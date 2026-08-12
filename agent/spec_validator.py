"""
SpecificationValidator — 완성된 Specification JSON을 자동 검증한다.
(기획안 13절: Schema / Unit / Range / Logical / Source / Requirement Validation)

여기서 "실패"는 파이프라인을 막지 않는다 — 검증 결과(issues)를 그대로
사용자에게 보여줘서 확인/수정하게 하는 것이 목적이다 (LLM이 조용히 틀린
값을 만들어내고 그게 그대로 PPTX에 박히는 상황을 막는 것이 핵심).
"""
from __future__ import annotations

from typing import List, Optional

from .schemas import RequirementSchema, SourcedNumber, SpecificationSchema, ValidationIssue, ValidationResult

_NUMERIC_SECTIONS = (
    "measurement_performance",
    "spatial_performance",
    "inspection_performance",
    "defect_detection",
)


def _iter_sourced_numbers(spec: SpecificationSchema):
    for section_name in _NUMERIC_SECTIONS:
        section = getattr(spec, section_name)
        for field_name in type(section).model_fields:
            value = getattr(section, field_name)
            if isinstance(value, SourcedNumber):
                yield f"{section_name}.{field_name}", value


def _validate_schema(spec: SpecificationSchema) -> List[ValidationIssue]:
    issues = []
    if not spec.inspection_target.material:
        issues.append(ValidationIssue(level="error", field="inspection_target.material", message="검사 대상(material)이 비어 있습니다."))
    if not spec.inspection_items:
        issues.append(ValidationIssue(level="error", field="inspection_items", message="검사 항목이 비어 있습니다."))
    if not spec.equipment.name:
        issues.append(ValidationIssue(level="warning", field="equipment.name", message="설비명이 채워지지 않았습니다."))
    return issues


def _validate_units(spec: SpecificationSchema) -> List[ValidationIssue]:
    issues = []
    for path, sourced in _iter_sourced_numbers(spec):
        if sourced.value is None:
            continue
        if not sourced.unit:
            issues.append(ValidationIssue(level="warning", field=path, message="값은 있는데 단위(unit)가 비어 있습니다."))
        expected_hint = path.rsplit(".", 1)[-1]
        for suffix, expected_unit in (("_um", "um"), ("_mm", "mm"), ("_mm_s", "mm/s"), ("_s", "s")):
            if expected_hint.endswith(suffix) and sourced.unit and sourced.unit.replace(" ", "") != expected_unit.replace(" ", ""):
                issues.append(
                    ValidationIssue(
                        level="warning",
                        field=path,
                        message=f"필드명은 '{expected_unit}' 단위를 암시하지만 실제 unit 값은 '{sourced.unit}' 입니다.",
                    )
                )
                break
    return issues


def _validate_range_and_logic(spec: SpecificationSchema) -> List[ValidationIssue]:
    issues = []
    mp = spec.measurement_performance
    sp = spec.spatial_performance

    def _val(sn: Optional[SourcedNumber]) -> Optional[float]:
        return sn.value if sn else None

    resolution = _val(mp.resolution_um)
    meas_range = _val(mp.measurement_range)
    if resolution is not None and meas_range is not None and resolution > meas_range:
        issues.append(
            ValidationIssue(
                level="error",
                field="measurement_performance.resolution_um",
                message=f"분해능({resolution}um)이 측정 범위({meas_range}um)보다 큽니다. 값을 다시 확인하세요.",
            )
        )

    accuracy = _val(mp.accuracy_um)
    repeatability = _val(mp.repeatability_um)
    if accuracy is not None and repeatability is not None and repeatability > accuracy:
        issues.append(
            ValidationIssue(
                level="warning",
                field="measurement_performance.repeatability_um",
                message=f"반복성({repeatability}um)이 정확도({accuracy}um)보다 나쁩니다(수치가 큽니다). 일반적이지 않은 조합이니 확인하세요.",
            )
        )

    z_res = _val(sp.z_resolution_um)
    if z_res is not None and accuracy is not None and z_res > accuracy:
        issues.append(
            ValidationIssue(
                level="warning",
                field="spatial_performance.z_resolution_um",
                message=f"Z 분해능({z_res}um)이 전체 정확도({accuracy}um)보다 큽니다. 물리적으로 이상한 조합일 수 있습니다.",
            )
        )

    for path, sourced in (
        ("measurement_performance.accuracy_um", mp.accuracy_um),
        ("measurement_performance.resolution_um", mp.resolution_um),
        ("defect_detection.minimum_defect_size_um", spec.defect_detection.minimum_defect_size_um),
    ):
        if sourced is not None and sourced.value is not None and sourced.value < 0:
            issues.append(ValidationIssue(level="error", field=path, message=f"값이 음수입니다: {sourced.value}"))

    return issues


def _validate_sources(spec: SpecificationSchema) -> List[ValidationIssue]:
    issues = []
    for path, sourced in _iter_sourced_numbers(spec):
        if sourced.value is None:
            continue
        if sourced.source_type is None:
            issues.append(ValidationIssue(level="warning", field=path, message="값은 있는데 source_type이 지정되지 않았습니다."))
        elif sourced.source_type == "document" and not sourced.source:
            issues.append(ValidationIssue(level="warning", field=path, message="source_type이 document인데 출처(source) 파일명이 비어 있습니다."))
        elif sourced.source_type in ("inferred", "default"):
            issues.append(ValidationIssue(level="info", field=path, message="이 값은 추정(inferred/default)된 값입니다. 생성 전 사용자 확인이 필요합니다."))
    return issues


def _validate_requirement_coverage(spec: SpecificationSchema, requirement: Optional[RequirementSchema]) -> List[ValidationIssue]:
    if requirement is None:
        return []
    issues = []
    items = set(requirement.inspection_items)
    if "thickness" in items and spec.measurement_performance.accuracy_um is None:
        issues.append(
            ValidationIssue(
                level="error",
                field="measurement_performance.accuracy_um",
                message="요청된 '두께' 검사 항목에 대한 정확도 정보가 채워지지 않았습니다.",
            )
        )
    if (items & {"surface_defect", "profile_3d"}) and spec.defect_detection.minimum_defect_size_um is None:
        issues.append(
            ValidationIssue(
                level="error",
                field="defect_detection.minimum_defect_size_um",
                message="요청된 결함 검사 항목에 대한 최소 검출 크기 정보가 채워지지 않았습니다.",
            )
        )
    for item in items:
        if item not in spec.inspection_items:
            issues.append(
                ValidationIssue(
                    level="warning",
                    field="inspection_items",
                    message=f"요청한 검사 항목 '{item}'이(가) 최종 사양서의 inspection_items에 포함되지 않았습니다.",
                )
            )
    return issues


def validate_specification(
    spec: SpecificationSchema,
    requirement: Optional[RequirementSchema] = None,
) -> ValidationResult:
    issues: List[ValidationIssue] = []
    issues += _validate_schema(spec)
    issues += _validate_units(spec)
    issues += _validate_range_and_logic(spec)
    issues += _validate_sources(spec)
    issues += _validate_requirement_coverage(spec, requirement)

    has_error = any(i.level == "error" for i in issues)
    return ValidationResult(is_valid=not has_error, issues=issues)
