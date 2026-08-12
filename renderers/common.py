"""
Specification JSON -> {Markdown, HTML, PPTX} 렌더러들이 공유하는 중간 모델.

목표: "어떤 필드가 어느 섹션의 몇 번째 행에 어떤 라벨로 들어가는지"를 이 파일
한 곳에서만 정의하고, markdown_renderer/html_renderer/pptx_renderer는 전부
build_sections()의 결과(RenderSection 목록)만 소비한다. 이렇게 하면 세 포맷
중 하나에서 필드를 추가/변경해도 나머지 두 포맷이 자동으로 따라온다
(포맷별로 필드 매핑을 3번 따로 유지하지 않는다).

SpecificationSchema 자체는 건드리지 않는다 (기존 기능 유지 원칙). PASS/FAIL/
UNKNOWN 판정이나 Requirement 대비 비교는 스키마에 저장하지 않고 여기서
"렌더링 시점에" 계산되는 파생 정보다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from agent.schemas import RequirementSchema, SourcedNumber, SpecificationSchema, ValidationResult

UNKNOWN = "UNKNOWN"


@dataclass
class RenderRow:
    label: str
    value_display: str  # 이미 사람이 읽을 문자열로 포맷된 값 (없으면 "UNKNOWN")
    unit: Optional[str] = None
    requirement_display: Optional[str] = None  # None이면 "이 필드는 요구사항과 비교 대상이 아님"
    result: Optional[str] = None  # "PASS" | "FAIL" | "UNKNOWN" | None(비교 대상 아님)
    source: Optional[str] = None
    source_type: Optional[str] = None
    field_path: Optional[str] = None  # "measurement_performance.accuracy_um" 같은 SpecificationSchema 경로.
    # converters/markdown_to_spec.py가 라벨→필드를 다시 매핑할 때, 이 파일의 문자열을
    # 따로 베끼지 않고 이 값을 그대로 읽어 쓴다 (라벨 매핑의 단일 소스).


@dataclass
class RenderSection:
    id: str
    title: str
    rows: List[RenderRow] = field(default_factory=list)
    note: Optional[str] = None  # 섹션 자체에 대한 부가 설명 (예: 표시할 값이 전혀 없을 때)


# 필드 -> Requirement 필드 비교 매핑. 값이 작을수록 좋은(<=) 지표만 우선 지원한다
# (accuracy/resolution/defect size 등은 모두 이 방향). scan_speed처럼 "클수록 좋음"인
# 지표는 이번 단계에서는 비교하지 않고 "-"로 표시한다 (정확한 방향성 설정에는
# 필드별 comparator 설정이 더 필요하며, 향후 template_config류 설정으로 확장 가능).
def _cmp_le(spec_value: Optional[float], req_value: Optional[float]) -> Optional[str]:
    if spec_value is None:
        return UNKNOWN
    if req_value is None:
        return None
    return "PASS" if spec_value <= req_value else "FAIL"


def _fmt_num(value: Optional[float]) -> str:
    if value is None:
        return UNKNOWN
    return str(value)


def _fmt_plain(value: Any) -> str:
    if value is None or value == "" or value == []:
        return UNKNOWN
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else UNKNOWN
    if isinstance(value, bool):
        return "지원" if value else "미지원"
    return str(value)


def _source_label(sn: Optional[SourcedNumber]) -> Optional[str]:
    if sn is None or sn.source_type is None:
        return None
    label = {
        "user_requirement": "사용자 요구사항",
        "document": sn.source or "문서",
        "inferred": "AI 추정",
        "default": "기본값",
    }.get(sn.source_type, sn.source_type)
    return label


def _num_row(label: str, field_path: str, sn: Optional[SourcedNumber], requirement_value: Optional[float] = None) -> RenderRow:
    value = sn.value if sn else None
    unit = sn.unit if sn and sn.unit else None
    result = _cmp_le(value, requirement_value) if requirement_value is not None or value is None else None
    return RenderRow(
        label=label,
        value_display=_fmt_num(value),
        unit=unit,
        requirement_display=_fmt_num(requirement_value) if requirement_value is not None else None,
        result=result,
        source=(sn.source if sn else None),
        source_type=(sn.source_type if sn else None),
        field_path=field_path,
    )


def _plain_row(label: str, field_path: str, value: Any) -> RenderRow:
    return RenderRow(label=label, value_display=_fmt_plain(value), field_path=field_path)


def build_sections(
    specification: SpecificationSchema,
    requirement: Optional[RequirementSchema] = None,
) -> List[RenderSection]:
    """SpecificationSchema(+선택적 RequirementSchema)를 13개 논리 섹션의 RenderSection 목록으로 변환한다."""
    eq = specification.equipment
    it = specification.inspection_target
    mp = specification.measurement_performance
    sp = specification.spatial_performance
    ip = specification.inspection_performance
    dd = specification.defect_detection
    opt = specification.optical_system
    sysc = specification.system
    iface = specification.interfaces
    env = specification.environment
    safety = specification.safety

    req_accuracy = requirement.required_accuracy_um if requirement else None
    req_resolution = requirement.required_resolution_um if requirement else None
    req_min_defect = requirement.minimum_defect_size_um if requirement else None

    sections = [
        RenderSection(
            id="equipment",
            title="1. Equipment",
            rows=[
                _plain_row("Equipment Name", "equipment.name", eq.name),
                _plain_row("Manufacturer", "equipment.manufacturer", eq.manufacturer),
                _plain_row("Model", "equipment.model", eq.model),
                _plain_row("Measurement Principle", "equipment.measurement_principle", eq.measurement_principle),
            ],
        ),
        RenderSection(
            id="inspection_target",
            title="2. Inspection Target",
            rows=[
                _plain_row("Material", "inspection_target.material", it.material),
                _plain_row("Product Type", "inspection_target.product_type", it.product_type),
                _plain_row("Width (mm)", "inspection_target.width_mm", it.width_mm),
                _plain_row("Length (mm)", "inspection_target.length_mm", it.length_mm),
                _plain_row("Thickness (um)", "inspection_target.thickness_um", it.thickness_um),
                _plain_row("Substrate", "inspection_target.substrate", it.substrate),
                _plain_row("Inspection Direction", "inspection_target.inspection_direction", it.inspection_direction),
            ],
        ),
        RenderSection(
            id="inspection_requirements",
            title="3. Inspection Requirements",
            rows=[_plain_row("Inspection Items", "inspection_items", specification.inspection_items)],
        ),
        RenderSection(
            id="measurement_performance",
            title="4. Measurement Performance",
            rows=[
                _num_row("Measurement Range", "measurement_performance.measurement_range", mp.measurement_range),
                _num_row("Resolution", "measurement_performance.resolution_um", mp.resolution_um, req_resolution),
                _num_row("Accuracy", "measurement_performance.accuracy_um", mp.accuracy_um, req_accuracy),
                _num_row("Repeatability", "measurement_performance.repeatability_um", mp.repeatability_um),
                _num_row("Reproducibility", "measurement_performance.reproducibility_um", mp.reproducibility_um),
            ],
        ),
        RenderSection(
            id="spatial_performance",
            title="5. Spatial Performance",
            rows=[
                _num_row("FOV", "spatial_performance.fov_mm", sp.fov_mm),
                _num_row("X Resolution", "spatial_performance.x_resolution_um", sp.x_resolution_um),
                _num_row("Y Resolution", "spatial_performance.y_resolution_um", sp.y_resolution_um),
                _num_row("Z Resolution", "spatial_performance.z_resolution_um", sp.z_resolution_um),
                _num_row("Sampling Interval", "spatial_performance.sampling_interval_um", sp.sampling_interval_um),
            ],
        ),
        RenderSection(
            id="optical_system",
            title="6. Optical System",
            rows=[
                _plain_row("Light Source", "optical_system.light_source", opt.light_source),
                _plain_row("Wavelength", "optical_system.wavelength", opt.wavelength),
                _plain_row("Optical Method", "optical_system.optical_method", opt.optical_method),
                _plain_row("Sensor Type", "optical_system.sensor_type", opt.sensor_type),
                _plain_row("Camera Resolution", "optical_system.camera_resolution", opt.camera_resolution),
                _plain_row("Objective", "optical_system.objective", opt.objective),
                _plain_row("Working Distance", "optical_system.working_distance", opt.working_distance),
            ],
        ),
        RenderSection(
            id="defect_inspection",
            title="7. Defect Inspection",
            rows=[
                _num_row("Minimum Defect Size", "defect_detection.minimum_defect_size_um", dd.minimum_defect_size_um, req_min_defect),
                _plain_row("Defect Types", "defect_detection.defect_types", dd.defect_types),
                _num_row("Defect Detection Accuracy", "defect_detection.defect_detection_accuracy", dd.defect_detection_accuracy),
                _num_row("False Positive Rate", "defect_detection.false_positive_rate", dd.false_positive_rate),
                _num_row("False Negative Rate", "defect_detection.false_negative_rate", dd.false_negative_rate),
            ],
        ),
        RenderSection(
            id="inspection_performance",
            title="8. Inspection Performance",
            rows=[
                _num_row("Scan Speed", "inspection_performance.scan_speed_mm_s", ip.scan_speed_mm_s),
                _num_row("Line Speed", "inspection_performance.line_speed_mm_s", ip.line_speed_mm_s),
                _num_row("Measurement Speed", "inspection_performance.measurement_speed", ip.measurement_speed),
                _num_row("Tact Time", "inspection_performance.tact_time_s", ip.tact_time_s),
                _num_row("Inspection Width", "inspection_performance.inspection_width_mm", ip.inspection_width_mm),
            ],
        ),
        RenderSection(
            id="system_configuration",
            title="9. System Configuration",
            rows=[
                _plain_row("Automation Level", "system.automation_level", sysc.automation_level),
                _plain_row("Stage", "system.stage", sysc.stage),
                _plain_row("Motion System", "system.motion_system", sysc.motion_system),
                _plain_row("Controller", "system.controller", sysc.controller),
                _plain_row("Software", "system.software", sysc.software),
                _plain_row("Data Output", "system.data_output", sysc.data_output),
            ],
        ),
        RenderSection(
            id="interfaces",
            title="10. Interfaces / Data",
            rows=[
                _plain_row("Ethernet", "interfaces.ethernet", iface.ethernet),
                _plain_row("Digital I/O", "interfaces.digital_io", iface.digital_io),
                _plain_row("PLC", "interfaces.plc", iface.plc),
                _plain_row("MES", "interfaces.mes", iface.mes),
                _plain_row("OPC-UA", "interfaces.opc_ua", iface.opc_ua),
                _plain_row("Other Interfaces", "interfaces.other_interfaces", iface.other_interfaces),
            ],
        ),
        RenderSection(
            id="environment",
            title="11. Environment",
            rows=[
                _plain_row("Operating Temperature", "environment.operating_temperature", env.operating_temperature),
                _plain_row("Humidity", "environment.humidity", env.humidity),
                _plain_row("Installation Space", "environment.installation_space", env.installation_space),
                _plain_row("Power", "environment.power", env.power),
                _plain_row("Vibration Requirement", "environment.vibration_requirement", env.vibration_requirement),
            ],
        ),
        RenderSection(
            id="safety",
            title="12. Safety",
            rows=[
                _plain_row("Safety Standard", "safety.safety_standard", safety.safety_standard),
                _plain_row("Interlock", "safety.interlock", safety.interlock),
                _plain_row("Emergency Stop", "safety.emergency_stop", safety.emergency_stop),
            ],
        ),
    ]
    return sections


def build_notes_section(specification: SpecificationSchema) -> RenderSection:
    rows = []
    for note in specification.notes:
        rows.append(_plain_row("Note", "notes", note))
    for assumption in specification.assumptions:
        rows.append(_plain_row("Assumption", "assumptions", assumption))
    if specification.needs_confirmation:
        rows.append(_plain_row("Needs Confirmation", "needs_confirmation", specification.needs_confirmation))
    if specification.sources:
        rows.append(_plain_row("Sources", "sources", specification.sources))
    return RenderSection(
        id="sources_notes",
        title="14. Sources / Notes",
        rows=rows,
        note=None if rows else "No notes recorded.",
    )


def build_validation_section(validation: Optional[ValidationResult]) -> RenderSection:
    if validation is None:
        return RenderSection(id="validation", title="13. Validation / Acceptance", rows=[], note="Not validated.")
    rows = [
        RenderRow(label=f"[{issue.level.upper()}] {issue.field}", value_display=issue.message)
        for issue in validation.issues
    ]
    overall = "PASS" if validation.is_valid else "FAIL"
    note = f"Overall: {overall}" if not rows else f"Overall: {overall} ({len(rows)} issue(s))"
    return RenderSection(id="validation", title="13. Validation / Acceptance", rows=rows, note=note)
