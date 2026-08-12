"""
Specification JSON -> Markdown 렌더러.

표준 포맷은 docs/SPECIFICATION_MARKDOWN_FORMAT.md에 문서화되어 있고,
converters/markdown_to_spec.py가 이 포맷을 역파싱해서 SpecificationSchema로
되돌릴 수 있다 (완전히 임의의 마크다운이 아니라, 우리가 정의한 표준 포맷 기준).
"""
from __future__ import annotations

from typing import List, Optional

from agent.schemas import ComplianceRecord, RequirementSchema, SpecificationSchema, ValidationResult
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
