"""
견적(Quotation) Pydantic 스키마 — docs/QUOTATION_MARKDOWN_FORMAT.md(Phase 3)가
정의한 포맷을 그대로 구조화한다. agent/schemas.py(사양서)와 분리한 이유는 두
도메인(사양/견적)이 서로 다른 라이프사이클로 성장할 것이기 때문이다 — SPEC
파싱 로직에 QUOTE 필드가 섞여 스키마가 비대해지는 것을 막는다.

금액 계산(Quantity x Unit Price, Subtotal, VAT, Grand Total)은 이 스키마
자체에는 없다 — 문서에 "적힌 값"만 담는다(사실 그대로 저장). 계산/검증은
agent/quote_parser.py의 순수 함수(코드, LLM 미사용)가 별도로 수행한다
(요청서 5단계 핵심 원칙: 금액 계산을 LLM에게 맡기지 않는다).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class QuoteLineItem(BaseModel):
    """Equipment/Options 표의 한 행(Item/Quantity/Unit Price/Amount 전부 있음)."""

    item: str
    quantity: float
    unit_price: float
    amount: float


class QuoteCostItem(BaseModel):
    """Additional Cost 표의 한 행(Item/Amount만 있음 — Quantity/Unit Price 없음)."""

    item: str
    amount: float


class QuoteGeneral(BaseModel):
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    linked_specification: Optional[str] = Field(
        default=None, description="문서에 적힌 'Linked Specification' 필드 원문 (예: 'SPEC-053.md')"
    )
    quote_no: Optional[str] = None
    quote_date: Optional[str] = None
    currency: Optional[str] = None


class QuoteCommercialTerms(BaseModel):
    discount_text: Optional[str] = Field(default=None, description="Discount 행 원문 (예: '-8,000,000 KRW', '5%', 'None')")
    payment: Optional[str] = None
    delivery: Optional[str] = None
    warranty: Optional[str] = None
    vat_text: Optional[str] = Field(default=None, description="VAT 행 원문 (예: '10% (included in Grand Total below)')")


class QuoteTotals(BaseModel):
    """'## Total' 표에 실제로 적혀 있는 값 — 문서가 주장하는 값이다. 이 값이 맞는지는
    agent.quote_parser.verify_quotation()이 별도로 재계산해 검증하며, 여기서는
    검증하지 않고 그대로 저장만 한다(요청값과 재계산값 혼동 방지)."""

    equipment_subtotal: Optional[float] = None
    options_subtotal: Optional[float] = None
    additional_cost_subtotal: Optional[float] = None
    discount: Optional[float] = None
    subtotal_before_vat: Optional[float] = None
    vat_amount: Optional[float] = None
    vat_excluded_from_grand_total: bool = Field(
        default=False, description="Grand Total 행 라벨에 '(excl. VAT)'가 있으면 True (VAT가 Grand Total에 더해지지 않은 문서)"
    )
    grand_total: Optional[float] = None


class QuotationSchema(BaseModel):
    """QUOTE-*.md 한 파일을 그대로 구조화한 것 — 문서에 적힌 값만 담는다(사실 저장)."""

    source_file: str = Field(description="예: 'QUOTE-053.md'")
    general: QuoteGeneral = Field(default_factory=QuoteGeneral)
    equipment: List[QuoteLineItem] = Field(default_factory=list)
    options: List[QuoteLineItem] = Field(default_factory=list)
    additional_costs: List[QuoteCostItem] = Field(default_factory=list)
    excluded_items: List[str] = Field(default_factory=list)
    commercial_terms: QuoteCommercialTerms = Field(default_factory=QuoteCommercialTerms)
    totals: QuoteTotals = Field(default_factory=QuoteTotals)
    notes: List[str] = Field(default_factory=list)


class QuoteCalculationIssue(BaseModel):
    """코드가 재계산한 값과 문서에 적힌 값이 다를 때 생기는 이슈 — 요청서 5단계
    '계산 오류 검증'의 산출물. LLM이 생성하지 않는다."""

    field: str = Field(description="예: 'equipment_subtotal', 'vat_amount', 'grand_total'")
    message: str
    stated_value: Optional[float] = None
    computed_value: Optional[float] = None


class QuoteAnalysis(BaseModel):
    """quote_parser.analyze_quotation()의 결과 — 문서에 적힌 값(quotation)과 코드가
    독립적으로 재계산한 값(computed_*)을 나란히 두고, 둘이 다르면 issues에 기록한다."""

    quotation: QuotationSchema

    computed_equipment_amount: float = 0.0
    computed_options_amount: float = 0.0
    computed_additional_cost_amount: float = 0.0
    computed_discount: float = 0.0
    computed_subtotal_before_vat: float = 0.0
    computed_vat_amount: Optional[float] = None
    computed_grand_total: Optional[float] = None

    issues: List[QuoteCalculationIssue] = Field(default_factory=list)

    @property
    def is_calculation_consistent(self) -> bool:
        return len(self.issues) == 0
