"""
Specification JSON -> Markdown 렌더러.

표준 포맷은 docs/SPECIFICATION_MARKDOWN_FORMAT.md에 문서화되어 있고,
converters/markdown_to_spec.py가 이 포맷을 역파싱해서 SpecificationSchema로
되돌릴 수 있다 (완전히 임의의 마크다운이 아니라, 우리가 정의한 표준 포맷 기준).
"""
from __future__ import annotations

from typing import Optional

from agent.schemas import RequirementSchema, SpecificationSchema, ValidationResult

from .common import RenderRow, RenderSection, build_notes_section, build_sections, build_validation_section


def _row_to_md_table_row(row: RenderRow, has_requirement_col: bool) -> str:
    if has_requirement_col:
        req = row.requirement_display if row.requirement_display is not None else "-"
        result = row.result if row.result is not None else "-"
        unit = row.unit or "-"
        return f"| {row.label} | {unit} | {req} | {row.value_display} | {result} |"
    return f"| {row.label} | {row.value_display} |"


def _section_to_md(section: RenderSection) -> str:
    lines = [f"## {section.title}", ""]
    if section.note:
        lines.append(f"_{section.note}_")
        lines.append("")
    if not section.rows:
        if not section.note:
            lines.append("_No data._")
            lines.append("")
        return "\n".join(lines)

    has_requirement_col = any(r.requirement_display is not None or r.result is not None for r in section.rows)
    if has_requirement_col:
        lines.append("| Item | Unit | Requirement | Specification | Result |")
        lines.append("|---|---|---|---|---|")
    else:
        lines.append("| Item | Specification |")
        lines.append("|---|---|")
    for row in section.rows:
        lines.append(_row_to_md_table_row(row, has_requirement_col))

    # Source 정보는 표 대신 표 아래 blockquote로 보존한다 (표준 포맷 예시와 동일)
    source_lines = [
        f"> Source: {row.source or row.source_type} — {row.label}"
        for row in section.rows
        if row.source_type is not None
    ]
    if source_lines:
        lines.append("")
        lines.extend(source_lines)

    lines.append("")
    return "\n".join(lines)


def render_markdown(
    specification: SpecificationSchema,
    requirement: Optional[RequirementSchema] = None,
    validation: Optional[ValidationResult] = None,
    title: str = "Electrode Inspection Equipment Specification",
) -> str:
    sections = build_sections(specification, requirement=requirement)
    by_id = {s.id: s for s in sections}
    order = [
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
    ordered = [by_id[key] for key in order]

    parts = [f"# {title}", ""]
    for section in ordered:
        parts.append(_section_to_md(section))
    parts.append(_section_to_md(build_validation_section(validation)))
    parts.append(_section_to_md(build_notes_section(specification)))

    return "\n".join(parts).rstrip() + "\n"
