"""
CandidateEquipment 기반 "사양서 다운로드"(Markdown/Word) 두 출력 포맷이 공유하는
중간 데이터 모델.

renderers/common.py의 build_sections()는 SpecificationSchema(LLM이 채운 최종
사양서) 기반이고, 이 파일은 CandidateEquipment(사양서 원문에서 결정론적으로
추출한 값, LLM을 거치지 않음) 기반이다 — 서로 다른 데이터 소스이므로 통합하지
않는다("마크다운 사양서 생성" 버튼이 원래 candidate 기반으로 만들어진 이유는
tests/test_candidate_markdown_route.py 상단 docstring 참고: LLM이 채운 값과
섞이지 않는, 근거가 명확한 문서를 만들기 위함).

이 모듈이 만드는 CandidateSpecificationData 하나를 markdown_renderer.
render_candidate_markdown()과 docx_renderer.render_candidate_docx()가 각각
그대로 소비한다 — 두 포맷이 같은 candidate/requirement를 각자 독립적으로
재해석하면서 값이 어긋나는 문제를 막기 위함(요청서 4절).

값이 원본 사양서에 없으면 "UNKNOWN"으로 정직하게 남기고, 추측해서 채우지
않는다(기존 render_candidate_markdown()과 동일한 원칙).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from agent.schemas import CandidateEquipment, ComplianceRecord, RequirementSchema

UNKNOWN = "UNKNOWN"


@dataclass
class SpecRow:
    label: str
    value: str  # 사람이 읽을 형태로 이미 포맷된 문자열, 없으면 UNKNOWN
    status: str  # "VERIFIED"(사양서 원문에서 직접 추출됨) | "UNKNOWN"(원문에 없음)


@dataclass
class SpecSection:
    id: str
    title: str
    rows: List[SpecRow] = field(default_factory=list)


@dataclass
class ComplianceRow:
    item: str
    unit: Optional[str]
    required_display: str
    equipment_display: str
    result: str  # PASS | FAIL | UNKNOWN | N/A


@dataclass
class CandidateSpecificationData:
    equipment_name: str
    manufacturer_display: str
    model_display: str
    sections: List[SpecSection]
    compliance: List[ComplianceRow]
    sources: List[str]
    notes: List[str]


def _row(label: str, value, unit: Optional[str] = None) -> SpecRow:
    if value is None or value == "" or value == []:
        return SpecRow(label, UNKNOWN, UNKNOWN)
    display = f"{value} {unit}".strip() if unit else str(value)
    return SpecRow(label, display, "VERIFIED")


def _range_row(label: str, min_v, max_v, unit: Optional[str]) -> SpecRow:
    if min_v is None or max_v is None:
        return SpecRow(label, UNKNOWN, UNKNOWN)
    unit_part = f" {unit}" if unit else ""
    return SpecRow(label, f"{min_v} ~ {max_v}{unit_part}", "VERIFIED")


def _accuracy_row(label: str, value, unit: Optional[str]) -> SpecRow:
    if value is None:
        return SpecRow(label, UNKNOWN, UNKNOWN)
    unit_part = f" {unit}" if unit else ""
    return SpecRow(label, f"±{value}{unit_part}", "VERIFIED")


def build_candidate_specification_data(
    candidate: CandidateEquipment,
    requirement: Optional[RequirementSchema] = None,
    hard_requirement_report: Optional[List[ComplianceRecord]] = None,
) -> CandidateSpecificationData:
    fact = candidate.equipment_fact
    name_parts = [p for p in (candidate.manufacturer, candidate.model) if p]
    equipment_name = " ".join(name_parts) if name_parts else UNKNOWN

    speed_value = fact.speed_value if fact else None
    speed_unit = fact.speed_unit if fact and speed_value is not None else None
    width_mm = fact.width_mm if fact else None

    general = SpecSection(
        "general",
        "General Specification",
        [
            _row("Equipment Name", equipment_name if name_parts else None),
            _row("Equipment Type", fact.equipment_type if fact else None),
            _row("Manufacturer", candidate.manufacturer),
            _row("Model", candidate.model),
            _row("Measurement Principle", fact.measurement_principle if fact else None),
            _row("Inspection Mode", fact.inline_offline if fact else None),
            _row("Measurement Method", fact.measurement_method if fact else None),
        ],
    )

    # CandidateEquipmentFact에는 Material/Product Type/Electrode Type/Length/
    # Thickness/Coating Thickness를 추출하는 필드가 없다 — 근거 없는 값을 지어
    # 내지 않고 UNKNOWN으로 정직하게 남긴다(요청서 9절).
    inspection_target = SpecSection(
        "inspection_target",
        "Inspection Target",
        [
            _row("Material", None),
            _row("Product Type", None),
            _row("Electrode Type", None),
            _row("Maximum Electrode Width", width_mm, "mm"),
            _row("Length", None),
            _row("Thickness", None),
            _row("Coating Thickness", None),
            _row("Target Line Speed", speed_value, speed_unit),
        ],
    )

    inspection_items = requirement.inspection_items if requirement else []
    inspection_items_display = ", ".join(i.replace("_", " ").title() for i in inspection_items) if inspection_items else None
    inspection_requirements = SpecSection(
        "inspection_requirements",
        "Inspection Requirements",
        [
            _row("Inspection Items", inspection_items_display),
            _row("Inspection Width", width_mm, "mm"),
            _row("Inspection Mode", fact.inline_offline if fact else None),
        ],
    )

    measurement_performance = SpecSection(
        "measurement_performance",
        "Measurement Performance",
        [
            _range_row("Measurement Range", fact.range_min if fact else None, fact.range_max if fact else None, fact.range_unit if fact else None),
            _row("Resolution", fact.resolution_value if fact else None, fact.resolution_unit if fact and fact.resolution_value is not None else None),
            _accuracy_row("Accuracy", fact.accuracy_value if fact else None, fact.accuracy_unit if fact else None),
            _row("Repeatability", None),
            _row("Measurement Speed", speed_value, speed_unit),
            _row("Sampling Rate", None),
        ],
    )

    # Spatial Performance/Optical System/System Configuration/Interfaces/
    # Environment/Safety는 CandidateEquipmentFact가 전혀 추출하지 않는 영역이다
    # (사양서 원문에 표/문구로 있어도 현재 후보 추출 로직 범위 밖) — 전부
    # UNKNOWN으로 정직하게 표시한다. 섹션 자체를 생략하지 않는 이유는 요청서가
    # 명시한 문서 구조(13개 섹션)를 항상 일관되게 유지하기 위함이다.
    spatial_performance = SpecSection(
        "spatial_performance",
        "Spatial Performance",
        [
            _row("X Range", None), _row("Y Range", None), _row("Z Range", None),
            _row("X Resolution", None), _row("Y Resolution", None), _row("Z Resolution", None),
            _row("FOV", None), _row("Working Distance", None), _row("Pixel Size", None),
        ],
    )

    optical_system = SpecSection(
        "optical_system",
        "Optical System",
        [
            _row("Light Source", None), _row("Wavelength", None), _row("Optical Method", None),
            _row("Interferometry", None), _row("Reflectometry", None), _row("OCT", None),
            _row("Laser", None), _row("Sensor Type", None), _row("Camera", None),
        ],
    )

    defect_detected = bool(fact and (fact.defect_types or fact.min_defect_size_value is not None))
    defect_inspection = SpecSection(
        "defect_inspection",
        "Defect Inspection",
        [
            _row("Defect Detection", "지원" if defect_detected else None),
            _row("Minimum Defect Size", fact.min_defect_size_value if fact else None, fact.min_defect_size_unit if fact and fact.min_defect_size_value is not None else None),
            _row("Defect Types", ", ".join(fact.defect_types) if fact and fact.defect_types else None),
            _row("Detection Resolution", None),
            _row("Classification", None),
        ],
    )

    inspection_performance = SpecSection(
        "inspection_performance",
        "Inspection Performance",
        [
            _row("Scan Speed", None),
            _row("Line Speed", speed_value, speed_unit),
            _row("Overall Measurement Speed", speed_value, speed_unit),
            _row("Tact Time", None),
            _row("Inspection Width", width_mm, "mm"),
        ],
    )

    system_configuration = SpecSection(
        "system_configuration",
        "System Configuration",
        [
            _row("Automation Level", None), _row("Stage", None), _row("Motion System", None),
            _row("Sensor", None), _row("Controller", None), _row("PC", None),
            _row("Software", None), _row("Data Output", None),
        ],
    )

    interfaces = SpecSection(
        "interfaces",
        "Interfaces / Data",
        [
            _row("PLC", None), _row("MES", None), _row("OPC-UA", None), _row("EtherNet/IP", None),
            _row("PROFINET", None), _row("Modbus", None), _row("Ethernet", None), _row("Digital I/O", None),
            _row("API", None), _row("Data Format", None), _row("Data Storage", None),
        ],
    )

    environment = SpecSection(
        "environment",
        "Environment",
        [
            _row("Operating Temperature", None), _row("Storage Temperature", None), _row("Humidity", None),
            _row("Installation Space", None), _row("Site Power Requirement", None), _row("Clean Room", None),
        ],
    )

    safety = SpecSection(
        "safety",
        "Safety",
        [
            _row("Safety Standard", None), _row("Laser Class", None), _row("Interlock", None),
            _row("Emergency Stop", None), _row("Safety Sensor", None), _row("Protective Cover", None),
        ],
    )

    sections = [
        general, inspection_target, inspection_requirements, measurement_performance,
        spatial_performance, optical_system, defect_inspection, inspection_performance,
        system_configuration, interfaces, environment, safety,
    ]

    compliance: List[ComplianceRow] = []
    for r in (hard_requirement_report or []):
        if r.requirement is not None:
            req_display = f"{r.operator or ''} {r.requirement} {r.unit or ''}".strip()
        else:
            req_display = UNKNOWN
        eq_display = f"{r.specification} {r.unit or ''}".strip() if r.specification is not None else UNKNOWN
        compliance.append(
            ComplianceRow(item=r.item, unit=r.unit, required_display=req_display, equipment_display=eq_display, result=r.result)
        )

    notes = [
        "일부 사양은 원본 사양서에서 확인되지 않았습니다.",
        "UNKNOWN 항목은 추정값으로 채우지 않았습니다.",
    ]

    return CandidateSpecificationData(
        equipment_name=equipment_name,
        manufacturer_display=candidate.manufacturer or UNKNOWN,
        model_display=candidate.model or UNKNOWN,
        sections=sections,
        compliance=compliance,
        sources=[candidate.source_document] if candidate.source_document else [],
        notes=notes,
    )
