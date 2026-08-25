"""
SpecificationValidator — 완성된 Specification JSON을 자동 검증한다.
(기획안 13절: Schema / Unit / Range / Logical / Source / Requirement Validation)

여기서 "실패"는 파이프라인을 막지 않는다 — 검증 결과(issues)를 그대로
사용자에게 보여줘서 확인/수정하게 하는 것이 목적이다 (LLM이 조용히 틀린
값을 만들어내고 그게 그대로 PPTX에 박히는 상황을 막는 것이 핵심).
"""
from __future__ import annotations

from typing import List, Optional

from . import categorical_match, units
from .schemas import (
    CandidateEquipment,
    ComplianceRecord,
    Operator,
    RequirementSchema,
    SourcedNumber,
    SpecificationSchema,
    ValidationIssue,
    ValidationResult,
)

_NUMERIC_SECTIONS = (
    "inspection_target",
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
        # 긴 접미사(_mm_s)부터 검사해야 "line_speed_mm_s"가 짧은 접미사(_s)에도
        # 걸려서 "mm/s인데 s를 기대한다"는 거짓 경고를 내지 않는다 — 접미사 하나가
        # 매치되면 그걸로 확정하고 더 짧은 접미사는 검사하지 않는다.
        for suffix, expected_unit in sorted(
            (("_um", "um"), ("_mm", "mm"), ("_mm_s", "mm/s"), ("_s", "s")), key=lambda p: -len(p[0])
        ):
            if expected_hint.endswith(suffix):
                if sourced.unit and sourced.unit.replace(" ", "") != expected_unit.replace(" ", ""):
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
        if sourced.status == "UNKNOWN":
            issues.append(ValidationIssue(level="warning", field=path, message="값은 있는데 status가 UNKNOWN입니다(근거 불명확)."))
        elif sourced.status == "VERIFIED" and not (sourced.source and sourced.source.document):
            # SpecGenerator._verify_sourced_numbers()가 VERIFIED로 표시된 값을 검색된
            # 문서와 대조해 확인 못하면 INFERRED로 자동 강등하므로, 이 경로가 살아있다면
            # 생성 파이프라인을 거치지 않고(API로 직접) VERIFIED를 주장하는 것이다 —
            # 경고가 아니라 오류로 막는다(요청서: source 없는 VERIFIED를 더 이상 허용하지 않음).
            issues.append(ValidationIssue(level="error", field=path, message="status가 VERIFIED인데 출처(source.document)가 비어 있습니다."))
        elif sourced.status == "INFERRED":
            issues.append(ValidationIssue(level="info", field=path, message="이 값은 추정(INFERRED)된 값입니다. 생성 전 사용자 확인이 필요합니다."))
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


def _compare(value: float, req_value: float, operator: Operator) -> bool:
    if operator == "<=":
        return value <= req_value
    if operator == ">=":
        return value >= req_value
    if operator == "<":
        return value < req_value
    if operator == ">":
        return value > req_value
    return value == req_value


# Requirement 필드 -> (Specification의 SourcedNumber, 표시 라벨) 매핑.
# "13. Requirement Compliance" 섹션은 이 표에 있는 항목만 비교한다 —
# 비교 기준이 없는 필드까지 "UNKNOWN"으로 채워 표를 불필요하게 늘리지 않는다.
_COMPLIANCE_FIELDS = [
    ("required_accuracy_um", "measurement_performance", "accuracy_um", "Accuracy"),
    ("required_resolution_um", "measurement_performance", "resolution_um", "Resolution"),
    ("minimum_defect_size_um", "defect_detection", "minimum_defect_size_um", "Minimum Defect Size"),
]


def build_compliance_report(
    spec: SpecificationSchema,
    requirement: Optional[RequirementSchema],
) -> List[ComplianceRecord]:
    """
    Requirement(사용자가 원하는 조건)와 Specification(장비의 실제/제안 사양)을
    항목별로 비교한다 (요청서 14/18절). 이 결과는 스키마에 저장하지 않고
    렌더링 시점에 계산되는 파생 정보다 — Requirement와 Specification 자체는
    항상 분리된 채로 유지된다.
    """
    if requirement is None:
        return []

    records: List[ComplianceRecord] = []
    for req_field, section_name, spec_field, label in _COMPLIANCE_FIELDS:
        req_value = getattr(requirement, req_field, None)
        section = getattr(spec, section_name)
        sourced: Optional[SourcedNumber] = getattr(section, spec_field, None)
        spec_value = sourced.value if sourced else None
        unit = sourced.unit if sourced and sourced.unit else "um"
        operator: Operator = (sourced.operator if sourced and sourced.operator else "<=")

        if req_value is None and spec_value is None:
            continue  # 요구사항도 사양값도 없으면 비교 자체가 무의미하므로 표에 넣지 않는다

        if spec_value is None:
            result, reason = "UNKNOWN", "사양값이 채워지지 않았습니다."
        elif req_value is None:
            result, reason = "UNKNOWN", "이 항목에 대한 요구사항이 지정되지 않았습니다."
        else:
            ok = _compare(spec_value, req_value, operator)
            result = "PASS" if ok else "FAIL"
            reason = f"{spec_value}{unit} {operator} {req_value}{unit}"

        records.append(
            ComplianceRecord(
                item=label,
                unit=unit,
                requirement=req_value,
                specification=spec_value,
                operator=operator,
                result=result,
                reason=reason,
                source=sourced.source if sourced else None,
            )
        )
    return records


# ==========================================
# Hard Requirement 검증 — 요구 범위/정확도를 장비의 "실측값"(candidate_matcher가
# 후보 문서에서 직접 추출한 값)과 비교한다.
#
# build_compliance_report()와 의도적으로 분리한다: 그쪽은 measurement_performance.
# accuracy_um(=사용자 요구값을 보호하기 위해 SpecGenerator._prefill_from_requirement가
# 그대로 고정해 넣는 필드, 요청서: 요구값/장비값 혼동 금지)과 requirement를 비교하므로
# 요구값끼리 비교하는 셈이라 hard requirement 판정에는 쓸 수 없다. 이 함수는 대신
# equipment_accuracy_um/measurement_range_full(candidate_matcher가 채우는, 장비의
# 실제 확인된 값)을 사용해 진짜 "요구 vs 실측" PASS/FAIL을 코드로 판정한다.
# ==========================================
def _range_hard_requirement_record(spec: SpecificationSchema, requirement: RequirementSchema) -> Optional[ComplianceRecord]:
    req_range = requirement.measurement_range
    if req_range is None or req_range.min is None or req_range.max is None:
        return None
    req_unit = req_range.unit or "um"
    required = (req_range.min, req_range.max, req_unit)

    range_full = spec.measurement_performance.measurement_range_full
    if range_full is None or range_full.min is None or range_full.max is None:
        return ComplianceRecord(
            item="Measurement Range", unit=req_unit, requirement=req_range.max, specification=None,
            operator="<=", result="UNKNOWN", reason="장비의 측정 범위를 확인하지 못했습니다.", hard=True,
        )

    candidate = (range_full.min, range_full.max, range_full.unit or req_unit)
    ok = units.range_covers(candidate, required)
    result = "PASS" if ok else "FAIL"
    reason = (
        f"요구 범위 {required[0]:g}~{required[1]:g}{required[2]} / "
        f"장비 범위 {candidate[0]:g}~{candidate[1]:g}{candidate[2]} → {result}"
    )
    return ComplianceRecord(
        item="Measurement Range", unit=req_unit, requirement=req_range.max, specification=range_full.max,
        operator="<=", result=result, reason=reason, source=range_full.source, hard=True,
    )


def _accuracy_hard_requirement_record(spec: SpecificationSchema, requirement: RequirementSchema) -> Optional[ComplianceRecord]:
    if requirement.accuracy is not None and requirement.accuracy.value is not None:
        req_value = requirement.accuracy.value
        req_unit = requirement.accuracy.unit or "um"
        operator: Operator = requirement.accuracy.operator or "<="
    elif requirement.required_accuracy_um is not None:
        req_value, req_unit, operator = requirement.required_accuracy_um, "um", "<="
    else:
        return None

    equipment_accuracy = spec.measurement_performance.equipment_accuracy_um
    if equipment_accuracy is None or equipment_accuracy.value is None:
        return ComplianceRecord(
            item="Accuracy", unit=req_unit, requirement=req_value, specification=None,
            operator=operator, result="UNKNOWN", reason="장비의 실제 정확도를 확인하지 못했습니다.", hard=True,
        )

    spec_value = equipment_accuracy.value
    spec_unit = equipment_accuracy.unit or req_unit
    ok = units.compare_values(spec_value, spec_unit, req_value, req_unit, operator)
    result = "PASS" if ok else "FAIL"
    reason = f"요구 정확도 {operator} {req_value:g}{req_unit} / 장비 정확도 {spec_value:g}{spec_unit} → {result}"
    return ComplianceRecord(
        item="Accuracy", unit=req_unit, requirement=req_value, specification=spec_value,
        operator=operator, result=result, reason=reason, source=equipment_accuracy.source, hard=True,
    )


def _defect_size_hard_requirement_record(spec: SpecificationSchema, requirement: RequirementSchema) -> Optional[ComplianceRecord]:
    if requirement.minimum_defect_size is not None and requirement.minimum_defect_size.value is not None:
        req_value = requirement.minimum_defect_size.value
        req_unit = requirement.minimum_defect_size.unit or "um"
        operator: Operator = requirement.minimum_defect_size.operator or "<="
    elif requirement.minimum_defect_size_um is not None:
        req_value, req_unit, operator = requirement.minimum_defect_size_um, "um", "<="
    else:
        return None

    equipment_defect_size = spec.defect_detection.equipment_minimum_defect_size_um
    if equipment_defect_size is None or equipment_defect_size.value is None:
        return ComplianceRecord(
            item="Minimum Defect Size", unit=req_unit, requirement=req_value, specification=None,
            operator=operator, result="UNKNOWN", reason="장비의 실제 최소 검출 결함 크기를 확인하지 못했습니다.", hard=True,
        )

    spec_value = equipment_defect_size.value
    spec_unit = equipment_defect_size.unit or req_unit
    ok = units.compare_values(spec_value, spec_unit, req_value, req_unit, operator)
    result = "PASS" if ok else "FAIL"
    reason = f"요구 최소 검출 결함 크기 {operator} {req_value:g}{req_unit} / 장비 최소 검출 결함 크기 {spec_value:g}{spec_unit} → {result}"
    return ComplianceRecord(
        item="Minimum Defect Size", unit=req_unit, requirement=req_value, specification=spec_value,
        operator=operator, result=result, reason=reason, source=equipment_defect_size.source, hard=True,
    )


def _width_hard_requirement_record(spec: SpecificationSchema, requirement: RequirementSchema) -> Optional[ComplianceRecord]:
    """요구 폭은 "이 폭 이상을 처리할 수 있어야 한다"는 뜻이므로 operator는 항상
    ">="다(agent.candidate_matcher._required_width와 동일한 원칙)."""
    if requirement.target.width_mm is None:
        return None
    req_value, req_unit, operator = requirement.target.width_mm, "mm", ">="

    equipment_width = spec.inspection_target.equipment_max_width_mm
    if equipment_width is None or equipment_width.value is None:
        return ComplianceRecord(
            item="Width", unit=req_unit, requirement=req_value, specification=None,
            operator=operator, result="UNKNOWN", reason="장비가 대응 가능한 최대 폭을 확인하지 못했습니다.", hard=True,
        )

    spec_value = equipment_width.value
    spec_unit = equipment_width.unit or req_unit
    ok = units.compare_values(spec_value, spec_unit, req_value, req_unit, operator)
    result = "PASS" if ok else "FAIL"
    reason = f"요구 폭 {operator} {req_value:g}{req_unit} / 장비 최대 폭 {spec_value:g}{spec_unit} → {result}"
    return ComplianceRecord(
        item="Width", unit=req_unit, requirement=req_value, specification=spec_value,
        operator=operator, result=result, reason=reason, source=equipment_width.source, hard=True,
    )


def _speed_hard_requirement_record(spec: SpecificationSchema, requirement: RequirementSchema) -> Optional[ComplianceRecord]:
    if requirement.measurement_speed is None or requirement.measurement_speed.value is None:
        return None
    req_value = requirement.measurement_speed.value
    req_unit = requirement.measurement_speed.unit or "mm/s"
    operator: Operator = requirement.measurement_speed.operator or ">="

    equipment_speed = spec.inspection_performance.line_speed_mm_s
    if equipment_speed is None or equipment_speed.value is None:
        return ComplianceRecord(
            item="Speed", unit=req_unit, requirement=req_value, specification=None,
            operator=operator, result="UNKNOWN", reason="장비의 실제 검사 속도를 확인하지 못했습니다.", hard=True,
        )

    spec_value = equipment_speed.value
    spec_unit = equipment_speed.unit or req_unit
    ok = units.compare_values(spec_value, spec_unit, req_value, req_unit, operator)
    result = "PASS" if ok else "FAIL"
    reason = f"요구 속도 {operator} {req_value:g}{req_unit} / 장비 속도 {spec_value:g}{spec_unit} → {result}"
    return ComplianceRecord(
        item="Speed", unit=req_unit, requirement=req_value, specification=spec_value,
        operator=operator, result=result, reason=reason, source=equipment_speed.source, hard=True,
    )


_CATEGORICAL_LABELS = {
    "inline": "Inline",
    "offline": "Offline",
    "non_contact": "Non-contact",
    "contact": "Contact",
}


def _categorical_hard_requirement_record(
    item: str,
    required: Optional[str],
    confirmed: Optional[str],
) -> Optional[ComplianceRecord]:
    """
    Inspection Mode(Inline/Offline)/Measurement Method(Contact/Non-contact)/
    Measurement Principle처럼 숫자가 아니라 범주형 값인 hard requirement를
    비교한다. required가 None이면(사용자가 그 조건을 요구하지 않았으면) 애초에
    평가하지 않는다 — Range/Accuracy와 동일한 원칙.
    """
    if required is None:
        return None
    required_label = _CATEGORICAL_LABELS.get(required, required)
    if confirmed is None:
        return ComplianceRecord(
            item=item, result="UNKNOWN",
            reason=f"요구 {item} {required_label} / 장비의 {item}을(를) 확인하지 못했습니다.",
            hard=True,
        )
    confirmed_label = _CATEGORICAL_LABELS.get(confirmed, confirmed)
    result = "PASS" if confirmed == required else "FAIL"
    reason = f"요구 {item} {required_label} / 장비 {item} {confirmed_label} → {result}"
    return ComplianceRecord(item=item, result=result, reason=reason, hard=True)


def build_hard_requirement_report(
    spec: SpecificationSchema,
    requirement: Optional[RequirementSchema],
) -> List[ComplianceRecord]:
    """
    측정 범위/정확도/최소 검출 결함 크기/검사 모드/측정 방식/측정 원리 hard requirement를
    요구값 대 "장비 실측값"으로 PASS/FAIL 판정한다(LLM이 아니라 agent.units/agent.
    categorical_match의 순수 함수로 판정 — candidate_matcher.build_candidates()가
    이미 채운 measurement_range_full/equipment_accuracy_um/
    equipment_minimum_defect_size_um/equipment.inline_offline/
    measurement_method/measurement_principle을 그대로 재사용하므로 비교 로직을
    중복 구현하지 않는다).
    """
    if requirement is None:
        return []
    records: List[ComplianceRecord] = []
    range_record = _range_hard_requirement_record(spec, requirement)
    if range_record is not None:
        records.append(range_record)
    accuracy_record = _accuracy_hard_requirement_record(spec, requirement)
    if accuracy_record is not None:
        records.append(accuracy_record)
    defect_size_record = _defect_size_hard_requirement_record(spec, requirement)
    if defect_size_record is not None:
        records.append(defect_size_record)
    width_record = _width_hard_requirement_record(spec, requirement)
    if width_record is not None:
        records.append(width_record)
    speed_record = _speed_hard_requirement_record(spec, requirement)
    if speed_record is not None:
        records.append(speed_record)
    mode_record = _categorical_hard_requirement_record(
        "Inspection Mode", requirement.inline_offline, spec.equipment.inline_offline
    )
    if mode_record is not None:
        records.append(mode_record)
    method_record = _categorical_hard_requirement_record(
        "Measurement Method", requirement.measurement_method, spec.equipment.measurement_method
    )
    if method_record is not None:
        records.append(method_record)
    if requirement.measurement_principle is not None:
        required_principle = (
            categorical_match.extract_measurement_principle(requirement.measurement_principle)
            or requirement.measurement_principle
        )
        principle_record = _categorical_hard_requirement_record(
            "Measurement Principle", required_principle, spec.equipment.measurement_principle
        )
        if principle_record is not None:
            records.append(principle_record)
    return records


def build_inspection_item_hard_requirement_records(
    chosen_candidate: Optional[CandidateEquipment],
) -> List[ComplianceRecord]:
    """
    agent.candidate_matcher.build_candidates()가 이미 판정한 "검사 항목(예:
    surface_defect/edge_defect)을 이 후보가 실제로 지원하는가" hard requirement
    판정을 그대로 ComplianceRecord로 옮긴다.

    다른 hard requirement(Range/Accuracy/...)는 SpecificationSchema에 값을
    저장해뒀다가 그 필드로부터 다시 계산하는 방식(build_hard_requirement_report)을
    쓰지만, 검사 항목 지원 여부는 숫자/범주형 단일 값이 아니라 "요구 항목별로
    여러 개"이므로 SpecificationSchema에 새 필드를 추가하지 않고 candidate_matcher가
    만든 CandidateFieldMatch를 그대로 재사용한다(같은 판정 로직을 중복 구현하지
    않기 위함 — hard 원칙은 동일하게 유지).
    """
    if chosen_candidate is None:
        return []
    records: List[ComplianceRecord] = []
    for match in chosen_candidate.matches:
        if not match.field_key.startswith("inspection_item_"):
            continue
        reason = match.evidence_text or f"장비의 {match.item} 지원 여부를 확인하지 못했습니다."
        records.append(
            ComplianceRecord(
                item=match.item,
                result=match.result,
                reason=f"요구 검사 항목 {match.requirement_text} / {reason} → {match.result}",
                source=match.source,
                hard=True,
            )
        )
    return records


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
