"""
질문에 견적/가격 관련 의도가 있는지 판정 — Phase 6(사양+견적 통합)에서 "사양만
물었나 / 견적도 같이 물었나"를 가르는 유일한 분기 신호다.

결정론적 키워드 매칭만 쓴다(LLM 미사용) — 이 프로젝트 전체의 원칙(범주형 판정은
Python 코드로)과 동일하다. 오탐 방향을 "견적 의도 있음"쪽으로 살짝 관대하게
잡는다 — 사양 분석은 항상 기본으로 함께 수행되므로(agent.pipeline.analyze_with_quotes),
견적 섹션을 잘못 추가로 보여주는 것의 비용이 놓치는 것보다 훨씬 작다.
"""
from __future__ import annotations

import re

_QUOTE_KEYWORDS = (
    "견적",
    "가격",
    "비용",
    "원가",
    "금액",
    "할인",
    "vat",
    "부가세",
    "quote",
    "quotation",
    "price",
    "cost",
    "예산",
    "구매",
)


def wants_quote_analysis(text: str) -> bool:
    """text에 견적/가격 관련 키워드가 있으면 True. 사양 관련 키워드 유무와 무관하게
    독립적으로 판정한다 — 사양 분석(candidate matching)은 이 함수 결과와 무관하게
    항상 수행되고, 이 함수는 그 결과에 견적 분석을 추가할지만 결정한다."""
    if not text:
        return False
    text_lower = text.lower()
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text_lower) if kw.isascii() else kw in text_lower
        for kw in _QUOTE_KEYWORDS
    )
