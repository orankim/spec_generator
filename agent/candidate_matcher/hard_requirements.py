"""
RequirementSchema -> (value, unit[, operator]) 정규화 계층 — 사용자가 실제로
요구한 hard requirement 필드만 뽑아 core.py의 build_candidates()가
agent.units.evaluate_hard_requirements()로 비교할 수 있는 형태로 만든다.

_source_ref()는 CandidateFieldMatch.source(어느 chunk/문서에서 이 값을 찾았는지)를
만드는 공용 헬퍼로, 추출(extraction.py)/검사항목(inspection_items.py)/랭킹
(ranking.py) 어디에도 속하지 않는 순수 변환 함수라 여기 둔다.
"""
from __future__ import annotations

from typing import Optional, Tuple

from langchain_core.documents import Document

from ..schemas import RequirementSchema, SourceRef
from ..spec_retriever import source_label


def _source_ref(doc: Document) -> SourceRef:
    return SourceRef(
        document=source_label(doc),
        section=doc.metadata.get("item") or doc.metadata.get("category"),
        chunk_id=doc.metadata.get("chunk_id"),
        source_type=doc.metadata.get("source_type"),
    )


def _required_range(requirement: RequirementSchema) -> Optional[Tuple[float, float, str]]:
    r = requirement.measurement_range
    if r is None or r.min is None or r.max is None:
        return None
    return r.min, r.max, r.unit or "um"


def _required_accuracy(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    if requirement.accuracy is not None and requirement.accuracy.value is not None:
        return requirement.accuracy.value, requirement.accuracy.unit or "um", requirement.accuracy.operator or "<="
    if requirement.required_accuracy_um is not None:
        return requirement.required_accuracy_um, "um", "<="
    return None


def _required_defect_size(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    """사용자가 요구한 최소 검출 결함 크기 — 장비가 "이 크기 이하의 결함까지" 검출할 수
    있어야 한다는 뜻이므로 accuracy와 동일하게 operator는 항상 "<="다(작을수록 더
    미세한 결함까지 잡아낸다는 의미이므로 후보의 실측값이 요구값보다 작거나 같아야 PASS)."""
    if requirement.minimum_defect_size is not None and requirement.minimum_defect_size.value is not None:
        return (
            requirement.minimum_defect_size.value,
            requirement.minimum_defect_size.unit or "um",
            requirement.minimum_defect_size.operator or "<=",
        )
    if requirement.minimum_defect_size_um is not None:
        return requirement.minimum_defect_size_um, "um", "<="
    return None


def _required_width(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    """요구 폭은 "이 폭 이상을 처리할 수 있어야 한다"는 뜻이므로 operator는 항상
    ">="다 — RequirementSchema.target.width_mm에는 operator 정보가 없는 단일
    float 필드라서(사용자가 폭을 요구할 때 이하/미만을 의도하는 경우가 없는
    도메인이므로) 여기서 고정한다."""
    if requirement.target.width_mm is None:
        return None
    return requirement.target.width_mm, "mm", ">="


def _required_speed(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    if requirement.measurement_speed is not None and requirement.measurement_speed.value is not None:
        return (
            requirement.measurement_speed.value,
            requirement.measurement_speed.unit or "mm/s",
            requirement.measurement_speed.operator or ">=",
        )
    return None
