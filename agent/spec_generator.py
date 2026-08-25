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

import logging
import os
from typing import List, Optional

from langchain_core.documents import Document

from . import candidate_matcher, ollama_client, units
from .schemas import (
    CandidateEquipment,
    RequirementSchema,
    SourcedNumber,
    SourceRef,
    SourcedRange,
    SpecificationSchema,
)
from .spec_retriever import format_context, source_label

logger = logging.getLogger(__name__)

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
    # spec.equipment.inline_offline/measurement_method/measurement_principle은 여기서
    # requirement 값으로 미리 채우지 않는다 — Equipment는 "실제로 선택된 장비"를
    # 서술하는 절이므로(manufacturer/model과 동일하게), 그 값은 아래
    # _apply_chosen_candidate()가 후보 문서에서 실제로 확인한 값으로만 채운다.
    # (과거에는 여기서 requirement.measurement_principle을 직접 대입했지만,
    # generate_specification()의 병합 단계에 실제로 반영하는 코드가 없어 죽은 코드였다
    # — 요구값과 실측값을 별도 필드로 분리하는 이 파일의 원칙에 맞춰 완전히 제거한다.)

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
        manufacturer, model = candidate_matcher.extract_manufacturer_model(doc.page_content)
        manufacturer = spec.equipment.manufacturer or manufacturer
        model = spec.equipment.model or model
        if not (manufacturer or model):
            continue
        spec.equipment.manufacturer = spec.equipment.manufacturer or manufacturer
        spec.equipment.model = spec.equipment.model or model
        spec.equipment.name = " ".join(x for x in (manufacturer, model) if x)
        if spec.equipment.name:
            spec.notes.append(f"설비명이 문서({source_label(doc)})에서 자동 추출되었습니다 — 정확한지 확인하세요.")
            return


def _apply_chosen_candidate(spec: SpecificationSchema, chosen: Optional[CandidateEquipment]) -> None:
    """
    candidate_matcher.select_best_candidate()가 고른 "가장 나은 후보"의 값을 최종
    사양서에 반영한다. LLM이 measurement_range_full/equipment_accuracy_um/
    equipment_minimum_defect_size_um을 스스로 채웠더라도, 실제 후보 문서 원문에서
    결정론적으로 추출/판정한 이 값이 항상 우선한다 — hard requirement(측정 범위
    포함 여부/정확도/최소 검출 결함 크기 충족 여부) PASS/FAIL을 LLM 판단에 맡기지
    않기 위함이다.

    measurement_range_full/equipment_accuracy_um/equipment_minimum_defect_size_um은
    match.found_value가 있으면
    PASS/FAIL과 무관하게 항상 채운다 — status="VERIFIED"는 "이 값이 실제 문서에서
    확인됐다"는 뜻이지 "요구사항을 충족한다"는 뜻이 아니며(그 판정은 별도로
    build_hard_requirement_report가 담당), 이렇게 해야 FAIL인 경우에도 Hard
    Requirement Report가 실제 근거 값으로 이유를 보여줄 수 있다.

    반면 레거시 단일값 필드(measurement_range)는 match.result == "PASS"일 때만
    동기화한다 — 이 필드는 spec_validator._validate_sources()/needs_confirmation이
    직접 검사하는 필드라서, FAIL인 값까지 VERIFIED로 써 넣으면 "요구사항을
    충족하는 값처럼 보이는" 오해를 줄 수 있기 때문이다.
    """
    if chosen is None:
        return

    if not spec.equipment.name and (chosen.manufacturer or chosen.model):
        spec.equipment.manufacturer = spec.equipment.manufacturer or chosen.manufacturer
        spec.equipment.model = spec.equipment.model or chosen.model
        spec.equipment.name = " ".join(x for x in (chosen.manufacturer, chosen.model) if x)
        if spec.equipment.name:
            spec.notes.append(f"설비명이 후보 문서({chosen.source_document})에서 자동 추출되었습니다 — 정확한지 확인하세요.")

    for match in chosen.matches:
        if match.source is None or (match.found_value is None and match.found_text is None):
            continue
        if match.field_key == "inline_offline" and match.found_text:
            # `or spec.equipment.inline_offline`로 기존 값을 우선하면 안 된다 — LLM이
            # narrowed context를 보고 이 필드를 먼저 자유 문자열로 채워 넣을 수 있고
            # (예: 원문 그대로 "Machine Vision"), 그 비canonical 값이 여기서 덮어써지지
            # 않고 남아 있으면 build_hard_requirement_report가 요구값의 canonical
            # 라벨(예: "Vision")과 문자열이 달라 실제로는 만족하는 조건을 FAIL로
            # 잘못 판정한다(실사용자 보고 버그: SPEC-006.md "Machine Vision" vs 요구
            # "Vision" → 의미상 동일한데 FAIL). measurement_range_full/equipment_accuracy_um과
            # 동일하게, 후보 문서에서 결정론적으로 추출한 canonical 값이 항상 우선해야 한다.
            spec.equipment.inline_offline = match.found_text
        elif match.field_key == "measurement_method" and match.found_text:
            spec.equipment.measurement_method = match.found_text
        elif match.field_key == "measurement_principle" and match.found_text:
            spec.equipment.measurement_principle = match.found_text
        elif match.field_key == "measurement_range" and match.found_min is not None:
            spec.measurement_performance.measurement_range_full = SourcedRange(
                min=match.found_min,
                max=match.found_value,
                unit=match.found_unit,
                status="VERIFIED",
                source=match.source.model_copy(),
            )
            if match.result == "PASS":
                # 레거시 단일값 필드(measurement_range)도 동일 근거로 동기화한다 — 이
                # 필드는 LLM이 "범위"를 억지로 단일 값으로 채우려다(예: 하한 "0") 원문과
                # 정확히 일치하는 토큰을 찾지 못해 _verify_sourced_numbers가 INFERRED로
                # 강등시키는 경우가 실제로 관찰되었다. Hard Requirement가 이미 PASS로
                # 확정한 값이 있으므로 그 값으로 legacy 필드를 덮어써 "PASS인데
                # INFERRED"라는 모순을 없앤다(요청서 5절).
                spec.measurement_performance.measurement_range = SourcedNumber(
                    value=match.found_value,
                    unit=match.found_unit,
                    status="VERIFIED",
                    source=match.source.model_copy(),
                )
        elif match.field_key == "accuracy":
            spec.measurement_performance.equipment_accuracy_um = SourcedNumber(
                value=match.found_value,
                unit=match.found_unit,
                status="VERIFIED",
                source=match.source.model_copy(),
            )
        elif match.field_key == "minimum_defect_size":
            spec.defect_detection.equipment_minimum_defect_size_um = SourcedNumber(
                value=match.found_value,
                unit=match.found_unit,
                status="VERIFIED",
                source=match.source.model_copy(),
            )


def _collect_verified_source_documents(spec: SpecificationSchema) -> List[str]:
    """
    모든 확인된(VERIFIED) SourcedNumber/SourcedRange의 근거 문서명을 모은다 — 검색된
    문서 전체(sources)가 아니라, 최종 사양의 각 필드값을 실제로 뒷받침하는 문서만
    primary_sources에 담아 UI에 우선 노출하기 위함이다.
    """
    documents = set()
    for section_name in (
        "measurement_performance",
        "spatial_performance",
        "inspection_performance",
        "defect_detection",
    ):
        section = getattr(spec, section_name)
        for field_name in type(section).model_fields:
            value = getattr(section, field_name)
            if (
                isinstance(value, (SourcedNumber, SourcedRange))
                and value.status == "VERIFIED"
                and value.source
                and value.source.document
            ):
                documents.add(value.source.document)
    return sorted(documents)


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


_MAX_CHUNK_CHARS_FOR_PROMPT = 2000


def _narrow_context_docs_for_prompt(
    retrieved_docs: List[Document], chosen: Optional[CandidateEquipment]
) -> List[Document]:
    """
    LLM 프롬프트에 실어 보낼 chunk를 "선택된 후보 문서"만으로 좁힌다.

    배경: candidate_matcher.build_candidates()/select_best_candidate()가 이미
    retrieved_docs 전체(실측: 흔한 다중 검사항목 질의에서 10개 사양서 중
    25개 chunk, corpus 전체의 약 30%)를 근거로 hard requirement PASS/FAIL을
    판정하고 "이 후보 하나"를 고른다. 그런데 기존 코드는 그 판정과 무관하게
    retrieved_docs 전체를 LLM 프롬프트에 그대로 실어 보내고 있었다 — LLM이
    최종적으로 사양서를 채워야 할 장비는 어차피 이 chosen 후보 하나뿐인데도,
    관련 없는 다른 9개 문서의 chunk까지 매번 컨텍스트로 넘겨 prompt 크기와
    Ollama 응답 시간을 불필요하게 늘리고 있었다(실측: 25개 chunk, 프롬프트
    약 11,900자). 후보 선정 로직(build_candidates/select_best_candidate) 자체는
    그대로 retrieved_docs 전체를 계속 보므로, RAG 검색/후보 매칭 정확도에는
    영향이 없다 — 오직 "LLM에게 무엇을 보여줄지"만 좁힌다.

    chosen이 없으면(검색 결과 0건 등) 기존과 동일하게 retrieved_docs 전체를
    그대로 쓴다(회귀 방지).
    """
    if chosen is None:
        return retrieved_docs
    narrowed = [doc for doc in retrieved_docs if source_label(doc) == chosen.source_document]
    return narrowed or retrieved_docs


def _truncate_docs_for_prompt(docs: List[Document], limit: int = _MAX_CHUNK_CHARS_FOR_PROMPT) -> List[Document]:
    """비정상적으로 긴 chunk(예: 표 하나가 통째로 한 chunk인 경우) 하나가 prompt
    크기를 지배하지 않도록 chunk 단위로 방어적으로 자른다. sample_specs처럼
    짧은 chunk만 있는 corpus에서는 사실상 아무 효과가 없다(안전망일 뿐, 정상
    케이스는 그대로 통과— 아래에서 길이가 그대로면 원본 Document를 재사용한다)."""
    result = []
    for doc in docs:
        if len(doc.page_content) <= limit:
            result.append(doc)
            continue
        truncated_text = doc.page_content[:limit] + "\n...(이하 생략 — 원문이 너무 길어 일부만 표시됨)"
        result.append(Document(page_content=truncated_text, metadata=doc.metadata))
    return result


def generate_specification(
    requirement: RequirementSchema,
    retrieved_docs: List[Document],
    context_text: str,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> SpecificationSchema:
    partial_spec = _prefill_from_requirement(requirement)

    # Hard Requirement 판정(및 최종적으로 채택될 후보)을 LLM 호출 "전에" 먼저
    # 계산한다 — 이 결과로 프롬프트에 실을 chunk를 좁히기 위함이다. 판정 로직
    # 자체는 기존과 동일하게 retrieved_docs 전체를 본다(순서만 앞당김, 결과는
    # 동일 — _apply_chosen_candidate가 나중에 이 값을 그대로 재사용한다).
    candidates = candidate_matcher.build_candidates(requirement, retrieved_docs)
    chosen_candidate = candidate_matcher.select_best_candidate(candidates)

    llm_context_docs = _narrow_context_docs_for_prompt(retrieved_docs, chosen_candidate)
    llm_context_docs = _truncate_docs_for_prompt(llm_context_docs)
    logger.info(
        "[LLM DEBUG] context 좁힘: retrieved_chunks=%s -> llm_context_chunks=%s (chosen_candidate=%s)",
        len(retrieved_docs), len(llm_context_docs),
        chosen_candidate.source_document if chosen_candidate else None,
    )

    # context_text(호출부가 넘긴, retrieved_docs 전체 기준 문자열) 대신 위에서
    # 좁힌/자른 llm_context_docs로 항상 다시 만든다 — 시그니처는 하위호환을 위해
    # context_text를 그대로 받지만, 실제 프롬프트에는 쓰지 않는다.
    narrowed_context_text = format_context(llm_context_docs)

    prompt = GENERATE_PROMPT.format(
        requirement_json=requirement.model_dump_json(indent=2),
        context=narrowed_context_text or "(검색된 참고 자료 없음)",
        partial_spec_json=partial_spec.model_dump_json(indent=2),
    )

    llm_spec = ollama_client.parse_structured(
        prompt, SpecificationSchema, model=model, host=host, context_chunk_count=len(llm_context_docs)
    )

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
    # candidates/chosen_candidate는 위에서(LLM 호출 전) 이미 계산해뒀다 — 그때와
    # 지금 사이에 retrieved_docs/requirement가 바뀌지 않으므로 재계산하지 않는다.
    _apply_chosen_candidate(merged, chosen_candidate)

    _fallback_equipment_identity(merged, retrieved_docs)

    merged.sources = sorted({source_label(doc) for doc in retrieved_docs if doc.metadata.get("source")})
    merged.primary_sources = _collect_verified_source_documents(merged)
    merged.needs_confirmation = _collect_needs_confirmation(merged)

    return merged
