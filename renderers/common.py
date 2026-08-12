"""
Specification JSON -> {Markdown, HTML, PPTX} 렌더러들이 공유하는 중간 모델.

목표: "어떤 필드가 어느 섹션의 몇 번째 행에 어떤 라벨로 들어가는지"를 이 파일
한 곳에서만 정의하고, markdown_renderer/html_renderer/pptx_renderer는 전부
build_sections()의 결과(RenderSection 목록)만 소비한다. 이렇게 하면 세 포맷
중 하나에서 필드를 추가/변경해도 나머지 두 포맷이 자동으로 따라온다
(포맷별로 필드 매핑을 3번 따로 유지하지 않는다).

SpecificationSchema 자체는 건드리지 않는다 (기존 기능 유지 원칙). 각 섹션의
데이터 표는 "이 장비의 사양이 무엇인가"만 보여주고(Item/Unit/Specification/
Status/Source), Requirement 대비 PASS/FAIL 비교는 여기서 다루지 않는다 —
그건 "13. Requirement Compliance" 섹션(agent.spec_validator.build_compliance_report)
전용 관심사로 분리했다 (요청서 14/18/27절: Requirement와 Specification을
혼동하지 않고, Schema/Markdown/HTML/PPTX 각자의 책임을 분리한다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from agent.schemas import SourcedNumber, SpecificationSchema, ValidationResult

UNKNOWN = "UNKNOWN"


@dataclass
class RenderRow:
    label: str
    value_display: str  # 이미 사람이 읽을 문자열로 포맷된 값 (없으면 "UNKNOWN")
    unit: Optional[str] = None
    status: Optional[str] = None  # USER_DEFINED | VERIFIED | INFERRED | UNKNOWN | None(추적 대상 아님)
    source: Optional[str] = None  # 사람이 읽을 근거 요약 (문서명/슬라이드 등)
    field_path: Optional[str] = None  # "measurement_performance.accuracy_um" 같은 SpecificationSchema 경로.
    # converters/markdown_to_spec.py가 라벨→필드를 다시 매핑할 때, 이 파일의 문자열을
    # 따로 베끼지 않고 이 값을 그대로 읽어 쓴다 (라벨 매핑의 단일 소스).


@dataclass
class RenderSection:
    id: str
    title: str
    rows: List[RenderRow] = field(default_factory=list)
    note: Optional[str] = None  # 섹션 자체에 대한 부가 설명 (예: 표시할 값이 전혀 없을 때)


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


def _source_summary(sn: Optional[SourcedNumber]) -> Optional[str]:
    if sn is None or sn.source is None:
        return None
    ref = sn.source
    parts = []
    if ref.document:
        parts.append(ref.document)
    if ref.slide is not None:
        parts.append(f"slide {ref.slide}")
    if ref.page is not None:
        parts.append(f"p.{ref.page}")
    if ref.section:
        parts.append(ref.section)
    return ", ".join(parts) if parts else (ref.source_type or None)


def _num_row(label: str, field_path: str, sn: Optional[SourcedNumber]) -> RenderRow:
    value = sn.value if sn else None
    unit = sn.unit if sn and sn.unit else None
    status = sn.status if sn else None
    return RenderRow(
        label=label,
        value_display=_fmt_num(value),
        unit=unit,
        status=status,
        source=_source_summary(sn),
        field_path=field_path,
    )


def _plain_row(label: str, field_path: str, value: Any) -> RenderRow:
    return RenderRow(label=label, value_display=_fmt_plain(value), field_path=field_path)


def build_sections(specification: SpecificationSchema) -> List[RenderSection]:
    """SpecificationSchema를 12개 논리 섹션(1~12)의 RenderSection 목록으로 변환한다."""
    eq = specification.equipment
    it = specification.inspection_target
    ir = specification.inspection_requirements
    mp = specification.measurement_performance
    sp = specification.spatial_performance
    ip = specification.inspection_performance
    dd = specification.defect_detection
    opt = specification.optical_system
    sysc = specification.system
    iface = specification.interfaces
    env = specification.environment
    safety = specification.safety

    sections = [
        RenderSection(
            id="equipment",
            title="1. General Specification",
            rows=[
                _plain_row("Equipment Name", "equipment.name", eq.name),
                _plain_row("Equipment Type", "equipment.equipment_type", eq.equipment_type),
                _plain_row("Manufacturer", "equipment.manufacturer", eq.manufacturer),
                _plain_row("Model", "equipment.model", eq.model),
                _plain_row("Version", "equipment.version", eq.version),
                _plain_row("Application", "equipment.application", eq.application),
                _plain_row("Inspection Method", "equipment.inspection_method", eq.inspection_method),
                _plain_row("Measurement Principle", "equipment.measurement_principle", eq.measurement_principle),
                _plain_row("Inline / Offline", "equipment.inline_offline", eq.inline_offline),
            ],
        ),
        RenderSection(
            id="inspection_target",
            title="2. Inspection Target",
            rows=[
                _plain_row("Material", "inspection_target.material", it.material),
                _plain_row("Product Type", "inspection_target.product_type", it.product_type),
                _plain_row("Electrode Type", "inspection_target.electrode_type", it.electrode_type),
                _plain_row("Width (mm)", "inspection_target.width_mm", it.width_mm),
                _plain_row("Length (mm)", "inspection_target.length_mm", it.length_mm),
                _plain_row("Thickness (um)", "inspection_target.thickness_um", it.thickness_um),
                _plain_row("Coating Thickness (um)", "inspection_target.coating_thickness_um", it.coating_thickness_um),
                _plain_row("Substrate", "inspection_target.substrate", it.substrate),
                _plain_row("Inspection Direction", "inspection_target.inspection_direction", it.inspection_direction),
                _num_row("Target Line Speed", "inspection_target.line_speed_mm_s", it.line_speed_mm_s),
            ],
        ),
        RenderSection(
            id="inspection_requirements",
            title="3. Inspection Requirements",
            rows=[
                _plain_row("Inspection Items", "inspection_items", specification.inspection_items),
                _plain_row("Inspection Area", "inspection_requirements.inspection_area", ir.inspection_area),
                _plain_row("Inspection Width (mm)", "inspection_requirements.inspection_width_mm", ir.inspection_width_mm),
                _plain_row("Inspection Length (mm)", "inspection_requirements.inspection_length_mm", ir.inspection_length_mm),
                _num_row("Sampling Interval", "inspection_requirements.sampling_interval", ir.sampling_interval),
                _plain_row("Inspection Frequency", "inspection_requirements.inspection_frequency", ir.inspection_frequency),
                _plain_row("Inspection Mode", "inspection_requirements.inspection_mode", ir.inspection_mode),
            ],
        ),
        RenderSection(
            id="measurement_performance",
            title="4. Measurement Performance",
            rows=[
                _num_row("Measurement Range", "measurement_performance.measurement_range", mp.measurement_range),
                _num_row("Resolution", "measurement_performance.resolution_um", mp.resolution_um),
                _num_row("Accuracy", "measurement_performance.accuracy_um", mp.accuracy_um),
                _num_row("Repeatability", "measurement_performance.repeatability_um", mp.repeatability_um),
                _num_row("Reproducibility", "measurement_performance.reproducibility_um", mp.reproducibility_um),
                _num_row("Linearity", "measurement_performance.linearity", mp.linearity),
                _num_row("Measurement Speed", "measurement_performance.measurement_speed", mp.measurement_speed),
                _num_row("Sampling Rate", "measurement_performance.sampling_rate", mp.sampling_rate),
            ],
        ),
        RenderSection(
            id="spatial_performance",
            title="5. Spatial Performance",
            rows=[
                _num_row("X Range", "spatial_performance.x_range", sp.x_range),
                _num_row("Y Range", "spatial_performance.y_range", sp.y_range),
                _num_row("Z Range", "spatial_performance.z_range", sp.z_range),
                _num_row("X Resolution", "spatial_performance.x_resolution_um", sp.x_resolution_um),
                _num_row("Y Resolution", "spatial_performance.y_resolution_um", sp.y_resolution_um),
                _num_row("Z Resolution", "spatial_performance.z_resolution_um", sp.z_resolution_um),
                _num_row("FOV", "spatial_performance.fov_mm", sp.fov_mm),
                _num_row("Working Distance", "spatial_performance.working_distance", sp.working_distance),
                _num_row("Pixel Size", "spatial_performance.pixel_size", sp.pixel_size),
                _num_row("Point Spacing", "spatial_performance.point_spacing", sp.point_spacing),
                _num_row("Profile Spacing", "spatial_performance.profile_spacing", sp.profile_spacing),
                _num_row("Spatial Sampling Interval", "spatial_performance.sampling_interval_um", sp.sampling_interval_um),
            ],
        ),
        RenderSection(
            id="optical_system",
            title="6. Optical System",
            rows=[
                _plain_row("Light Source", "optical_system.light_source", opt.light_source),
                _plain_row("Wavelength", "optical_system.wavelength", opt.wavelength),
                _plain_row("Spectral Range", "optical_system.spectral_range", opt.spectral_range),
                _plain_row("Optical Method", "optical_system.optical_method", opt.optical_method),
                _plain_row("Interferometry", "optical_system.interferometry", opt.interferometry),
                _plain_row("Reflectometry", "optical_system.reflectometry", opt.reflectometry),
                _plain_row("OCT", "optical_system.oct", opt.oct),
                _plain_row("Laser", "optical_system.laser", opt.laser),
                _plain_row("Sensor Type", "optical_system.sensor_type", opt.sensor_type),
                _plain_row("Camera", "optical_system.camera", opt.camera),
                _plain_row("Camera Resolution", "optical_system.camera_resolution", opt.camera_resolution),
                _plain_row("Lens", "optical_system.lens", opt.lens),
                _plain_row("Objective", "optical_system.objective", opt.objective),
                _plain_row("Optical Working Distance", "optical_system.working_distance", opt.working_distance),
            ],
        ),
        RenderSection(
            id="defect_inspection",
            title="7. Defect Inspection",
            rows=[
                _plain_row("Defect Detection", "defect_detection.defect_detection", dd.defect_detection),
                _num_row("Minimum Defect Size", "defect_detection.minimum_defect_size_um", dd.minimum_defect_size_um),
                _plain_row("Defect Types", "defect_detection.defect_types", dd.defect_types),
                _num_row("Detection Resolution", "defect_detection.detection_resolution", dd.detection_resolution),
                _num_row("Defect Detection Accuracy", "defect_detection.defect_detection_accuracy", dd.defect_detection_accuracy),
                _num_row("False Positive Rate", "defect_detection.false_positive_rate", dd.false_positive_rate),
                _num_row("False Negative Rate", "defect_detection.false_negative_rate", dd.false_negative_rate),
                _plain_row("Classification", "defect_detection.classification", dd.classification),
            ],
        ),
        RenderSection(
            id="inspection_performance",
            title="7-1. Inspection Performance",
            rows=[
                _num_row("Scan Speed", "inspection_performance.scan_speed_mm_s", ip.scan_speed_mm_s),
                _num_row("Line Speed", "inspection_performance.line_speed_mm_s", ip.line_speed_mm_s),
                _num_row("Overall Measurement Speed", "inspection_performance.measurement_speed", ip.measurement_speed),
                _num_row("Tact Time", "inspection_performance.tact_time_s", ip.tact_time_s),
                _num_row("Inspection Width", "inspection_performance.inspection_width_mm", ip.inspection_width_mm),
            ],
        ),
        RenderSection(
            id="system_configuration",
            title="8. System Configuration",
            rows=[
                _plain_row("Automation Level", "system.automation_level", sysc.automation_level),
                _plain_row("Stage", "system.stage", sysc.stage),
                _plain_row("Motion System", "system.motion_system", sysc.motion_system),
                _plain_row("Sensor", "system.sensor", sysc.sensor),
                _plain_row("Controller", "system.controller", sysc.controller),
                _plain_row("PC", "system.pc", sysc.pc),
                _plain_row("Software", "system.software", sysc.software),
                _plain_row("Display", "system.display", sysc.display),
                _plain_row("Power", "system.power", sysc.power),
                _plain_row("Air", "system.air", sysc.air),
                _plain_row("Cooling", "system.cooling", sysc.cooling),
                _plain_row("Mechanical Configuration", "system.mechanical_configuration", sysc.mechanical_configuration),
                _plain_row("Data Output", "system.data_output", sysc.data_output),
            ],
        ),
        RenderSection(
            id="interfaces",
            title="9. Interfaces / Data",
            rows=[
                _plain_row("PLC", "interfaces.plc", iface.plc),
                _plain_row("MES", "interfaces.mes", iface.mes),
                _plain_row("OPC-UA", "interfaces.opc_ua", iface.opc_ua),
                _plain_row("EtherNet/IP", "interfaces.ethernet_ip", iface.ethernet_ip),
                _plain_row("PROFINET", "interfaces.profinet", iface.profinet),
                _plain_row("Modbus", "interfaces.modbus", iface.modbus),
                _plain_row("Ethernet", "interfaces.ethernet", iface.ethernet),
                _plain_row("Digital I/O", "interfaces.digital_io", iface.digital_io),
                _plain_row("Analog I/O", "interfaces.analog_io", iface.analog_io),
                _plain_row("API", "interfaces.api", iface.api),
                _plain_row("Data Format", "interfaces.data_format", iface.data_format),
                _plain_row("Data Storage", "interfaces.data_storage", iface.data_storage),
                _plain_row("Network", "interfaces.network", iface.network),
                _plain_row("Other Interfaces", "interfaces.other_interfaces", iface.other_interfaces),
            ],
        ),
        RenderSection(
            id="environment",
            title="10. Environment",
            rows=[
                _plain_row("Operating Temperature", "environment.operating_temperature", env.operating_temperature),
                _plain_row("Storage Temperature", "environment.storage_temperature", env.storage_temperature),
                _plain_row("Humidity", "environment.humidity", env.humidity),
                _plain_row("Installation Space", "environment.installation_space", env.installation_space),
                _plain_row("Site Power Requirement", "environment.power", env.power),
                _plain_row("Vibration Requirement", "environment.vibration_requirement", env.vibration_requirement),
                _plain_row("Dust", "environment.dust", env.dust),
                _plain_row("Installation Environment", "environment.installation_environment", env.installation_environment),
                _plain_row("Clean Room", "environment.clean_room", env.clean_room),
            ],
        ),
        RenderSection(
            id="safety",
            title="11. Safety",
            rows=[
                _plain_row("Safety Standard", "safety.safety_standard", safety.safety_standard),
                _plain_row("Laser Class", "safety.laser_class", safety.laser_class),
                _plain_row("Interlock", "safety.interlock", safety.interlock),
                _plain_row("Emergency Stop", "safety.emergency_stop", safety.emergency_stop),
                _plain_row("Safety Sensor", "safety.safety_sensor", safety.safety_sensor),
                _plain_row("Protective Cover", "safety.protective_cover", safety.protective_cover),
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
        return RenderSection(id="validation", title="12. Validation / Acceptance", rows=[], note="Not validated.")
    rows = [
        RenderRow(label=f"[{issue.level.upper()}] {issue.field}", value_display=issue.message)
        for issue in validation.issues
    ]
    overall = "PASS" if validation.is_valid else "FAIL"
    note = f"Overall: {overall}" if not rows else f"Overall: {overall} ({len(rows)} issue(s))"
    return RenderSection(id="validation", title="12. Validation / Acceptance", rows=rows, note=note)


#: "13. Requirement Compliance" 섹션 제목. ComplianceRecord는 Item/Unit/Requirement/
#: Specification/Result/Reason이라는, 다른 섹션(Item/Unit/Specification/Status/Source)과는
#: 다른 표 모양을 가지므로 RenderRow에 억지로 끼워맞추지 않고 각 렌더러가 List[ComplianceRecord]를
#: 직접 포맷한다 (markdown_renderer/html_renderer/pptx_renderer 참고).
COMPLIANCE_SECTION_TITLE = "13. Requirement Compliance"
COMPLIANCE_SECTION_EMPTY_NOTE = "No requirement provided for comparison."
