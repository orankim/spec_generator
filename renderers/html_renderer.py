"""
Specification JSON -> HTML 렌더러.

외부 CDN/웹폰트/JS 라이브러리를 전혀 사용하지 않는 완전 자체 완결형(self-contained)
HTML을 생성한다 (사내 폐쇄망에서 인터넷 연결 없이 그대로 열어볼 수 있어야 하므로).
markdown_renderer와 동일한 renderers/common.py의 섹션 모델을 사용하므로, 두 포맷의
필드 목록/순서가 어긋나지 않는다.
"""
from __future__ import annotations

import html as _html
from typing import Optional

from agent.schemas import RequirementSchema, SpecificationSchema, ValidationResult

from .common import RenderRow, RenderSection, build_notes_section, build_sections, build_validation_section

_STYLE = """
body { font-family: -apple-system, 'Segoe UI', '맑은 고딕', sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1a2530; background: #fff; }
h1 { border-bottom: 3px solid #2b6cb0; padding-bottom: 10px; }
h2 { margin-top: 40px; color: #2b6cb0; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }
th, td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; }
th { background: #f7fafc; }
td.unknown { color: #a0aec0; font-style: italic; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: bold; }
.badge-pass { background: #c6f6d5; color: #22543d; }
.badge-fail { background: #fed7d7; color: #822727; }
.badge-unknown, .badge-dash { background: #edf2f7; color: #718096; }
.badge-error { background: #fed7d7; color: #822727; }
.badge-warning { background: #feebc8; color: #7b341e; }
.badge-info { background: #bee3f8; color: #2a4365; }
.sources { font-size: 13px; color: #718096; margin-top: 6px; }
.sources div { margin: 2px 0; }
.note { color: #718096; font-style: italic; }
"""


def _esc(value: str) -> str:
    return _html.escape(str(value))


def _badge(text: str, cls: str) -> str:
    return f'<span class="badge badge-{cls}">{_esc(text)}</span>'


def _result_badge(result: Optional[str]) -> str:
    if result is None:
        return '<span class="badge badge-dash">-</span>'
    return _badge(result, result.lower())


def _cell(value: str) -> str:
    if value == "UNKNOWN":
        return '<td class="unknown">UNKNOWN</td>'
    return f"<td>{_esc(value)}</td>"


def _section_to_html(section: RenderSection) -> str:
    parts = [f"<h2>{_esc(section.title)}</h2>"]
    if section.note:
        parts.append(f'<p class="note">{_esc(section.note)}</p>')
    if not section.rows:
        if not section.note:
            parts.append('<p class="note">No data.</p>')
        return "\n".join(parts)

    has_requirement_col = any(r.requirement_display is not None or r.result is not None for r in section.rows)
    parts.append("<table>")
    if has_requirement_col:
        parts.append("<tr><th>Item</th><th>Unit</th><th>Requirement</th><th>Specification</th><th>Result</th></tr>")
        for row in section.rows:
            req = row.requirement_display if row.requirement_display is not None else "-"
            parts.append(
                "<tr>"
                f"<td>{_esc(row.label)}</td>"
                f"<td>{_esc(row.unit or '-')}</td>"
                f"<td>{_esc(req)}</td>"
                + _cell(row.value_display)
                + f"<td>{_result_badge(row.result)}</td>"
                "</tr>"
            )
    else:
        parts.append("<tr><th>Item</th><th>Specification</th></tr>")
        for row in section.rows:
            parts.append(f"<tr><td>{_esc(row.label)}</td>" + _cell(row.value_display) + "</tr>")
    parts.append("</table>")

    source_rows = [row for row in section.rows if row.source_type is not None]
    if source_rows:
        parts.append('<div class="sources">')
        for row in source_rows:
            parts.append(f"<div>Source: {_esc(row.source or row.source_type)} — {_esc(row.label)}</div>")
        parts.append("</div>")

    return "\n".join(parts)


def _validation_section_to_html(section: RenderSection) -> str:
    parts = [f"<h2>{_esc(section.title)}</h2>"]
    if section.note:
        parts.append(f'<p class="note">{_esc(section.note)}</p>')
    if not section.rows:
        return "\n".join(parts)
    parts.append("<table><tr><th>Level</th><th>Field</th><th>Message</th></tr>")
    for row in section.rows:
        level = row.label.split("]")[0].strip("[").lower() if row.label.startswith("[") else "info"
        field = row.label.split("]", 1)[-1].strip()
        parts.append(f"<tr><td>{_badge(level.upper(), level)}</td><td>{_esc(field)}</td>{_cell(row.value_display)}</tr>")
    parts.append("</table>")
    return "\n".join(parts)


def render_html(
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
    body_parts = [f"<h1>{_esc(title)}</h1>"]
    for key in order:
        body_parts.append(_section_to_html(by_id[key]))
    body_parts.append(_validation_section_to_html(build_validation_section(validation)))
    body_parts.append(_section_to_html(build_notes_section(specification)))

    body = "\n".join(body_parts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
{body}
</body>
</html>
"""
