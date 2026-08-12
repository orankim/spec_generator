"""
RequirementParser — 자연어 또는 조건 선택 UI 입력을 RequirementSchema로 변환한다.

두 입력 방식(자연어 / 조건 선택) 모두 최종적으로 동일한 RequirementSchema를
만들어내므로, 이후 파이프라인(Validator → Retriever → Generator)은 입력 방식과
무관하게 동일하게 동작한다 (기획안 9절).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import ollama_client
from .schemas import RequirementSchema

PARSE_PROMPT = """당신은 전극 검사기(인라인 계측 설비) 요구사항 분석 전문가입니다.
아래 [사용자 입력]을 읽고 요구사항을 구조화된 JSON으로 정리하세요.

반드시 지켜야 할 규칙:
- 사용자가 명시적으로 말하지 않은 값은 절대로 추측하지 마세요. 반드시 null(또는 빈 배열)로 남기세요.
  예: 사용자가 정확도를 언급하지 않았다면 required_accuracy_um은 null이어야 합니다.
- inspection_items에는 사용자가 실제로 언급한 검사 항목만 담으세요.
  (thickness, surface_defect, profile_3d, coating, edge_defect 등 중 해당하는 것만)
- measurement_method는 "비접촉/무접촉"이면 non_contact, "접촉식"이면 contact, 언급이 없으면 null로 두세요.
- measurement_principle은 레이저/OCT/간섭계/비전 중 사용자가 명시한 것만 채우고, 아니면 null로 두세요.

[사용자 입력]
{user_text}
"""


def parse_requirement_text(
    user_text: str,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> RequirementSchema:
    """자연어 요구사항 -> RequirementSchema (Ollama 구조화 출력 사용)."""
    prompt = PARSE_PROMPT.format(user_text=user_text)
    requirement = ollama_client.parse_structured(prompt, RequirementSchema, model=model, host=host)
    requirement.raw_text = user_text
    return requirement


def requirement_from_selection(selection: Dict[str, Any]) -> RequirementSchema:
    """
    조건 선택 UI(체크박스/드롭다운 등)에서 넘어온 값을 RequirementSchema로 변환한다.
    LLM을 거치지 않는 결정론적 매핑이며, selection의 키는 RequirementSchema 필드와
    1:1로 대응하도록 UI에서 구성한다 (예: {"target": {...}, "inspection_items": [...]}).
    """
    return RequirementSchema(**selection)
