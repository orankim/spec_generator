"""
Specification JSON -> Markdown 렌더러.

표준 포맷은 docs/SPECIFICATION_MARKDOWN_FORMAT.md에 문서화되어 있고,
converters/markdown_to_spec.py가 이 포맷을 역파싱해서 SpecificationSchema로
되돌릴 수 있다 (완전히 임의의 마크다운이 아니라, 우리가 정의한 표준 포맷 기준).
"""
from __future__ import annotations

from typing import List, Optional

from agent.schemas import CandidateEquipment, ComplianceRecord, RequirementSchema, SpecificationSchema, ValidationResult
from agent.spec_validator import build_compliance_report

from .common import (
    COMPLIANCE_SECTION_EMPTY_NOTE,
    COMPLIANCE_SECTION_TITLE,
    RenderRow,
    RenderSection,
    build_notes_section,
    build_sections,
    build_validation_section,
)

_SECTION_ORDER = [
    "equipment",
    "inspection_target",
    "inspection_requirements",
    "measurement_performance",
    "spatial_performance",
    "optical_system",
    "defect_inspection",
    "inspection_performance",
    "system_configuration",
    "interfaces",
    "environment",
    "safety",
]


def _row_to_md_table_row(row: RenderRow, has_status_col: bool) -> str:
    if has_status_col:
        status = row.status or "-"
        source = row.source or "-"
        unit = row.unit or "-"
        return f"| {row.label} | {unit} | {row.value_display} | {status} | {source} |"
    return f"| {row.label} | {row.value_display} |"


def _section_to_md(section: RenderSection, has_status_col: bool) -> str:
    lines = [f"## {section.title}", ""]
    if section.note:
        lines.append(f"_{section.note}_")
        lines.append("")
    if not section.rows:
        if not section.note:
            lines.append("_No data._")
            lines.append("")
        return "\n".join(lines)

    if has_status_col:
        lines.append("| Item | Unit | Specification | Status | Source |")
        lines.append("|---|---|---|---|---|")
    else:
        lines.append("| Item | Specification |")
        lines.append("|---|---|")
    for row in section.rows:
        lines.append(_row_to_md_table_row(row, has_status_col))

    lines.append("")
    return "\n".join(lines)


def _fmt_opt(value) -> str:
    return "UNKNOWN" if value is None else str(value)


def _compliance_records_to_md(records: List[ComplianceRecord]) -> str:
    lines = [f"## {COMPLIANCE_SECTION_TITLE}", ""]
    if not records:
        lines.append(f"_{COMPLIANCE_SECTION_EMPTY_NOTE}_")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Item | Unit | Requirement | Specification | Result | Reason |")
    lines.append("|---|---|---|---|---|---|")
    for r in records:
        lines.append(
            f"| {r.item} | {r.unit or '-'} | {_fmt_opt(r.requirement)} | {_fmt_opt(r.specification)} | {r.result} | {r.reason} |"
        )
    lines.append("")
    return "\n".join(lines)


def _validation_section_to_md(section: RenderSection) -> str:
    lines = [f"## {section.title}", ""]
    if section.note:
        lines.append(f"_{section.note}_")
        lines.append("")
    if not section.rows:
        return "\n".join(lines)
    lines.append("| Level / Field | Message |")
    lines.append("|---|---|")
    for row in section.rows:
        lines.append(f"| {row.label} | {row.value_display} |")
    lines.append("")
    return "\n".join(lines)


def render_markdown(
    specification: SpecificationSchema,
    requirement: Optional[RequirementSchema] = None,
    validation: Optional[ValidationResult] = None,
    title: str = "Electrode Inspection Equipment Specification",
) -> str:
    sections = build_sections(specification)
    by_id = {s.id: s for s in sections}
    ordered = [by_id[key] for key in _SECTION_ORDER]

    numeric_section_ids = {
        "inspection_target",
        "inspection_requirements",
        "measurement_performance",
        "spatial_performance",
        "inspection_performance",
        "defect_inspection",
    }

    parts = [f"# {title}", ""]
    for section in ordered:
        parts.append(_section_to_md(section, has_status_col=section.id in numeric_section_ids))

    parts.append(_validation_section_to_md(build_validation_section(validation)))

    compliance_records = build_compliance_report(specification, requirement)
    parts.append(_compliance_records_to_md(compliance_records))

    parts.append(_section_to_md(build_notes_section(specification), has_status_col=False))

    return "\n".join(parts).rstrip() + "\n"


def render_candidate_markdown(candidate: CandidateEquipment, requirement: Optional[RequirementSchema] = None) -> str:
    """
    추천된 CandidateEquipment 하나를 간단한 Markdown 사양서로 렌더링한다.
    render_markdown()(SpecificationSchema 기반, LLM이 채운 값 포함)과는 별개의
    경로다 — 이 함수는 candidate.equipment_fact(사양서 원문에서 결정론적으로
    추출된 값)만 사용하고 LLM을 전혀 거치지 않는다. 근거 없는 필드는 "UNKNOWN"
    으로 정직하게 남긴다(요청서: "마크다운 사양서 생성" 버튼).
    """
    fact = candidate.equipment_fact
    name_parts = [p for p in (candidate.manufacturer, candidate.model) if p]
    equipment_name = " ".join(name_parts) if name_parts else _fmt_opt(None)

    lines: List[str] = ["# Equipment Specification", "", "## General", ""]
    lines.append(f"- Equipment Name: {equipment_name}")
    lines.append(f"- Manufacturer: {_fmt_opt(candidate.manufacturer)}")
    lines.append(f"- Model: {_fmt_opt(candidate.model)}")
    lines.append(f"- Equipment Type: {_fmt_opt(fact.equipment_type if fact else None)}")
    lines.append(f"- Measurement Principle: {_fmt_opt(fact.measurement_principle if fact else None)}")
    lines.append(f"- Inspection Mode: {_fmt_opt(fact.inline_offline if fact else None)}")
    lines.append(f"- Measurement Type: {_fmt_opt(fact.measurement_method if fact else None)}")
    lines.append("")

    lines.append("## Inspection Performance")
    lines.append("")
    lines.append("| Item | Specification |")
    lines.append("|---|---|")
    width_display = f"{fact.width_mm} mm" if fact and fact.width_mm is not None else _fmt_opt(None)
    lines.append(f"| Maximum Electrode Width | {width_display} |")
    if fact and fact.range_min is not None and fact.range_max is not None:
        range_display = f"{fact.range_min} ~ {fact.range_max} {fact.range_unit or ''}".strip()
    else:
        range_display = _fmt_opt(None)
    lines.append(f"| Measurement Range | {range_display} |")
    accuracy_display = (
        f"±{fact.accuracy_value} {fact.accuracy_unit or ''}".strip() if fact and fact.accuracy_value is not None else _fmt_opt(None)
    )
    lines.append(f"| Accuracy | {accuracy_display} |")
    resolution_display = (
        f"{fact.resolution_value} {fact.resolution_unit or ''}".strip() if fact and fact.resolution_value is not None else _fmt_opt(None)
    )
    lines.append(f"| Resolution | {resolution_display} |")
    speed_display = (
        f"{fact.speed_value} {fact.speed_unit or ''}".strip() if fact and fact.speed_value is not None else _fmt_opt(None)
    )
    lines.append(f"| Measurement Speed | {speed_display} |")
    lines.append("")

    lines.append("## Inspection Items")
    lines.append("")
    inspection_items = requirement.inspection_items if requirement else []
    if inspection_items:
        for item in inspection_items:
            lines.append(f"- {item.replace('_', ' ').title()}")
    else:
        lines.append(f"_{_fmt_opt(None)}_")
    lines.append("")

    lines.append("## Defect Inspection")
    lines.append("")
    lines.append("| Item | Specification |")
    lines.append("|---|---|")
    min_defect_display = (
        f"{fact.min_defect_size_value} {fact.min_defect_size_unit or ''}".strip()
        if fact and fact.min_defect_size_value is not None
        else _fmt_opt(None)
    )
    lines.append(f"| Minimum Detectable Defect | {min_defect_display} |")
    defect_types_display = ", ".join(fact.defect_types) if fact and fact.defect_types else _fmt_opt(None)
    lines.append(f"| Defect Types | {defect_types_display} |")
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    lines.append(f"- {candidate.source_document}")

    return "\n".join(lines).rstrip() + "\n"
