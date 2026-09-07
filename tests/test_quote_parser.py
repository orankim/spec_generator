"""
Phase 5 — 견적 분석 엔진(agent/quote_parser.py) 테스트.

핵심 검증: 금액 계산(Quantity x Unit Price, Subtotal, Discount, VAT, Grand
Total)은 전부 코드가 담당하며, LLM은 이 모듈 어디에도 등장하지 않는다
(agent/quote_parser.py에 ollama_client/langchain import가 전혀 없음을 이
파일이 스스로도 확인한다 — test_no_llm_import_in_quote_parser).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent import quote_parser
from agent.quote_parser import (
    DEFAULT_QUOTES_DIR,
    analyze_quotation,
    find_cheapest,
    find_quote_files_for_spec,
    load_quotation,
    load_quotations_for_spec,
    parse_quotation_markdown,
    rank_by_grand_total,
)
from agent.quote_schemas import QuotationSchema

_REPO_ROOT = Path(__file__).resolve().parent.parent
_QUOTES_DIR = _REPO_ROOT / "sample_quotes"
_ERROR_DIR = _QUOTES_DIR / "error_cases"


# ---------------------------------------------------------------------------
# 0. LLM 미사용 회귀 가드
# ---------------------------------------------------------------------------
def test_no_llm_import_in_quote_parser():
    """요청서 5단계 핵심 원칙: 금액 계산은 LLM에게 맡기지 않는다. 이 모듈이
    ollama_client/langchain을 import하지 않는지 AST로 정적 확인한다(문자열
    검색이 아니라 실제 import 문만 본다 — 주석에 그 단어가 있어도 오탐하지 않음)."""
    source = (_REPO_ROOT / "agent" / "quote_parser.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = ("ollama_client", "langchain", "ollama")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for n in names:
            assert not any(f in n for f in forbidden), f"quote_parser.py가 {n}을 import합니다 — 금액 계산에 LLM을 쓰면 안 됩니다."


# ---------------------------------------------------------------------------
# 1~4. 본체/옵션/추가비용 금액, 수량 x 단가
# ---------------------------------------------------------------------------
_SAMPLE_QUOTE = """# Equipment Quotation

## General

- Manufacturer: TestCo
- Model: TC-100
- Linked Specification: SPEC-999.md
- Quote No.: Q-TEST-0001
- Quote Date: 2026-01-01
- Currency: KRW

## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestCo TC-100 (Main Unit) | 1 | 100,000,000 | 100,000,000 |

## Options

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| Extended Warranty | 2 | 5,000,000 | 10,000,000 |

## Additional Cost

| Item | Amount |
|---|---|
| Installation | 8,000,000 |
| Training | 2,000,000 |

## Excluded Items

- Site preparation
- Consumables

## Commercial Terms

- Discount: -6,000,000 KRW
- Payment: 50/50
- Delivery: 8 weeks
- Warranty: 12 months
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 100,000,000 |
| Options Subtotal | 10,000,000 |
| Additional Cost Subtotal | 10,000,000 |
| Discount | -6,000,000 |
| Subtotal (before VAT) | 114,000,000 |
| VAT (10%) | 11,400,000 |
| Grand Total | 125,400,000 |

## Notes

SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다.
"""


@pytest.fixture
def parsed() -> QuotationSchema:
    return parse_quotation_markdown(_SAMPLE_QUOTE, "QUOTE-TEST.md")


def test_1_equipment_amount(parsed):
    assert len(parsed.equipment) == 1
    assert parsed.equipment[0].amount == 100_000_000


def test_2_options_amount(parsed):
    assert len(parsed.options) == 1
    assert parsed.options[0].amount == 10_000_000


def test_3_additional_cost_amount(parsed):
    assert len(parsed.additional_costs) == 2
    assert sum(c.amount for c in parsed.additional_costs) == 10_000_000


def test_4_quantity_times_unit_price(parsed):
    option = parsed.options[0]
    assert option.quantity == 2
    assert option.unit_price == 5_000_000
    assert option.quantity * option.unit_price == option.amount


# ---------------------------------------------------------------------------
# 5~7. 할인/VAT/Grand Total 재계산이 문서 값과 일치
# ---------------------------------------------------------------------------
def test_5_discount(parsed):
    analysis = analyze_quotation(parsed)
    assert analysis.computed_discount == -6_000_000
    assert not any(i.field == "subtotal_before_vat" for i in analysis.issues)


def test_6_vat(parsed):
    analysis = analyze_quotation(parsed)
    # (100,000,000 + 10,000,000 + 10,000,000 - 6,000,000) * 10% = 11,400,000
    assert analysis.computed_vat_amount == pytest.approx(11_400_000, abs=1)
    assert not any(i.field == "vat_amount" for i in analysis.issues)


def test_7_grand_total(parsed):
    analysis = analyze_quotation(parsed)
    assert analysis.computed_grand_total == pytest.approx(125_400_000, abs=1)
    assert analysis.is_calculation_consistent


# ---------------------------------------------------------------------------
# 8. 계산 오류 검출 — sample_quotes/error_cases/의 5개 파일 전부 실제로 잡히는지
# ---------------------------------------------------------------------------
def test_8_all_error_case_files_are_detected():
    error_files = sorted(_ERROR_DIR.glob("QUOTE-ERR-*.md"))
    assert len(error_files) >= 5, "error_cases/에 계산 오류 테스트 데이터가 부족합니다"
    for path in error_files:
        quotation = load_quotation(str(path))
        analysis = analyze_quotation(quotation)
        assert analysis.issues, f"{path.name}에 심어둔 계산 오류가 검출되지 않았습니다"


def test_8b_normal_quotes_have_no_false_positive_errors():
    """정상 데이터(sample_quotes/QUOTE-*.md, error_cases 제외) 전부가 계산 오류
    없이 통과해야 한다 — 검증 로직 자체가 너무 엄격해 정상 데이터를 오탐하면
    안 된다(반올림 허용 오차 회귀 가드)."""
    normal_files = sorted(p for p in _QUOTES_DIR.glob("QUOTE-*.md"))
    assert len(normal_files) >= 100
    false_positives = []
    for path in normal_files:
        quotation = load_quotation(str(path))
        analysis = analyze_quotation(quotation)
        if analysis.issues:
            false_positives.append((path.name, [i.message for i in analysis.issues]))
    assert not false_positives, f"정상 데이터에서 오탐 발생: {false_positives}"


# ---------------------------------------------------------------------------
# 9. 제외 항목
# ---------------------------------------------------------------------------
def test_9_excluded_items(parsed):
    assert parsed.excluded_items == ["Site preparation", "Consumables"]


def test_9b_no_excluded_items_section_gives_empty_list():
    text = _SAMPLE_QUOTE.replace(
        "## Excluded Items\n\n- Site preparation\n- Consumables\n\n", ""
    )
    quotation = parse_quotation_markdown(text, "QUOTE-TEST2.md")
    assert quotation.excluded_items == []


# ---------------------------------------------------------------------------
# 10. SPEC <-> QUOTE 연결
# ---------------------------------------------------------------------------
def test_10_spec_quote_linking_by_filename_number():
    files = find_quote_files_for_spec("SPEC-001")
    assert any(f.endswith("QUOTE-001.md") for f in files)


def test_10b_linked_specification_field_matches_filename_convention():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-053.md"))
    assert quotation.general.linked_specification == "SPEC-053.md"


# ---------------------------------------------------------------------------
# 11/12. 장비별 견적 비교 / 동일 장비의 다른 견적 비교(Case H)
# ---------------------------------------------------------------------------
def test_11_compare_grand_totals_across_different_equipment():
    q1 = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    q2 = load_quotation(str(_QUOTES_DIR / "QUOTE-002.md"))
    a1, a2 = analyze_quotation(q1), analyze_quotation(q2)
    assert a1.computed_grand_total is not None
    assert a2.computed_grand_total is not None
    assert a1.quotation.general.model != a2.quotation.general.model


def test_12_same_equipment_two_quotations_differ_case_h():
    quotations = load_quotations_for_spec("SPEC-051")
    assert len(quotations) == 2, "SPEC-051은 Case H 대안 견적(QUOTE-051-B.md)을 가져야 합니다"
    manufacturers = {q.general.manufacturer for q in quotations}
    models = {q.general.model for q in quotations}
    assert manufacturers == {"MultiInspect"}
    assert models == {"MI-800"}
    totals = [analyze_quotation(q).computed_grand_total for q in quotations]
    assert totals[0] != totals[1], "동일 장비의 두 견적 구성이 실제로 달라야 합니다"


# ---------------------------------------------------------------------------
# 13. 견적 없는 장비 처리
# ---------------------------------------------------------------------------
def test_13_no_quote_for_equipment_returns_empty_not_error():
    files = find_quote_files_for_spec("SPEC-999999")
    assert files == []
    quotations = load_quotations_for_spec("SPEC-999999")
    assert quotations == []


# ---------------------------------------------------------------------------
# 14. 근거 없는 가격 생성 방지 — 파서가 문서에 없는 값을 지어내지 않는다
# ---------------------------------------------------------------------------
def test_14_missing_fields_stay_none_not_fabricated():
    minimal = """# Equipment Quotation

## General

- Manufacturer: OnlyMfr
- Model: OM-1

## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| OnlyMfr OM-1 (Main Unit) | 1 | 10,000,000 | 10,000,000 |

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 10,000,000 |
"""
    quotation = parse_quotation_markdown(minimal, "QUOTE-MIN.md")
    assert quotation.general.quote_no is None
    assert quotation.general.currency is None
    assert quotation.totals.vat_amount is None
    assert quotation.totals.grand_total is None
    assert quotation.options == []
    assert quotation.additional_costs == []

    analysis = analyze_quotation(quotation)
    # Grand Total/VAT이 문서에 없으면 재계산값도 None으로 남아야 한다 — 없는 값을
    # "0으로 가정"하거나 임의의 숫자로 채우지 않는다.
    assert analysis.computed_vat_amount is None
    assert analysis.computed_grand_total is None


# ---------------------------------------------------------------------------
# 15. 가격 적정성 판단 근거 부족 처리 — 스키마 자체에 그런 필드가 없어 구조적으로
# "비싸다/저렴하다/시장가격 대비" 같은 판단을 만들어낼 수 없음을 확인한다.
# ---------------------------------------------------------------------------
def test_15_schema_has_no_price_reasonableness_fields():
    from agent.quote_schemas import QuoteAnalysis, QuotationSchema as _QS

    forbidden_substrings = ("market", "reasonable", "적정", "시장가격", "fair_price")
    for model in (_QS, QuoteAnalysis):
        field_names = " ".join(model.model_fields.keys()).lower()
        for bad in forbidden_substrings:
            assert bad.lower() not in field_names, (
                f"{model.__name__}에 가격 적정성 판단을 암시하는 필드({bad})가 있습니다 — "
                "요청서 7단계: 비교 근거 없는 가격 적정성 판단 금지."
            )


# ---------------------------------------------------------------------------
# 견적 비교(최솟값) — 요청서 10단계 테스트 3 "견적이 가장 낮은 장비"
# ---------------------------------------------------------------------------
def test_find_cheapest_across_multiple_candidates():
    quote_analyses = {
        "SPEC-001.md": [analyze_quotation(load_quotation(str(_QUOTES_DIR / "QUOTE-001.md")))],
        "SPEC-002.md": [analyze_quotation(load_quotation(str(_QUOTES_DIR / "QUOTE-002.md")))],
    }
    cheapest_spec_id, cheapest_analysis = find_cheapest(quote_analyses)
    all_totals = {sid: a[0].computed_grand_total for sid, a in quote_analyses.items()}
    assert cheapest_analysis.computed_grand_total == min(all_totals.values())
    assert cheapest_spec_id == min(all_totals, key=all_totals.get)


def test_find_cheapest_ignores_unknown_grand_total():
    minimal = parse_quotation_markdown(
        """# Equipment Quotation

## General

- Manufacturer: NoTotalCo
- Model: NT-1

## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| NoTotalCo NT-1 (Main Unit) | 1 | 1 | 1 |
""",
        "QUOTE-NOTOTAL.md",
    )
    quote_analyses = {
        "SPEC-NOTOTAL.md": [analyze_quotation(minimal)],
        "SPEC-001.md": [analyze_quotation(load_quotation(str(_QUOTES_DIR / "QUOTE-001.md")))],
    }
    result = find_cheapest(quote_analyses)
    assert result is not None
    assert result[0] == "SPEC-001.md", "Grand Total이 UNKNOWN인 항목이 최솟값으로 잘못 선택되었습니다"


def test_find_cheapest_returns_none_when_no_quotes():
    assert find_cheapest({}) is None


def test_rank_by_grand_total_descending():
    quote_analyses = {
        "SPEC-001.md": [analyze_quotation(load_quotation(str(_QUOTES_DIR / "QUOTE-001.md")))],
        "SPEC-002.md": [analyze_quotation(load_quotation(str(_QUOTES_DIR / "QUOTE-002.md")))],
    }
    ranked = rank_by_grand_total(quote_analyses, ascending=False)
    totals = [a.computed_grand_total for _, a in ranked]
    assert totals == sorted(totals, reverse=True)
