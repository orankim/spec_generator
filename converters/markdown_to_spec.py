"""
표준 Specification Markdown(docs/SPECIFICATION_MARKDOWN_FORMAT.md, 즉
renderers/markdown_renderer.render_markdown()가 만드는 포맷) -> SpecificationSchema.

임의의 마크다운을 일반적으로 파싱하려고 하지 않는다. 오직 우리가 정의한 표준
포맷(라벨-필드 매핑은 renderers/common.py의 build_sections()가 유일한 소스)만
대상으로 한다. 표준 포맷이 아닌 라벨/구조는 조용히 무시한다(에러 없이 건너뜀).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from agent.schemas import SourcedNumber, SpecificationSchema

from renderers.common import build_notes_section, build_sections

_KNOWN_SOURCE_TYPES = {"user_requirement", "inferred", "default", "document"}

# 한 행(row)에 값 하나가 콤마로 join된 리스트 필드 (예: "핀홀, 크랙")
_LIST_PATHS = {
    "inspection_items",
    "defect_detection.defect_types",
    "interfaces.other_interfaces",
    "needs_confirmation",
    "sources",
}

# notes/assumptions는 항목마다 별도 행("Note" 라벨이 여러 번 반복)으로 렌더링되므로
# 콤마 분리가 아니라 "행마다 리스트에 추가"로 파싱해야 한다 (renderers/common.py의
# build_notes_section 참고).
_APPEND_LIST_PATHS = {"notes", "assumptions"}

_BOOL_PATHS = {
    "interfaces.ethernet",
    "interfaces.digital_io",
    "interfaces.plc",
    "interfaces.mes",
    "interfaces.opc_ua",
    "safety.interlock",
    "safety.emergency_stop",
}

# 일반(non-SourcedNumber) 필드 중 숫자 타입인 것들 - 문자열로 잘못 세팅되지 않도록 별도 처리
_FLOAT_PLAIN_PATHS = {
    "inspection_target.width_mm",
    "inspection_target.length_mm",
    "inspection_target.thickness_um",
}


def _label_to_path_map() -> Dict[str, str]:
    """빈 SpecificationSchema로 build_sections()를 한 번 돌려 라벨->필드경로 맵을 얻는다."""
    mapping: Dict[str, str] = {}
    blank = SpecificationSchema()
    for section in build_sections(blank):
        for row in section.rows:
            if row.field_path:
                mapping[row.label] = row.field_path
    # build_notes_section은 리스트가 비어 있으면 행 자체를 만들지 않으므로(데이터
    # 기반 생성), 빈 스펙으로는 "Note"/"Assumption" 등의 라벨을 얻을 수 없다.
    # 이 4개는 renderers/common.py build_notes_section()의 라벨과 정확히 일치해야 한다.
    mapping.setdefault("Note", "notes")
    mapping.setdefault("Assumption", "assumptions")
    mapping.setdefault("Needs Confirmation", "needs_confirmation")
    mapping.setdefault("Sources", "sources")
    return mapping


def _parse_tables(markdown_text: str) -> List[Dict[str, Any]]:
    """마크다운을 '## 헤더' 단위 블록으로 나누고, 각 블록의 파이프 테이블을 파싱한다."""
    blocks = []
    current_header = None
    current_lines: List[str] = []

    def flush():
        if current_header is not None:
            blocks.append({"header": current_header, "lines": current_lines[:]})

    for line in markdown_text.splitlines():
        if line.startswith("## "):
            flush()
            current_header = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()

    parsed = []
    for block in blocks:
        table_lines = [l for l in block["lines"] if l.strip().startswith("|")]
        if len(table_lines) < 2:
            parsed.append({"header": block["header"], "columns": [], "rows": []})
            continue
        header_cols = [c.strip() for c in table_lines[0].strip("|").split("|")]
        data_rows = []
        for line in table_lines[2:]:  # [0]=헤더, [1]=구분선(---)
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == len(header_cols):
                data_rows.append(cells)
        sources = {}
        for line in block["lines"]:
            m = re.match(r"^>\s*Source:\s*(.+?)\s*—\s*(.+)$", line.strip())
            if m:
                sources[m.group(2).strip()] = m.group(1).strip()
        parsed.append({"header": block["header"], "columns": header_cols, "rows": data_rows, "sources": sources})
    return parsed


def _set_by_path(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    target = obj
    for p in parts[:-1]:
        target = getattr(target, p)
    setattr(target, parts[-1], value)


def _parse_list(text: str) -> List[str]:
    if text == "UNKNOWN" or not text:
        return []
    return [v.strip() for v in text.split(",") if v.strip()]


def _parse_bool(text: str) -> Optional[bool]:
    if text == "지원":
        return True
    if text == "미지원":
        return False
    return None


def _parse_float(text: str) -> Optional[float]:
    if text == "UNKNOWN" or not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def markdown_to_spec(markdown_text: str) -> SpecificationSchema:
    label_to_path = _label_to_path_map()
    spec = SpecificationSchema()

    for block in _parse_tables(markdown_text):
        columns = block["columns"]
        if not columns:
            continue
        has_requirement_col = columns == ["Item", "Unit", "Requirement", "Specification", "Result"]

        for row_cells in block["rows"]:
            label = row_cells[0]
            path = label_to_path.get(label)
            if not path:
                continue  # 표준 포맷에 없는 행은 조용히 건너뜀

            # "Defect Inspection" 같은 섹션은 SourcedNumber 필드와 plain 필드(예:
            # Defect Types)가 같은 5열 표를 공유하므로, 표 모양이 아니라 필드
            # 종류(path)로 파싱 방식을 결정한다. "Specification" 열 위치는 표
            # 모양에 따라 다르므로(5열이면 인덱스 3, 2열이면 인덱스 1) 먼저 통일한다.
            value_text = row_cells[3] if has_requirement_col else row_cells[1]

            if path in _APPEND_LIST_PATHS:
                if value_text != "UNKNOWN" and value_text:
                    current = list(getattr(spec, path))
                    current.append(value_text)
                    _set_by_path(spec, path, current)
                continue

            if path in _LIST_PATHS:
                _set_by_path(spec, path, _parse_list(value_text))
                continue

            if path in _BOOL_PATHS:
                _set_by_path(spec, path, _parse_bool(value_text))
                continue

            if path in _FLOAT_PLAIN_PATHS:
                _set_by_path(spec, path, _parse_float(value_text))
                continue

            if has_requirement_col:
                unit_text = row_cells[1]
                value = _parse_float(value_text)
                source_type = None
                source = None
                source_text = block["sources"].get(label)
                if source_text:
                    if source_text in _KNOWN_SOURCE_TYPES:
                        source_type = source_text
                    else:
                        source_type = "document"
                        source = source_text
                sourced = SourcedNumber(
                    value=value,
                    unit=(unit_text if unit_text != "-" else None),
                    source_type=source_type,
                    source=source,
                )
                _set_by_path(spec, path, sourced if value is not None else None)
            else:
                _set_by_path(spec, path, None if value_text == "UNKNOWN" else value_text)

    return spec
