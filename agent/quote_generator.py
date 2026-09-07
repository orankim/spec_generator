"""
LLM 기반 견적 서술 생성 — 요청서 5단계 "LLM이 담당" 목록(항목 의미 해석/본체·옵션·
부대비용 분류/제외 항목 설명/견적 구성 요약/주요 확인사항 설명)만 LLM에게 맡긴다.

이 모듈이 호출되는 시점에는 agent.quote_parser.analyze_quotation()이 이미 모든
금액 계산을 끝냈다 — 이 모듈은 그 결과(QuoteAnalysis, 전부 실제 문서에서 나온
값)를 프롬프트에 사실로만 주입하고, 출력 스키마(QuoteNarrative)에는 숫자 필드를
하나도 두지 않는다. 즉 LLM이 새 숫자를 "만들 수 있는 자리"가 구조적으로 없다
(요청서 7단계: 근거 없는 가격/옵션/비용 생성 금지).

숫자 필드가 없어도 자유 텍스트(예: equipment_vs_options_summary)에 LLM이 임의의
숫자를 문장으로 적어 넣을 가능성은 남아있다 — find_unrecognized_numbers()가
그 텍스트에 나타난 큰 숫자가 실제로 이 견적에 존재하는 값인지 대조하는 방어선을
추가로 제공한다(완벽한 차단은 아니며, 사람이 검토할 신호를 제공하는 안전망).
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, Field

from . import ollama_client
from .quote_schemas import QuoteAnalysis

_NO_FABRICATION_INSTRUCTION = (
    "아래는 이미 계산이 끝난 사실입니다. 이 정보에 없는 숫자, 옵션, 비용 항목, 제외 "
    "항목을 새로 만들지 마세요. 확인할 수 없는 내용은 '확인되지 않음'이라고 쓰세요. "
    "가격이 비싸다/저렴하다/시장가격 대비 어떻다는 판단을 절대 하지 마세요 — 비교할 "
    "근거 데이터가 없습니다."
)


class QuoteNarrative(BaseModel):
    """LLM 출력 스키마 — 의도적으로 숫자 필드가 없다(서술/분류 전용)."""

    equipment_vs_options_summary: Optional[str] = Field(
        default=None, description="본체/옵션/부대비용 구성을 사람이 읽을 요약 (숫자는 아래 프롬프트에 이미 준 값만 언급)"
    )
    excluded_items_explanation: Optional[str] = Field(default=None, description="제외 항목이 있다면 그 의미 설명")
    key_considerations: List[str] = Field(default_factory=list, description="확인이 필요한 주요 사항 목록")


def _fmt(value: Optional[float]) -> str:
    return f"{value:,.0f}" if value is not None else "확인되지 않음(UNKNOWN)"


def build_quote_facts_prompt(analysis: QuoteAnalysis) -> str:
    """analysis에 있는 사실만 나열한다 — 여기 없는 내용은 LLM도 알 수 없다."""
    q = analysis.quotation
    lines = [
        f"제조사: {q.general.manufacturer or 'UNKNOWN'}",
        f"모델: {q.general.model or 'UNKNOWN'}",
        f"통화: {q.general.currency or 'UNKNOWN'}",
        "",
        "[본체]",
    ]
    for item in q.equipment:
        lines.append(f"- {item.item}: 수량 {item.quantity:g}, 단가 {_fmt(item.unit_price)}, 금액 {_fmt(item.amount)}")

    lines.append("")
    lines.append("[옵션]" if q.options else "[옵션] 없음")
    for item in q.options:
        lines.append(f"- {item.item}: 수량 {item.quantity:g}, 단가 {_fmt(item.unit_price)}, 금액 {_fmt(item.amount)}")

    lines.append("")
    lines.append("[추가 비용]" if q.additional_costs else "[추가 비용] 없음")
    for item in q.additional_costs:
        lines.append(f"- {item.item}: {_fmt(item.amount)}")

    lines.append("")
    lines.append("[제외 항목]" if q.excluded_items else "[제외 항목] 없음")
    for item in q.excluded_items:
        lines.append(f"- {item}")

    lines.append("")
    lines.append(
        f"[합계] 본체 {_fmt(analysis.computed_equipment_amount)} / 옵션 {_fmt(analysis.computed_options_amount)} / "
        f"추가비용 {_fmt(analysis.computed_additional_cost_amount)} / 할인 {_fmt(analysis.computed_discount)} / "
        f"VAT {_fmt(analysis.computed_vat_amount)} / 최종 금액 {_fmt(analysis.computed_grand_total)}"
    )
    if analysis.issues:
        lines.append("")
        lines.append("[계산 오류 검출됨]")
        for issue in analysis.issues:
            lines.append(f"- {issue.message}")

    return "\n".join(lines)


def generate_quote_narrative(
    analysis: QuoteAnalysis, model: Optional[str] = None, host: Optional[str] = None
) -> QuoteNarrative:
    """QuoteAnalysis(전부 코드가 계산한 사실)를 LLM에게 넘겨 의미 해석/요약만
    받는다. 금액 계산은 이 함수 호출 이전에 이미 끝나 있다(agent.quote_parser)."""
    prompt = f"{_NO_FABRICATION_INSTRUCTION}\n\n{build_quote_facts_prompt(analysis)}"
    return ollama_client.parse_structured(prompt, QuoteNarrative, model=model, host=host)


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def find_unrecognized_numbers(text: str, analysis: QuoteAnalysis, min_magnitude: float = 1000.0) -> List[float]:
    """text(LLM이 생성한 서술)에 등장하는 큰 숫자 중, 이 견적의 실제 값(analysis에
    있는 모든 금액) 어디에도 없는 숫자를 찾는다. min_magnitude보다 작은 숫자(수량,
    퍼센트 등 오탐이 흔한 값)는 무시한다 — 완벽한 검증이 아니라 사람이 검토할
    신호를 주는 안전망이다."""
    known_values = {
        round(v)
        for v in (
            [analysis.computed_equipment_amount, analysis.computed_options_amount, analysis.computed_additional_cost_amount, analysis.computed_discount, analysis.computed_subtotal_before_vat, analysis.computed_vat_amount, analysis.computed_grand_total]
            + [i.amount for i in analysis.quotation.equipment]
            + [i.amount for i in analysis.quotation.options]
            + [i.unit_price for i in analysis.quotation.equipment]
            + [i.unit_price for i in analysis.quotation.options]
            + [i.amount for i in analysis.quotation.additional_costs]
        )
        if v is not None
    }
    found = []
    for match in _NUMBER_RE.findall(text):
        value = float(match.replace(",", ""))
        if value < min_magnitude:
            continue
        if round(value) not in known_values:
            found.append(value)
    return found
