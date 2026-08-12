"""
SpecificationGenerator — Requirement + 검색된 사내 문서를 바탕으로
최종 Specification JSON을 생성한다.

핵심 원칙(기획안 12절)을 코드로 강제하기 위해 두 단계로 나눈다:

1. **결정론적 사전 채움(pre-fill)**: 사용자가 요구사항에서 명시한 값은
   LLM을 거치지 않고 파이썬 코드로 그대로 옮겨 담고 status를
   "USER_DEFINED"로 고정한다. LLM이 이 값을 덮어쓸 수 없다.
2. **LLM 보강**: 나머지 빈 필드만, 검색된 사내 문서를 근거로
   Ollama 구조화 출력으로 채운다. 문서에 없는 값은 null로 두거나
   "INFERRED"로 표시하도록 프롬프트에서 명시적으로 요구한다.

생성 후 SourcedNumber 중 status가 INFERRED/UNKNOWN인 필드를 모아
top-level `needs_confirmation`에 자동으로 채운다 — LLM이 스스로 이
목록을 정확히 관리할 것이라고 신뢰하지 않기 위함이다.
"""
from __future__ import annotations

import os
from typing import List, Optional

from langchain_core.documents import Document

from . import ollama_client
from .schemas import RequirementSchema, SourcedNumber, SpecificationSchema

GENERATE_PROMPT = """당신은 전극 검사기(계측 설비) 사양서를 작성하는 베테랑 엔지니어입니다.
아래 [사용자 요구사항]과 [사내 참고 자료]를 바탕으로 [현재까지 채워진 사양서]의
빈 칸(null)만 채우세요.

반드시 지켜야 할 규칙:
- [사내 참고 자료]에 실제로 나온 수치만 채우세요. 문서에 없는 수치를 지어내지 마세요.
- 문서에서 가져온 값은 status를 "VERIFIED"로, source.document에는 참고 자료의 출처(파일명)를 적으세요.
- 문서에도 없고 사용자도 말하지 않았지만 업계 통념상 합리적으로 추정 가능한 값이 있다면
  status를 "INFERRED"로 표시하고, 그렇지 않다면 반드시 null로 남기고 status를 "UNKNOWN"으로 두세요.
- 서로 다른 문서에서 값이 충돌하면 임의로 하나를 고르지 말고 null로 남기고
  notes에 "문서 간 값 충돌: ..." 형태로 기록하세요.
- 이미 값이 채워져 있는 필드는 절대 변경하지 마세요.
- 단위는 필드 이름에 명시된 단위(um, mm, mm/s, s 등)를 그대로 따르세요.

[사용자 요구사항]
{requirement_json}

[사내 참고 자료]
{context}

[현재까지 채워진 사양서 (이 구조를 유지한 채 빈 칸만 채워서 반환하세요)]
{partial_spec_json}
"""


def _prefill_from_requirement(requirement: RequirementSchema) -> SpecificationSchema:
    spec = SpecificationSchema()

    spec.inspection_target.material = requirement.target.material
    spec.inspection_target.product_type = requirement.target.product_type
    spec.inspection_target.width_mm = requirement.target.width_mm
    spec.inspection_target.length_mm = requirement.target.length_mm
    spec.inspection_target.substrate = requirement.target.substrate

    spec.inspection_items = list(requirement.inspection_items)
    spec.equipment.measurement_principle = requirement.measurement_principle

    if requirement.required_accuracy_um is not None:
        spec.measurement_performance.accuracy_um = SourcedNumber(
            value=requirement.required_accuracy_um, unit="um", operator="<=", status="USER_DEFINED"
        )
    if requirement.minimum_defect_size_um is not None:
        spec.defect_detection.minimum_defect_size_um = SourcedNumber(
            value=requirement.minimum_defect_size_um, unit="um", operator="<=", status="USER_DEFINED"
        )
    if requirement.required_resolution_um is not None:
        spec.measurement_performance.resolution_um = SourcedNumber(
            value=requirement.required_resolution_um, unit="um", operator="<=", status="USER_DEFINED"
        )

    return spec


def _collect_needs_confirmation(spec: SpecificationSchema) -> List[str]:
    needs_confirmation: List[str] = []
    for section_name in (
        "measurement_performance",
        "spatial_performance",
        "inspection_performance",
        "defect_detection",
    ):
        section = getattr(spec, section_name)
        for field_name in type(section).model_fields:
            value = getattr(section, field_name)
            if isinstance(value, SourcedNumber) and value.status in ("INFERRED", "UNKNOWN") and value.value is not None:
                needs_confirmation.append(f"{section_name}.{field_name}")
    return needs_confirmation


def generate_specification(
    requirement: RequirementSchema,
    retrieved_docs: List[Document],
    context_text: str,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> SpecificationSchema:
    partial_spec = _prefill_from_requirement(requirement)

    prompt = GENERATE_PROMPT.format(
        requirement_json=requirement.model_dump_json(indent=2),
        context=context_text or "(검색된 참고 자료 없음)",
        partial_spec_json=partial_spec.model_dump_json(indent=2),
    )

    llm_spec = ollama_client.parse_structured(prompt, SpecificationSchema, model=model, host=host)

    # 사용자가 명시한 값은 LLM 결과로 절대 덮어쓰지 않는다.
    merged = llm_spec.model_copy(deep=True)
    merged.inspection_target.material = partial_spec.inspection_target.material or merged.inspection_target.material
    merged.inspection_target.width_mm = (
        partial_spec.inspection_target.width_mm
        if partial_spec.inspection_target.width_mm is not None
        else merged.inspection_target.width_mm
    )
    merged.inspection_target.length_mm = (
        partial_spec.inspection_target.length_mm
        if partial_spec.inspection_target.length_mm is not None
        else merged.inspection_target.length_mm
    )
    merged.inspection_target.substrate = partial_spec.inspection_target.substrate or merged.inspection_target.substrate
    merged.inspection_items = partial_spec.inspection_items or merged.inspection_items

    if partial_spec.measurement_performance.accuracy_um is not None:
        merged.measurement_performance.accuracy_um = partial_spec.measurement_performance.accuracy_um
    if partial_spec.measurement_performance.resolution_um is not None:
        merged.measurement_performance.resolution_um = partial_spec.measurement_performance.resolution_um
    if partial_spec.defect_detection.minimum_defect_size_um is not None:
        merged.defect_detection.minimum_defect_size_um = partial_spec.defect_detection.minimum_defect_size_um

    merged.sources = sorted({doc.metadata.get("source", "") for doc in retrieved_docs if doc.metadata.get("source")})
    merged.needs_confirmation = _collect_needs_confirmation(merged)

    return merged
