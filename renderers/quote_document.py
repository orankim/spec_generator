"""
QuoteAnalysis -> {Markdown, Word} 견적서 두 출력 포맷이 공유하는 중간 데이터 모델.

renderers/candidate_specification.py(사양서)와 같은 원칙이다: Markdown/Word
렌더러가 QuoteAnalysis를 각자 독립적으로 재해석하면 두 포맷의 금액이 어긋날
수 있으므로, 이 파일이 만드는 QuoteDocumentData 하나를 두 렌더러가 그대로
소비한다.

금액은 전부 quotation.totals(문서에 문자 그대로 적힌 값)가 아니라 analysis.
computed_*(agent/quote_parser.py가 Equipment/Options/Additional Cost/Commercial
Terms에서 코드로 독립 재계산한 값)를 쓴다 — 요청서 5/10단계 핵심 원칙("금액은
LLM이나 문서에 적힌 값을 그대로 신뢰하지 않고 코드가 재계산/검증한다") 그대로,
채팅 카드(main.py renderQuoteSummaryBlock/quoteDetailRowsHtml)가 이미 쓰는
값과 동일한 소스를 다운로드 문서에도 재사용한다. 문서에 적힌 값과 재계산 값이
다르면(analysis.issues) 별도 "Calculation Issues" 섹션에 그대로 옮긴다 — 조용히
한쪽 값만 보여주고 넘어가지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from agent.quote_schemas import QuoteAnalysis

UNKNOWN = "UNKNOWN"


@dataclass
class QuoteLineItemRow:
    item: str
    quantity: str
    unit_price: str
    amount: str


@dataclass
class QuoteCostRow:
    item: str
    amount: str


@dataclass
class QuoteTotalRow:
    label: str
    amount: str


@dataclass
class QuoteDocumentData:
    title: str
    source_file: str
    general_rows: List[Tuple[str, str]]
    equipment_rows: List[QuoteLineItemRow]
    option_rows: List[QuoteLineItemRow]
    additional_cost_rows: List[QuoteCostRow]
    excluded_items: List[str]
    commercial_rows: List[Tuple[str, str]]
    total_rows: List[QuoteTotalRow]
    issue_messages: List[str]
    notes: List[str]


def _fmt_amount(value: Optional[float]) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:,.0f}"


def _fmt_opt(value: Optional[str]) -> str:
    return value if value else UNKNOWN


def _line_item_rows(items) -> List[QuoteLineItemRow]:
    return [
        QuoteLineItemRow(item=i.item, quantity=f"{i.quantity:g}", unit_price=_fmt_amount(i.unit_price), amount=_fmt_amount(i.amount))
        for i in items
    ]


def build_quote_document_data(analysis: QuoteAnalysis) -> QuoteDocumentData:
    quotation = analysis.quotation
    general = quotation.general
    terms = quotation.commercial_terms
    currency = general.currency or ""

    name_parts = [p for p in (general.manufacturer, general.model) if p]
    title = " ".join(name_parts) + " Quotation" if name_parts else "Equipment Quotation"

    general_rows = [
        ("Manufacturer", _fmt_opt(general.manufacturer)),
        ("Model", _fmt_opt(general.model)),
        ("Linked Specification", _fmt_opt(general.linked_specification)),
        ("Quote No.", _fmt_opt(general.quote_no)),
        ("Quote Date", _fmt_opt(general.quote_date)),
        ("Currency", _fmt_opt(general.currency)),
    ]

    additional_cost_rows = [QuoteCostRow(item=c.item, amount=_fmt_amount(c.amount)) for c in quotation.additional_costs]

    commercial_rows = [
        ("Discount", _fmt_opt(terms.discount_text)),
        ("Payment", _fmt_opt(terms.payment)),
        ("Delivery", _fmt_opt(terms.delivery)),
        ("Warranty", _fmt_opt(terms.warranty)),
        ("VAT", _fmt_opt(terms.vat_text)),
    ]

    # 코드가 재계산한 값만 보여준다(문서에 적힌 quotation.totals가 아니라
    # analysis.computed_*) — main.py의 quoteDetailRowsHtml()과 동일한 행 선택
    # 규칙: 0/None인 항목(옵션 없음, 부대비용 없음, 할인 없음, VAT 해당 없음)은
    # 행 자체를 만들지 않는다.
    total_rows = [QuoteTotalRow("Equipment Subtotal", _fmt_amount(analysis.computed_equipment_amount))]
    if analysis.computed_options_amount:
        total_rows.append(QuoteTotalRow("Options Subtotal", _fmt_amount(analysis.computed_options_amount)))
    if analysis.computed_additional_cost_amount:
        total_rows.append(QuoteTotalRow("Additional Cost Subtotal", _fmt_amount(analysis.computed_additional_cost_amount)))
    if analysis.computed_discount:
        total_rows.append(QuoteTotalRow("Discount", _fmt_amount(analysis.computed_discount)))
    if analysis.computed_vat_amount is not None:
        total_rows.append(QuoteTotalRow("VAT", _fmt_amount(analysis.computed_vat_amount)))
    total_rows.append(QuoteTotalRow("Grand Total", _fmt_amount(analysis.computed_grand_total)))

    return QuoteDocumentData(
        title=f"{title} ({currency})" if currency else title,
        source_file=quotation.source_file,
        general_rows=general_rows,
        equipment_rows=_line_item_rows(quotation.equipment),
        option_rows=_line_item_rows(quotation.options),
        additional_cost_rows=additional_cost_rows,
        excluded_items=list(quotation.excluded_items),
        commercial_rows=commercial_rows,
        total_rows=total_rows,
        issue_messages=[issue.message for issue in analysis.issues],
        notes=list(quotation.notes),
    )
