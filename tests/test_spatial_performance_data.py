"""
Spatial Performance 데이터 보강 — sample_specs/SPEC-001~100 전체에 대한 구조/
값 형식 검증(요청서 13단계 Test A/B).

Test A: 100개 SPEC이 여전히 정상 Markdown으로 파싱되고, "## Spatial
        Performance" 절이 있는 파일은 agent.candidate_matcher가 실제로
        인식 가능한 항목명으로 채워져 있는지 확인한다.
Test B: 값 형식이 비정상(빈 문자열, 음수 Range/Resolution, 파싱 불가능한
        숫자 형식)이 아닌지 확인한다.
"""
from __future__ import annotations

import re
from glob import glob
from pathlib import Path

import pytest
from langchain_core.documents import Document

from agent.candidate_matcher import build_candidates
from agent.schemas import RequirementSchema

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATHS = sorted(glob(str(_REPO_ROOT / "sample_specs" / "SPEC-*.md")))

_SPATIAL_ITEMS = (
    "x_range_min", "y_range_min", "z_range_min",
    "x_resolution_value", "y_resolution_value", "z_resolution_value",
    "fov_display", "working_distance_value", "pixel_size_value",
)


def _build_fact(path: str):
    text = Path(path).read_text(encoding="utf-8")
    doc = Document(page_content=text, metadata={"filename": Path(path).name})
    candidates = build_candidates(RequirementSchema(), [doc])
    return candidates[0].equipment_fact if candidates else None, text


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_a_spec_parses_and_produces_a_candidate_fact(path):
    fact, _ = _build_fact(path)
    assert fact is not None, f"{path}에서 candidate_fact를 만들지 못했습니다"


def test_a_exactly_100_spec_files_exist():
    assert len(_SPEC_PATHS) == 100


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_b_range_fields_are_non_negative_and_ordered(path):
    fact, _ = _build_fact(path)
    for axis in ("x_range", "y_range", "z_range"):
        lo = getattr(fact, f"{axis}_min")
        hi = getattr(fact, f"{axis}_max")
        if lo is None and hi is None:
            continue
        assert lo is not None and hi is not None, f"{path}: {axis}가 min/max 중 한쪽만 채워짐"
        assert lo >= 0, f"{path}: {axis}_min이 음수({lo})"
        assert hi >= lo, f"{path}: {axis}_max({hi}) < {axis}_min({lo})"


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_b_resolution_and_pixel_size_are_positive(path):
    fact, _ = _build_fact(path)
    for field in ("x_resolution_value", "y_resolution_value", "z_resolution_value", "working_distance_value", "pixel_size_value"):
        value = getattr(fact, field)
        if value is None:
            continue
        assert value > 0, f"{path}: {field}가 0 이하({value})"


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_b_units_are_recognized_length_units(path):
    from agent.units import UnitError, unit_dimension

    fact, _ = _build_fact(path)
    for unit_field in ("x_range_unit", "y_range_unit", "z_range_unit", "x_resolution_unit", "y_resolution_unit", "z_resolution_unit", "working_distance_unit", "pixel_size_unit"):
        unit = getattr(fact, unit_field)
        if unit is None:
            continue
        assert unit != "", f"{path}: {unit_field}가 빈 문자열"
        try:
            assert unit_dimension(unit) == "length", f"{path}: {unit_field}={unit!r}가 length 단위가 아님"
        except UnitError:
            pytest.fail(f"{path}: {unit_field}={unit!r}를 agent.units가 인식하지 못합니다")


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_b_fov_display_is_non_empty_when_present(path):
    fact, _ = _build_fact(path)
    if fact.fov_display is not None:
        assert fact.fov_display.strip() != "", f"{path}: fov_display가 빈 문자열"


# ---------------------------------------------------------------------------
# 새로 추가된 "## Spatial Performance" 절 자체의 Markdown 형식 검증(원문 레벨).
# ---------------------------------------------------------------------------
_SPATIAL_SECTION_RE = re.compile(r"\n##\s*Spatial Performance\s*\n+(.+?)(?=\n##\s|\Z)", re.IGNORECASE | re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")
_KNOWN_LABELS = {"x range", "y range", "z range", "x resolution", "y resolution", "z resolution", "fov", "working distance", "pixel size", "xy resolution"}


@pytest.mark.parametrize("path", _SPEC_PATHS)
def test_a_spatial_performance_section_uses_recognized_item_labels(path):
    text = Path(path).read_text(encoding="utf-8")
    m = _SPATIAL_SECTION_RE.search(text)
    if not m:
        return
    rows_found = 0
    for line in m.group(1).splitlines():
        row = _TABLE_ROW_RE.match(line.strip())
        if not row or row.group(1).lower() == "item" or set(row.group(1)) <= {"-"}:
            continue
        label, value = row.group(1).strip(), row.group(2).strip()
        assert label.lower() in _KNOWN_LABELS, f"{path}: 인식할 수 없는 Spatial Performance 항목명 '{label}'"
        assert value != "", f"{path}: '{label}' 값이 빈 문자열"
        rows_found += 1
    assert rows_found > 0, f"{path}: ## Spatial Performance 절이 있지만 표 행이 없습니다"
