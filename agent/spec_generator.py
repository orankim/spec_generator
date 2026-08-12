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
import re
from typing import List, Optional

from langchain_core.documents import Document

from . import ollama_client, units
from .schemas import RequirementSchema, SourceRef, SourcedNumber, SpecificationSchema
from .spec_retriever import source_label

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


_IDENTITY_PATTERNS = {
    "manufacturer": re.compile(r"(?:Manufacturer|제조사)\s*[:：]\s*(.+)", re.IGNORECASE),
    "model": re.compile(r"(?:^|\n)[-*]?\s*Model\s*[:：]\s*(.+)", re.IGNORECASE),
}


def _find_matching_doc(sourced: SourcedNumber, retrieved_docs: List[Document]) -> Optional[Document]:
    """sourced.value/unit이 실제로 어느 검색된 문서 원문에 등장하는지 찾는다.
    canonical 단위로 변환 후 비교하므로 nm/um/mm처럼 표기가 달라도 매치된다."""
    if sourced.value is None or not sourced.unit:
        return None
    try:
        target_value, target_unit = units.to_canonical(sourced.value, sourced.unit)
    except units.UnitError:
        return None
    for doc in retrieved_docs:
        for found_value, found_unit in units.iter_value_units(doc.page_content):
            try:
                found_canonical, found_canonical_unit = units.to_canonical(found_value, found_unit)
            except units.UnitError:
                continue
            if found_canonical_unit == target_unit and abs(found_canonical - target_value) < 1e-6:
                return doc
    return None


def _verify_sourced_numbers(spec: SpecificationSchema, retrieved_docs: List[Document]) -> None:
    """
    LLM이 status="VERIFIED"로 표시한 모든 SourcedNumber를 실제 검색된 문서 원문과
    코드로 대조한다. 근거 문서에 실제로 그 수치가 있으면 source.document/chunk_id를
    보강(비어 있던 경우)하고, 어떤 검색 문서에서도 확인되지 않으면 VERIFIED를
    INFERRED로 자동 강등한다 — 소형 LLM이 "그럴듯해 보여서" VERIFIED를 붙이고
    source는 비워두는 경우를 코드 레벨에서 막기 위함이다. 강등된 값은
    _collect_needs_confirmation()에 의해 자동으로 needs_confirmation에 잡힌다.
    """
    for section_name in (
        "measurement_performance",
        "spatial_performance",
        "inspection_performance",
        "defect_detection",
    ):
        section = getattr(spec, section_name)
        for field_name in type(section).model_fields:
            sourced = getattr(section, field_name)
            if not isinstance(sourced, SourcedNumber):
                continue
            if sourced.status != "VERIFIED" or sourced.value is None:
                continue

            match_doc = _find_matching_doc(sourced, retrieved_docs)
            if match_doc is not None:
                if sourced.source is None:
                    sourced.source = SourceRef()
                if not sourced.source.document:
                    sourced.source.document = source_label(match_doc)
                if sourced.source.chunk_id is None:
                    sourced.source.chunk_id = match_doc.metadata.get("chunk_id")
                if not sourced.source.section:
                    sourced.source.section = match_doc.metadata.get("item") or match_doc.metadata.get("category")
            else:
                sourced.status = "INFERRED"
                note = "검색된 참고 문서에서 이 값을 다시 확인하지 못해 VERIFIED에서 INFERRED로 자동 하향 조정되었습니다."
                sourced.reasoning = f"{sourced.reasoning} {note}" if sourced.reasoning else note


def _confirmed_source_documents(spec: SpecificationSchema) -> set:
    """_verify_sourced_numbers()가 실제로 값을 확인해 source.document를 채운
    문서 파일명 집합. equipment 신원 추출 시 아무 검색 결과나 쓰지 않고 이미
    신뢰가 검증된 문서를 우선하기 위해 쓰인다."""
    confirmed = set()
    for section_name in (
        "measurement_performance",
        "spatial_performance",
        "inspection_performance",
        "defect_detection",
    ):
        section = getattr(spec, section_name)
        for field_name in type(section).model_fields:
            sourced = getattr(section, field_name)
            if isinstance(sourced, SourcedNumber) and sourced.status == "VERIFIED" and sourced.source and sourced.source.document:
                confirmed.add(sourced.source.document)
    return confirmed


def _fallback_equipment_identity(spec: SpecificationSchema, retrieved_docs: List[Document]) -> None:
    """
    LLM이 equipment.name(및 manufacturer/model)을 채우지 못했을 때, 검색된 문서의
    "Manufacturer:"/"Model:" 같은 명시적 라인에서 정규식으로 결정론적으로 보강한다.
    Equipment.name은 SourcedNumber가 아니라 status/source 필드가 없으므로, 여기서
    채운 값은 notes에 근거 문서명을 남겨 사용자가 확인할 수 있게 한다(거짓 확신을
    주지 않기 위함 — LLM 없이 regex만으로 채웠다는 사실을 숨기지 않는다).

    검색된 문서 중 어느 것이든 첫 매치를 쓰지 않고, _verify_sourced_numbers()가 이미
    실제 수치를 확인해준 문서(=이 사양서의 다른 값들의 실제 근거)를 최우선으로 본다 —
    그래야 정확도/측정범위가 검증된 문서와 "다른" 장비의 제조사/모델을 잘못 붙이지 않는다.
    """
    if spec.equipment.name:
        return
    confirmed = _confirmed_source_documents(spec)
    ordered_docs = sorted(retrieved_docs, key=lambda d: 0 if source_label(d) in confirmed else 1)
    for doc in ordered_docs:
        text = doc.page_content
        manufacturer = spec.equipment.manufacturer
        model = spec.equipment.model
        if not manufacturer:
            m = _IDENTITY_PATTERNS["manufacturer"].search(text)
            if m:
                manufacturer = m.group(1).strip()
        if not model:
            m = _IDENTITY_PATTERNS["model"].search(text)
            if m:
                model = m.group(1).strip()
        if not (manufacturer or model):
            continue
        spec.equipment.manufacturer = spec.equipment.manufacturer or manufacturer
        spec.equipment.model = spec.equipment.model or model
        spec.equipment.name = " ".join(x for x in (manufacturer, model) if x)
        if spec.equipment.name:
            spec.notes.append(f"설비명이 문서({source_label(doc)})에서 자동 추출되었습니다 — 정확한지 확인하세요.")
            return


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

    _verify_sourced_numbers(merged, retrieved_docs)
    _fallback_equipment_identity(merged, retrieved_docs)

    merged.sources = sorted({source_label(doc) for doc in retrieved_docs if doc.metadata.get("source")})
    merged.needs_confirmation = _collect_needs_confirmation(merged)

    return merged
