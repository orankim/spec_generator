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


def test_surface_defect_boost_keyword_entry_is_union_of_subtypes():
    """Final Combined Validation(56케이스 전체 real Ollama 재확인) 결과로 Production에
    적용된 변경 — surface_defect(상위 카테고리)는 이미 정의된 세부 하위 타입 키워드의
    합집합을 그대로 쓴다(새 키워드를 만들지 않음, QA023 하드코딩 아님 — 일반 정책).
    이 테스트가 실패하면(예: 누군가 이 매핑을 되돌리면) Retrieval Recall이 다시
    97.7%로 떨어질 수 있다는 신호다."""
    subtype_keys = ("scratch", "contamination", "particle", "pinhole", "void", "coating_non_uniformity", "edge_crack")
    expected = tuple(kw for key in subtype_keys for kw in spec_retriever._ITEM_BOOST_KEYWORDS[key])
    assert spec_retriever._ITEM_BOOST_KEYWORDS["surface_defect"] == expected


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


# ---------------------------------------------------------------------------
# 일반 정책 회귀 테스트(QA023 전용 아님) — surface_defect(상위 카테고리) 질의가
# "이미 정의된 세부 하위 타입 키워드"를 실제로 활용하는지, 그리고 기존 하위 타입
# 단독 질의(scratch/crack/particle/contamination)의 동작이 그대로 유지되는지를
# synthetic in-memory vector store로 검증한다. 실제 ChromaDB/Ollama 불필요.
# ---------------------------------------------------------------------------
class _FakeVectorStore:
    """SimpleChromaStore.get()의 최소 인터페이스만 흉내낸다 — 임베딩/DB 연결 없음."""

    def __init__(self, docs: dict):
        # docs: {filename: content}
        self._docs = docs

    def get(self, include=None, where=None):
        return {
            "documents": list(self._docs.values()),
            "metadatas": [{"filename": fn} for fn in self._docs],
        }


def _boost_sources(requirement, docs: dict):
    from agent.schemas import RequirementSchema

    vs = _FakeVectorStore(docs)
    req = RequirementSchema(inspection_items=requirement)
    return {spec_retriever.source_label(d) for d in spec_retriever._inspection_item_boost_docs(req, vs)}


def test_surface_defect_boost_finds_doc_mentioning_only_a_subtype_keyword():
    """일반 정책 검증: 문서가 상위 카테고리 단어("surface defect")를 전혀 쓰지 않고
    세부 결함 이름("Scratch")만 언급해도, inspection_items=['surface_defect']로
    질의하면 boost가 그 문서를 찾아야 한다 — QA023/SPEC-009와 무관한 합성 문서."""
    docs = {
        "SPEC-FAKE-1.md": "Equipment Type: Generic Inspector\nDefect Types: Large Scratch",
        "SPEC-FAKE-2.md": "Equipment Type: Thickness Gauge\nNo defect detection capability.",
    }
    sources = _boost_sources(["surface_defect"], docs)
    assert sources == {"SPEC-FAKE-1.md"}


def test_surface_defect_boost_does_not_match_unrelated_document():
    """관련 없는 문서(결함 키워드 전혀 없음)는 boost되지 않아야 한다(과도한 매칭 방지)."""
    docs = {"SPEC-FAKE-3.md": "Equipment Type: Speed Sensor\nMeasures line speed only."}
    sources = _boost_sources(["surface_defect"], docs)
    assert sources == set()


def test_existing_subtype_only_query_behavior_unchanged():
    """기존 세부 결함 단독 질의(scratch/crack/particle/contamination)가 surface_defect
    추가 이후에도 예전과 동일하게 동작하는지(회귀 없음) 확인한다."""
    docs = {
        "SPEC-FAKE-4.md": "Defect Types: Particle, Contamination",
        "SPEC-FAKE-5.md": "Defect Types: Large Scratch",
    }
    assert _boost_sources(["particle"], docs) == {"SPEC-FAKE-4.md"}
    assert _boost_sources(["contamination"], docs) == {"SPEC-FAKE-4.md"}
    assert _boost_sources(["scratch"], docs) == {"SPEC-FAKE-5.md"}
