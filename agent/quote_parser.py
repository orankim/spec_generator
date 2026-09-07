"""
QuoteParser — sample_quotes/QUOTE-*.md(docs/QUOTATION_MARKDOWN_FORMAT.md 포맷)를
파싱하고, 금액을 코드로 재계산/검증한다.

핵심 원칙(요청서 5단계): **금액 계산은 LLM에게 맡기지 않는다.** Quantity x Unit
Price, Subtotal, Discount, VAT, Grand Total, 계산 오류 검증은 전부 이 모듈의
순수 함수(정규식 파싱 + 사칙연산)가 담당한다. LLM은 이 모듈이 만든 구조화된
결과를 받아 "의미 해석"(항목 분류/제외 항목 설명/견적 구성 요약)만 한다 —
그 LLM 호출은 이 모듈에 없다(Phase 6에서 pipeline에 연결할 때 추가된다).

agent/candidate_matcher.py의 라벨 기반 정규식 매칭 스타일을 그대로 따른다 —
같은 프로젝트 안에서 "문서의 라벨:값 쌍을 정규식으로 뽑는다"는 방식을 두 번
다르게 구현하지 않는다.
"""
from __future__ import annotations

import os
import re
from glob import glob
from typing import Dict, List, Optional, Tuple

from .paths import REPO_ROOT
from .quote_schemas import (
    QuotationSchema,
    QuoteAnalysis,
    QuoteCalculationIssue,
    QuoteCommercialTerms,
    QuoteCostItem,
    QuoteGeneral,
    QuoteLineItem,
    QuoteTotals,
)

DEFAULT_QUOTES_DIR = str(REPO_ROOT / "sample_quotes")

# 계산 비교 시 허용 오차. sample_quotes 생성기(scripts/generate_quotes_001_100.py)를
# 포함해 실제 견적서도 흔히 각 금액(특히 VAT)을 만 원/천 원 단위로 반올림해
# 표기한다 — 정확한 비율 계산값(예: 5,009,000)과 반올림 표기값(5,010,000)의 차이는
# "계산 오류"가 아니라 정상적인 반올림 관행이다. 10,000원은 이 프로젝트 sample
# 데이터의 반올림 단위(만 원)에서 발생할 수 있는 최대 오차(그 절반인 5,000원)보다
# 넉넉히 크면서도, 실제 계산 오류 테스트 데이터(sample_quotes/error_cases/, 최소
# 오차 3,000,000원)보다는 300배 작다 — 진짜 오류를 놓치지 않으면서 반올림 잡음만
# 흡수한다.
_TOLERANCE = 10_000.0

_SECTION_RE = re.compile(r"(?:^|\n)##\s+(.+?)\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL)
_BULLET_FIELD_RE = re.compile(r"(?:^|\n)[-*]\s*([^:：\n]+)[:：]\s*(.+)")


def _split_sections(text: str) -> Dict[str, str]:
    """'## Section' 헤딩 기준으로 본문을 나눈다. 키는 헤딩 원문(소문자화 없음)."""
    sections: Dict[str, str] = {}
    for name, body in _SECTION_RE.findall(text):
        sections[name.strip()] = body.strip()
    return sections


def _parse_bullet_fields(body: str) -> Dict[str, str]:
    """'- Label: Value' 불릿 목록을 {Label: Value} 딕셔너리로 만든다."""
    return {label.strip(): value.strip() for label, value in _BULLET_FIELD_RE.findall(body)}


def _parse_number(text: Optional[str]) -> Optional[float]:
    """'150,000,000' / '-8,000,000' / '150,000,000 KRW' 같은 표기에서 숫자만 뽑는다.
    통화 기호/단위 텍스트가 붙어 있어도 첫 숫자 토큰만 취한다. 숫자가 없으면 None
    (0으로 추측하지 않는다 — UNKNOWN을 사실로 바꾸지 않는다는 원칙과 동일)."""
    if not text:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _parse_table_rows_n(body: str, ncols: int) -> List[List[str]]:
    """'| a | b | c | d |' 형식의 표 행을 ncols개 셀 리스트로 뽑는다. 헤더/구분선
    행은 제외한다."""
    rows: List[List[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != ncols:
            continue
        if cells[0].lower() in ("item",):
            continue
        if all(set(c) <= {"-"} for c in cells if c):
            continue
        rows.append(cells)
    return rows


def _parse_line_items(body: str) -> List[QuoteLineItem]:
    """Equipment/Options 표(Item/Quantity/Unit Price/Amount, 4열)를 파싱한다."""
    items: List[QuoteLineItem] = []
    for item, qty, price, amount in _parse_table_rows_n(body, 4):
        qty_v = _parse_number(qty)
        price_v = _parse_number(price)
        amount_v = _parse_number(amount)
        if qty_v is None or price_v is None or amount_v is None:
            continue
        items.append(QuoteLineItem(item=item, quantity=qty_v, unit_price=price_v, amount=amount_v))
    return items


def _parse_cost_items(body: str) -> List[QuoteCostItem]:
    """Additional Cost 표(Item/Amount, 2열)를 파싱한다."""
    items: List[QuoteCostItem] = []
    for item, amount in _parse_table_rows_n(body, 2):
        amount_v = _parse_number(amount)
        if amount_v is None:
            continue
        items.append(QuoteCostItem(item=item, amount=amount_v))
    return items


def _parse_excluded_items(body: str) -> List[str]:
    items = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("-") or line.startswith("*"):
            text = line.lstrip("-*").strip()
            if text and text.lower() != "none":
                items.append(text)
    return items


def _parse_totals(body: str) -> QuoteTotals:
    rows = {label: _parse_number(value) for label, value in _parse_table_rows_n(body, 2)}
    # Grand Total 라벨은 "Grand Total" 또는 "Grand Total (excl. VAT)" 두 형태다 —
    # docs/QUOTATION_MARKDOWN_FORMAT.md/scripts/generate_quotes_001_100.py 참고.
    grand_total_key = next((k for k in rows if k.startswith("Grand Total")), None)
    vat_key = next((k for k in rows if k.startswith("VAT")), None)
    return QuoteTotals(
        equipment_subtotal=rows.get("Equipment Subtotal"),
        options_subtotal=rows.get("Options Subtotal"),
        additional_cost_subtotal=rows.get("Additional Cost Subtotal"),
        discount=rows.get("Discount"),
        subtotal_before_vat=rows.get("Subtotal (before VAT)"),
        vat_amount=rows.get(vat_key) if vat_key else None,
        vat_excluded_from_grand_total=bool(grand_total_key and "excl. VAT" in grand_total_key),
        grand_total=rows.get(grand_total_key) if grand_total_key else None,
    )


def parse_quotation_markdown(text: str, source_file: str) -> QuotationSchema:
    """QUOTE-*.md 원문 -> QuotationSchema. 문서에 적힌 값만 그대로 담는다(계산 없음)."""
    sections = _split_sections(text)

    general_fields = _parse_bullet_fields(sections.get("General", ""))
    general = QuoteGeneral(
        manufacturer=general_fields.get("Manufacturer"),
        model=general_fields.get("Model"),
        linked_specification=general_fields.get("Linked Specification"),
        quote_no=general_fields.get("Quote No."),
        quote_date=general_fields.get("Quote Date"),
        currency=general_fields.get("Currency"),
    )

    commercial_fields = _parse_bullet_fields(sections.get("Commercial Terms", ""))
    commercial = QuoteCommercialTerms(
        discount_text=commercial_fields.get("Discount"),
        payment=commercial_fields.get("Payment"),
        delivery=commercial_fields.get("Delivery"),
        warranty=commercial_fields.get("Warranty"),
        vat_text=commercial_fields.get("VAT"),
    )

    notes_body = sections.get("Notes", "")
    notes = [line.strip() for line in notes_body.splitlines() if line.strip()]

    return QuotationSchema(
        source_file=source_file,
        general=general,
        equipment=_parse_line_items(sections.get("Equipment", "")),
        options=_parse_line_items(sections.get("Options", "")),
        additional_costs=_parse_cost_items(sections.get("Additional Cost", "")),
        excluded_items=_parse_excluded_items(sections.get("Excluded Items", "")),
        commercial_terms=commercial,
        totals=_parse_totals(sections.get("Total", "")),
        notes=notes,
    )


def load_quotation(path: str) -> QuotationSchema:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_quotation_markdown(text, os.path.basename(path))


# ==========================================
# 금액 계산 / 검증 — 전부 코드, LLM 미사용 (요청서 5단계)
# ==========================================
def _parse_discount_amount(commercial: QuoteCommercialTerms, base_for_percent: float) -> float:
    """Discount 필드는 정액('-8,000,000 KRW')과 퍼센트('5%') 두 표기를 모두 허용한다
    (docs/QUOTATION_MARKDOWN_FORMAT.md). 'None'/빈 값이면 0으로 취급한다(할인 없음은
    UNKNOWN이 아니라 확정적으로 0이다 — 문서가 명시적으로 'Discount: None'이라고
    쓴 경우이므로 값이 없어서 추측하는 것과는 다르다)."""
    text = commercial.discount_text
    if not text or text.strip().lower() == "none":
        return 0.0
    if "%" in text:
        pct = _parse_number(text)
        if pct is None:
            return 0.0
        return -abs(base_for_percent * pct / 100.0)
    value = _parse_number(text)
    if value is None:
        return 0.0
    # 정액 표기는 부호를 그대로 신뢰한다(양수로 적혀 있어도 "할인 금액"의 의미이므로
    # 음수로 정규화한다 — Total 표의 Discount 행과 동일한 부호 규칙).
    return -abs(value) if value > 0 else value


def analyze_quotation(quotation: QuotationSchema) -> QuoteAnalysis:
    """quotation에 적힌 개별 항목(Equipment/Options/Additional Cost)에서 Subtotal/
    Discount/VAT/Grand Total을 코드로 독립 재계산하고, 문서의 '## Total' 표에 적힌
    값(quotation.totals)과 비교해 다르면 QuoteCalculationIssue로 기록한다."""
    issues: List[QuoteCalculationIssue] = []

    for item in quotation.equipment + quotation.options:
        expected = item.quantity * item.unit_price
        if abs(expected - item.amount) > _TOLERANCE:
            issues.append(
                QuoteCalculationIssue(
                    field=f"line_item:{item.item}",
                    message=(
                        f"'{item.item}' Amount({item.amount:,.0f})가 Quantity({item.quantity:g}) x "
                        f"Unit Price({item.unit_price:,.0f}) = {expected:,.0f}과 다릅니다."
                    ),
                    stated_value=item.amount,
                    computed_value=expected,
                )
            )

    computed_equipment = sum(i.amount for i in quotation.equipment)
    computed_options = sum(i.amount for i in quotation.options)
    computed_additional = sum(i.amount for i in quotation.additional_costs)

    stated_discount = quotation.totals.discount
    computed_subtotal_pre_discount = computed_equipment + computed_options + computed_additional
    computed_discount = (
        stated_discount
        if stated_discount is not None
        else _parse_discount_amount(quotation.commercial_terms, computed_subtotal_pre_discount)
    )
    computed_subtotal = computed_subtotal_pre_discount + computed_discount

    computed_vat: Optional[float] = None
    computed_grand_total: Optional[float] = None
    vat_text = (quotation.commercial_terms.vat_text or "").lower()
    if "not applicable" not in vat_text and "면세" not in vat_text:
        vat_pct = _parse_number(quotation.commercial_terms.vat_text)
        if "included" in vat_text and quotation.totals.vat_amount is None:
            # VAT가 총액에 이미 포함된다고 명시했고 별도 VAT 행이 없는 경우 —
            # 재계산 대상에서 VAT를 분리하지 않는다(문서 구조 자체가 그렇게 설계됨).
            computed_grand_total = computed_subtotal
        elif vat_pct is not None:
            computed_vat = computed_subtotal * vat_pct / 100.0
            computed_grand_total = (
                computed_subtotal if quotation.totals.vat_excluded_from_grand_total else computed_subtotal + computed_vat
            )

    def _check(field: str, stated: Optional[float], computed: Optional[float], label: str) -> None:
        if stated is None or computed is None:
            return
        if abs(stated - computed) > _TOLERANCE:
            issues.append(
                QuoteCalculationIssue(
                    field=field,
                    message=f"{label}: 문서에 적힌 값({stated:,.0f})이 재계산 값({computed:,.0f})과 다릅니다.",
                    stated_value=stated,
                    computed_value=computed,
                )
            )

    _check("equipment_subtotal", quotation.totals.equipment_subtotal, computed_equipment, "Equipment Subtotal")
    if quotation.options:
        _check("options_subtotal", quotation.totals.options_subtotal, computed_options, "Options Subtotal")
    if quotation.additional_costs:
        _check(
            "additional_cost_subtotal",
            quotation.totals.additional_cost_subtotal,
            computed_additional,
            "Additional Cost Subtotal",
        )
    _check("subtotal_before_vat", quotation.totals.subtotal_before_vat, computed_subtotal, "Subtotal (before VAT)")
    if computed_vat is not None:
        _check("vat_amount", quotation.totals.vat_amount, computed_vat, "VAT")
    if computed_grand_total is not None:
        _check("grand_total", quotation.totals.grand_total, computed_grand_total, "Grand Total")

    return QuoteAnalysis(
        quotation=quotation,
        computed_equipment_amount=computed_equipment,
        computed_options_amount=computed_options,
        computed_additional_cost_amount=computed_additional,
        computed_discount=computed_discount,
        computed_subtotal_before_vat=computed_subtotal,
        computed_vat_amount=computed_vat,
        computed_grand_total=computed_grand_total,
        issues=issues,
    )


# ==========================================
# SPEC <-> QUOTE 연결 (요청서 3단계: 파일명 번호 기반 연결)
# ==========================================
_SPEC_ID_RE = re.compile(r"SPEC-(\d+)", re.IGNORECASE)


def find_quote_files_for_spec(spec_id: str, quotes_dir: Optional[str] = None) -> List[str]:
    """spec_id(예: 'SPEC-051' 또는 'SPEC-051.md')에 연결된 QUOTE 파일 전부를 찾는다.
    기본 견적(QUOTE-051.md)과 Case H 대안 견적(QUOTE-051-B.md 등)을 모두 포함한다.
    error_cases/ 아래 파일은 정의상 SPEC과 연결하지 않으므로 검색 대상이 아니다
    (docs/QUOTATION_MARKDOWN_FORMAT.md)."""
    m = _SPEC_ID_RE.search(spec_id)
    if not m:
        return []
    num = m.group(1)
    base = quotes_dir or DEFAULT_QUOTES_DIR
    pattern_exact = os.path.join(base, f"QUOTE-{num}.md")
    pattern_variant = os.path.join(base, f"QUOTE-{num}-*.md")
    return sorted(glob(pattern_exact) + glob(pattern_variant))


def load_quotations_for_spec(spec_id: str, quotes_dir: Optional[str] = None) -> List[QuotationSchema]:
    return [load_quotation(p) for p in find_quote_files_for_spec(spec_id, quotes_dir)]


# ==========================================
# 견적 비교 — "가장 낮은 장비" 같은 질문(요청서 10단계 테스트 3)에 쓴다.
# 정렬/최솟값 계산은 순수 코드다(여기도 LLM 없음).
# ==========================================
def rank_by_grand_total(
    quote_analyses: Dict[str, List[QuoteAnalysis]], ascending: bool = True
) -> List[Tuple[str, QuoteAnalysis]]:
    """spec_id -> [QuoteAnalysis, ...] 딕셔너리(agent.pipeline.attach_quote_analyses의
    반환값과 동일 형태)를 (spec_id, analysis) 쌍의 flat 리스트로 펴고 Grand Total
    기준으로 정렬한다. Grand Total이 없는(UNKNOWN) 항목은 비교 불가하므로 제외한다
    — "가장 낮다"는 판단에 UNKNOWN을 임의의 값(0 등)으로 취급해 끼워 넣지 않는다.
    동일 장비에 여러 견적(Case H)이 있으면 전부 개별 항목으로 비교 대상에 들어간다."""
    flat: List[Tuple[str, QuoteAnalysis]] = [
        (spec_id, analysis)
        for spec_id, analyses in quote_analyses.items()
        for analysis in analyses
        if analysis.computed_grand_total is not None
    ]
    flat.sort(key=lambda pair: pair[1].computed_grand_total, reverse=not ascending)
    return flat


def find_cheapest(quote_analyses: Dict[str, List[QuoteAnalysis]]) -> Optional[Tuple[str, QuoteAnalysis]]:
    ranked = rank_by_grand_total(quote_analyses, ascending=True)
    return ranked[0] if ranked else None
