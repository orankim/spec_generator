"""
QA023 Root Cause 분석의 구조적 사실(코드에 실제로 있는 값)을 회귀 가드로 고정한다.
Ollama 호출 없음 — production 모듈의 딕셔너리/함수 존재 여부와, 로컬 SPEC 파일
텍스트만 확인한다(임베딩/LLM 호출 전혀 없음).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import categorical_match, spec_retriever  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_surface_defect_has_no_item_boost_keyword_entry():
    """Root Cause의 핵심 사실 — 이 회귀 가드가 실패하면(누군가 surface_defect 항목을
    _ITEM_BOOST_KEYWORDS에 추가하면) QA023 분석 리포트의 전제가 바뀐 것이므로
    재분석이 필요하다는 신호다."""
    assert spec_retriever._ITEM_BOOST_KEYWORDS.get("surface_defect") is None


def test_surface_defect_has_no_capability_keyword_entry():
    assert categorical_match.INSPECTION_ITEM_CAPABILITY_KEYWORDS.get("surface_defect") is None


def test_item_boost_keywords_has_all_expected_subtype_entries():
    """Strategy C 시뮬레이션이 참조하는 하위 타입 키가 실제로 존재하는지(재구현 없이
    그대로 재사용 가능한지) 확인한다."""
    for key in ("scratch", "contamination", "particle", "pinhole", "void", "coating_non_uniformity", "edge_crack"):
        assert key in spec_retriever._ITEM_BOOST_KEYWORDS
        assert len(spec_retriever._ITEM_BOOST_KEYWORDS[key]) > 0


def test_spec009_content_contains_scratch_and_crack_keywords():
    text = (_REPO_ROOT / "sample_specs" / "SPEC-009.md").read_text(encoding="utf-8").lower()
    assert "scratch" in text
    assert "crack" in text
    # "edge crack"(공백 포함 정확 문구)은 없다 — 실제 문서 표현은 "Edge Defect"이지 "Edge Crack"이 아님.
    assert "edge crack" not in text


def test_spec009_equipment_type_is_3d_profile_oriented():
    """SPEC-009가 profile_3d 계열로 분류될 근거가 있는지(surface_defect 어휘와
    거리가 있다는 Root Cause 설명의 근거) 확인한다."""
    text = (_REPO_ROOT / "sample_specs" / "SPEC-009.md").read_text(encoding="utf-8").lower()
    assert "3d" in text or "profilometry" in text


def test_item_query_hint_for_surface_defect_matches_cached_expanded_query():
    """_ITEM_QUERY_HINTS의 값이 실제 QA023 캐시에 기록된 확장 질의와 일치하는지
    (QA023 분석의 Step A/B 전제가 되는 문자열이 코드와 캐시 양쪽에서 같은지)."""
    assert spec_retriever._ITEM_QUERY_HINTS["surface_defect"] == "표면 결함 검출 이물 크랙 핀홀"


def test_build_queries_generates_expected_two_queries_for_surface_defect_only():
    """QA023처럼 inspection_items=['surface_defect']뿐이고 다른 구조화 필드가 없는
    RequirementSchema에 대해 _build_queries()가 실제로 몇 개의 질의를 만드는지
    (production 함수를 그대로 호출 — 재구현 아님)."""
    from agent.schemas import RequirementSchema

    req = RequirementSchema(raw_text="표면 결함 검사기를 찾아줘. 폭 조건은 따로 없어.", inspection_items=["surface_defect"])
    queries = spec_retriever._build_queries(req)
    assert queries == ["표면 결함 검출 이물 크랙 핀홀", "표면 결함 검사기를 찾아줘. 폭 조건은 따로 없어."]
