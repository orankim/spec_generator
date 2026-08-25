"""
카테고리형(범주형) 값 정규화/매칭 — 측정 원리(Measurement Principle), 검사 모드
(Inspection Mode: Inline/Offline), 측정 방식(Measurement Type: Contact/
Non-contact)처럼 표현은 다양하지만 실제로는 몇 가지 정해진 범주 중 하나를
가리키는 값을 다룬다. agent.units가 숫자+단위를 순수 함수로 다루는 것과
대칭되는 역할이며, 여기서도 LLM에 의존하지 않고 정규식/키워드 매칭으로
결정론적으로 처리한다(요청서: "LLM은 사용자 문장을 구조화하는 용도로만
사용, 하드 매칭은 Python 코드로 수행").

agent.requirement_parser(요구사항 raw_text)와 agent.candidate_matcher(후보
문서 원문) 양쪽에서 이 모듈의 동일한 키워드 표를 재사용해, 같은 개념이 항상
같은 canonical 라벨로 정규화되도록 보장한다 — 그래야 "OCT" vs "OCT 기반"처럼
표현이 달라도 정확히 같은 문자열로 비교(==)할 수 있다.

경계 처리 주의: Python 정규식의 \\b는 한글 음절도 "단어 문자"로 취급하므로
"비접촉식"처럼 키워드 뒤에 한글 조사/접미사가 공백 없이 바로 붙으면 매칭이
조용히 실패한다(agent.units.py에서 이미 한 번 겪은 문제와 동일한 원인). 이
모듈은 \\b 대신 "라틴 문자/숫자가 바로 붙어있지 않으면 OK"라는 완화된 경계
조건((?<![A-Za-z0-9])...(?![A-Za-z0-9]))을 쓴다 — 한글 조사/접미사는 자유롭게
허용하되, "oct"가 "doctor" 내부에서 잘못 매칭되는 것은 막는다.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# (매칭 키워드, canonical 라벨) — 위에서부터 순서대로 검사해 첫 매치를 쓴다.
# non_contact 계열이 "contact"라는 부분 문자열을 포함하므로 반드시 먼저 검사한다.
MEASUREMENT_PRINCIPLE_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("spectral reflectometry", "Spectral Reflectometry"),
    ("interferometry", "Interferometry"),
    ("간섭계", "Interferometry"),
    ("oct", "OCT"),
    ("machine vision", "Vision"),
    ("vision", "Vision"),
    ("비전", "Vision"),
    ("laser", "Laser"),
    ("레이저", "Laser"),
)

INSPECTION_MODE_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("inline", "inline"),
    ("인라인", "inline"),
    ("offline", "offline"),
    ("오프라인", "offline"),
)

MEASUREMENT_METHOD_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("non-contact", "non_contact"),
    ("non contact", "non_contact"),
    ("noncontact", "non_contact"),
    ("비접촉", "non_contact"),
    ("무접촉", "non_contact"),
    ("contact", "contact"),
    ("접촉식", "contact"),
    ("접촉", "contact"),
)


def _find_first(text: Optional[str], keywords: Tuple[Tuple[str, str], ...]) -> Optional[str]:
    if not text:
        return None
    for pattern, canonical in keywords:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(pattern)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            return canonical
    return None


def extract_measurement_principle(text: Optional[str]) -> Optional[str]:
    """text에서 측정 원리 키워드를 찾아 canonical 라벨(OCT/Interferometry/Laser/
    Vision/Spectral Reflectometry)로 정규화한다. 못 찾으면 None."""
    return _find_first(text, MEASUREMENT_PRINCIPLE_KEYWORDS)


def extract_inspection_mode(text: Optional[str]) -> Optional[str]:
    """text에서 Inline/Offline을 찾아 "inline"/"offline"(RequirementSchema.inline_offline과
    동일한 값)으로 정규화한다. 못 찾으면 None."""
    return _find_first(text, INSPECTION_MODE_KEYWORDS)


def extract_measurement_method(text: Optional[str]) -> Optional[str]:
    """text에서 접촉/비접촉을 찾아 "non_contact"/"contact"(RequirementSchema.
    measurement_method와 동일한 값)로 정규화한다. 못 찾으면 None."""
    return _find_first(text, MEASUREMENT_METHOD_KEYWORDS)


# ==========================================
# 검사 항목(inspection_items) 지원 여부 — 장비 문서의 Equipment Type/Measurement
# Principle 같은 서술 텍스트에 특정 검사 항목을 실제로 수행한다는 근거(positive) 또는
# 반증(negative)이 있는지 판정한다. "3D Profile"/"profile_3d"/"3d_profile" 같은
# 표현이 전부 같은 의미로 인식되도록, 소문자화 후 "3d"라는 단일 키워드로 정규화해
# 부분 문자열 비교한다(대소문자/공백/언더스코어 표기 차이에 흔들리지 않음) — 향후
# 다른 검사 항목을 추가할 때도 이 표(positive, negative) 하나만 채우면 된다.
# ==========================================
INSPECTION_ITEM_CAPABILITY_KEYWORDS: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "profile_3d": (("3d", "profilometry", "3차원"), ("2d",)),
}


def match_inspection_item_capability(item: str, text: Optional[str]) -> Optional[bool]:
    """장비 문서 원문(예: "Equipment Type: Electrode 3D Inspection System")에서
    특정 검사 항목(item)을 실제로 지원한다는 근거가 있는지 판정한다.
    True = 지원 근거 있음(PASS), False = 명시적 반증 있음(FAIL), None = 판단할
    근거가 없음(UNKNOWN) — 이 모듈의 다른 함수와 동일하게 LLM 없이 결정론적으로
    처리하며, 근거 없이 PASS/FAIL을 단정하지 않는다."""
    spec = INSPECTION_ITEM_CAPABILITY_KEYWORDS.get(item)
    if spec is None or not text:
        return None
    positive, negative = spec
    text_lower = text.lower()
    if any(kw in text_lower for kw in positive):
        return True
    if any(kw in text_lower for kw in negative):
        return False
    return None
