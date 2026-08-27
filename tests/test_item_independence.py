"""
검사 항목 독립성 및 최소 검출 결함 크기, 참고 문서 중복 제거 검증 단위 테스트.
"""
import unittest.mock as mock

import pytest
from agent.requirement_parser import parse_requirement_text, _extract_inspection_items_and_categories
from agent.candidate_matcher import build_candidates
from agent.schemas import RequirementSchema, RequirementValue, SourcedNumber, SourceRef
from renderers.common import _source_summary
from langchain_core.documents import Document


def _parse_with_empty_llm(user_text: str) -> RequirementSchema:
    """다른 회귀 테스트(tests/regression_lib.py)와 동일한 패턴: 이 환경에는 live
    Ollama 서버가 없으므로 LLM 파싱을 빈 응답으로 스텁하고 deterministic 추출
    계층만으로 검증한다(worst case — LLM이 실제로 채워주면 결과는 같거나 더 좋다)."""
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=RequirementSchema()):
        return parse_requirement_text(user_text)


def test_coating_thickness_vs_coating_non_uniformity():
    req1 = _parse_with_empty_llm("전극 코팅 두께를 측정할 수 있는 장비를 찾아줘.")
    assert "thickness" in req1.inspection_items
    assert "coating_non_uniformity" not in req1.inspection_items

    req2 = _parse_with_empty_llm("전극 코팅의 Coating Non-uniformity를 Inline으로 검사할 수 있는 장비를 찾아줘.")
    assert "coating_non_uniformity" in req2.inspection_items
    assert req2.inspection_items == ["coating_non_uniformity"]


def test_inspection_item_independence():
    # Edge Crack -> NOT surface_defect or edge_defect
    items_crack, cats_crack = _extract_inspection_items_and_categories("Edge Crack 검사기")
    assert "edge_crack" in items_crack
    assert "surface_defect" not in items_crack

    # Coating Defect -> NOT surface_defect
    items_cdef, cats_cdef = _extract_inspection_items_and_categories("Coating Defect 검사기")
    assert "coating_defect" in items_cdef
    assert "surface_defect" not in items_cdef

    # Void -> NOT surface_defect
    items_void, cats_void = _extract_inspection_items_and_categories("Void 검사기")
    assert "void" in items_void
    assert "surface_defect" not in items_void

    # Edge Defect -> NOT edge_crack
    items_edef, cats_edef = _extract_inspection_items_and_categories("Edge Defect 검사기")
    assert "edge_defect" in items_edef
    assert "edge_crack" not in items_edef


def test_minimum_detectable_defect_hard_requirement():
    req = RequirementSchema(
        minimum_defect_size=RequirementValue(value=3.0, unit="um", operator="<=")
    )
    
    doc_pass = Document(
        page_content="## General\n- Manufacturer: Test\n- Model: T-100\n\n## Defect Inspection\n| Minimum Detectable Defect | 2 μm |\n| Defect Types | Scratch |",
        metadata={"source": "TEST-001.md"}
    )
    candidates_pass = build_candidates(req, [doc_pass])
    assert len(candidates_pass) == 1
    match_pass = next(m for m in candidates_pass[0].matches if m.field_key == "minimum_defect_size")
    assert match_pass.result == "PASS"
    assert match_pass.found_value == 2.0  # Document value extracted, NOT user's 3.0

    doc_fail = Document(
        page_content="## General\n- Manufacturer: Test\n- Model: T-200\n\n## Defect Inspection\n| Minimum Detectable Defect | 5 μm |\n| Defect Types | Scratch |",
        metadata={"source": "TEST-002.md"}
    )
    candidates_fail = build_candidates(req, [doc_fail])
    assert len(candidates_fail) == 1
    match_fail = next(m for m in candidates_fail[0].matches if m.field_key == "minimum_defect_size")
    assert match_fail.result == "FAIL"
    assert match_fail.found_value == 5.0


def test_source_summary_deduplication():
    sn_dupe = SourcedNumber(
        value=1.0,
        unit="um",
        status="VERIFIED",
        source=SourceRef(document="SPEC-013.md", section="SPEC-013.md > Equipment Specification")
    )
    summary = _source_summary(sn_dupe)
    assert summary == "SPEC-013.md, Equipment Specification"
