"""
Candidate Fact Extraction 전용 테스트 — agent.candidate_matcher._extract_candidate_fact가
sample_specs/*.md 실제 원문에서 값을 정확히 뽑아내는지, RAG 검색을 거치지 않고
파일을 직접 읽어 검증한다(빠르고 RAG 노이즈가 없다). Ground Truth 값은
tests/ground_truth_data.py(SPEC-011~050 생성 근거)와 sample_specs/*.md 원문을
직접 대조해 확인했다.

실행:
    pytest tests/test_candidate_extraction.py -v
    pytest -m candidate -v
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from agent.candidate_matcher import _extract_candidate_fact

pytestmark = pytest.mark.candidate

_SAMPLE_SPECS_DIR = Path(__file__).resolve().parent.parent / "sample_specs"


def _load_fact(spec_id: str):
    text = (_SAMPLE_SPECS_DIR / f"{spec_id}.md").read_text(encoding="utf-8")
    doc = Document(page_content=text, metadata={"filename": f"{spec_id}.md"})
    return _extract_candidate_fact([doc])


# ---------------------------------------------------------------
# 문제1 회귀 방지: Width/Speed가 실제 문서에 있는데 UNKNOWN으로 추출되던 문제.
# ---------------------------------------------------------------
def test_spec013_width_and_speed_extracted():
    fact = _load_fact("SPEC-013")
    assert fact.manufacturer == "ThicknessPro"
    assert fact.model == "TP-800"
    assert fact.width_mm == 1200.0
    assert fact.speed == (800.0, "mm/s")
    assert fact.range == (0.0, 800.0, "um")
    assert fact.accuracy == (0.8, "um")


def test_spec039_speed_extracted():
    fact = _load_fact("SPEC-039")
    assert fact.manufacturer == "ProfileScan"
    assert fact.model == "PS-1000"
    assert fact.width_mm == 1000.0
    assert fact.speed == (700.0, "mm/s")


# ---------------------------------------------------------------
# 문제3 회귀 방지: Equipment Type/Notes에 명시적 근거가 있는지 여부를 정확히
# 추출하는지 확인한다(PASS/FAIL 판정 자체는 candidate_matcher.build_candidates가
# 하므로, 여기서는 그 판정의 입력이 되는 "원문 사실"만 검증한다).
# ---------------------------------------------------------------
def test_spec013_equipment_type_mentions_thickness():
    fact = _load_fact("SPEC-013")
    assert "thickness" in (fact.equipment_type_text or "").lower()


def test_spec009_3d_profile_device_equipment_type_does_not_mention_thickness():
    """SPEC-009(FastScan FS-1000)는 3D Profile 전용 장비이므로 Equipment Type/Notes
    어디에도 "thickness"가 없어야 한다 — 있으면 Measurement Range (Z)만으로
    두께 측정 지원을 오판하던 예전 버그가 되살아난 것이다."""
    fact = _load_fact("SPEC-009")
    assert "thickness" not in (fact.equipment_type_text or "").lower()
    assert "thickness" not in (fact.notes_text or "").lower()
    assert fact.range is not None  # Measurement Range (Z) 자체는 존재함(그래서 착각하기 쉬웠다)


def test_spec001_notes_mentions_thickness_explicitly():
    """SPEC-001(OptiScan ES-200)은 Notes에 "thickness"가 명시적으로 있는
    corpus 유일의 '두께+표면결함 겸용' 실제 근거 사례."""
    fact = _load_fact("SPEC-001")
    assert "thickness" in (fact.notes_text or "").lower()


# ---------------------------------------------------------------
# Defect Types 원문 추출 검증(문제2의 입력 데이터).
# ---------------------------------------------------------------
def test_spec021_defect_types_include_scratch_and_contamination():
    fact = _load_fact("SPEC-021")
    assert fact.width_mm == 1000.0
    assert fact.defect_size == (3.0, "um")
    text = (fact.defect_types_text or "").lower()
    assert "scratch" in text
    assert "contamination" in text


def test_spec010_defect_types_include_scratch_but_not_contamination():
    """MultiSense MS-600은 Scratch는 지원하지만 Contamination은 없다 —
    surface_defect 하나로 뭉개면 이 차이를 검증할 수 없다(문제2)."""
    fact = _load_fact("SPEC-010")
    text = (fact.defect_types_text or "").lower()
    assert "scratch" in text
    assert "contamination" not in text


# ---------------------------------------------------------------
# 그 외 필드(Not Supported 표기, Manufacturer/Model) 추출.
# ---------------------------------------------------------------
def test_spec011_thickness_family_defect_inspection_not_supported():
    fact = _load_fact("SPEC-011")
    assert fact.defect_inspection_not_supported is True


def test_spec006_thickness_not_supported_flag_extracted():
    """SPEC-006은 '## Thickness Measurement\\n\\n- Not Supported'로 명시적으로
    두께 측정을 지원하지 않는다고 밝힌다 — Equipment Type/Notes에 다른 두께
    근거가 있어도 이 명시적 반증이 항상 이겨야 한다(candidate_matcher가
    thickness_not_supported를 최우선으로 확인하는 이유)."""
    fact = _load_fact("SPEC-006")
    assert fact.thickness_not_supported is True


@pytest.mark.parametrize(
    "spec_id,expected_manufacturer,expected_model",
    [
        ("SPEC-021", "VisionInspect", "VI-1000"),
        ("SPEC-036", "VoidScan", "VS-800"),
        ("SPEC-035", "FilmInspect", "FI-500"),
        ("SPEC-027", "EdgeVision", "EV-600"),
    ],
)
def test_manufacturer_and_model_extracted(spec_id, expected_manufacturer, expected_model):
    fact = _load_fact(spec_id)
    assert fact.manufacturer == expected_manufacturer
    assert fact.model == expected_model
