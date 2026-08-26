"""
회귀 테스트: SPEC-001~050 corpus 기반 테스트에서 발견된 5개 문제에 대한 수정을
검증한다.

문제1: 후보 장비의 Width/Speed 등이 문서에 실제로 존재하는데도 초기 top-k 검색이
       해당 chunk를 놓쳐 UNKNOWN으로 잘못 판정되던 문제(예: SPEC-013 Width,
       SPEC-039 Speed) — RAG 검색은 "후보 선정"까지만 담당하고, 후보로 확정되면
       agent.spec_retriever가 그 문서 전체(모든 chunk)를 deterministic field
       extraction에 넘긴다.
문제2: "스크래치와 오염" 같은 세부 결함 이름이 상위 카테고리(surface_defect)
       하나로 뭉개지던 문제 — 세부 canonical item을 그대로 유지하고 상위
       카테고리는 검색 확장 전용 inspection_categories로만 보낸다.
문제3: "3D Profile 검사기를 찾아줘"처럼 다른 항목이 명시된 문장에서도 thickness가
       근거 없이 끼어들던 문제.
문제4: "3 μm 이하 크기의 스크래치"처럼 "결함"이라는 단어 없이 표현된 최소 검출
       결함 크기를 놓치던 문제.
문제5: PASS/PARTIAL/FAIL 3단계 우선순위 — PARTIAL 후보가 FAIL 후보보다 항상
       우선해야 하는데 tie-break이 이를 보장하지 못하던 문제.
"""
import hashlib
import shutil
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document

from agent import spec_retriever
from agent.candidate_matcher import build_candidates, select_best_candidate
from agent.requirement_parser import parse_requirement_text
from agent.schemas import CandidateEquipment, CandidateFieldMatch, RequirementSchema, RequirementTarget
from build_rag_ollama import build_vector_db

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_DB = "./_test_chroma_db_hard_requirement_pipeline_fixes"


def _fake_vector(text: str, dim: int = 32):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    arr = np.frombuffer((h * (dim // len(h) + 1))[: dim * 4], dtype=np.uint32).astype(np.float64)
    return (arr / arr.max()).tolist()


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with mock.patch.object(OllamaEmbeddings, "embed_documents", lambda self, texts: [_fake_vector(t) for t in texts]), \
         mock.patch.object(OllamaEmbeddings, "embed_query", lambda self, text: _fake_vector(text)):
        yield


@pytest.fixture(scope="module")
def db(fake_embeddings):
    shutil.rmtree(_TEST_DB, ignore_errors=True)
    build_vector_db("sample_specs", _TEST_DB, rebuild=True)
    yield _TEST_DB
    shutil.rmtree(_TEST_DB, ignore_errors=True)


def _parse_with_empty_llm(user_text: str) -> RequirementSchema:
    """LLM이 아무것도 채우지 못했다고 가정(worst case) — deterministic 계층만으로
    올바른 결과가 나오는지 가장 엄격하게 검증한다."""
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=RequirementSchema()):
        return parse_requirement_text(user_text)


# ---------------------------------------------------------------
# 문제1: 초기 top-k에서 밀려난 chunk 때문에 실제로 문서에 있는 Width/Speed가
# UNKNOWN으로 잘못 판정되던 문제. k_per_query를 일부러 작게(1) 둬서 원래
# 버그가 재현되던 조건을 그대로 재현하고, 후보로 일단 확정되면 전체 문서를
# 읽어와 값을 찾아내는지 확인한다.
# ---------------------------------------------------------------
def test_reported_bug_spec013_width_not_unknown_despite_narrow_top_k(db):
    requirement = RequirementSchema(
        raw_text="폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, 0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘.",
        target=RequirementTarget(width_mm=800.0),
        inline_offline="inline",
        inspection_items=["thickness"],
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=1)
    candidates = build_candidates(requirement, docs)
    spec013 = next((c for c in candidates if c.source_document == "SPEC-013.md"), None)
    assert spec013 is not None, "SPEC-013.md가 후보로 확정되지 않았습니다(전제 실패)"

    by_item = {m.item: m for m in spec013.matches}
    assert by_item["Width"].result == "PASS", "SPEC-013은 실제로 Maximum Electrode Width: 1200 mm를 명시하므로 UNKNOWN이 아니라 PASS여야 한다"
    assert by_item["Width"].found_value == 1200.0


def test_reported_bug_spec039_speed_not_unknown_despite_narrow_top_k(db):
    requirement = RequirementSchema(
        raw_text="폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘.",
        target=RequirementTarget(width_mm=1000.0),
        inline_offline="inline",
        inspection_items=["profile_3d"],
        measurement_speed=None,
    )
    from agent.schemas import RequirementValue

    requirement.measurement_speed = RequirementValue(value=500.0, unit="mm/s", operator=">=")
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=1)
    candidates = build_candidates(requirement, docs)
    spec039 = next((c for c in candidates if c.source_document == "SPEC-039.md"), None)
    assert spec039 is not None, "SPEC-039.md가 후보로 확정되지 않았습니다(전제 실패)"

    by_item = {m.item: m for m in spec039.matches}
    assert by_item["Speed"].result == "PASS", "SPEC-039는 실제로 Measurement Speed: 700 mm/s를 명시하므로 UNKNOWN이 아니라 PASS여야 한다"
    assert by_item["Speed"].found_value == 700.0


# ---------------------------------------------------------------
# 문제2: "스크래치와 오염" -> ["scratch", "contamination"] (surface_defect로
# 뭉개지 않음), 상위 카테고리는 inspection_categories에만.
# ---------------------------------------------------------------
def test_reported_bug_fine_grained_defect_items_not_collapsed_to_category():
    requirement = _parse_with_empty_llm(
        "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘."
    )
    assert set(requirement.inspection_items) == {"scratch", "contamination"}
    assert "surface_defect" not in requirement.inspection_items
    assert "surface_defect" in requirement.inspection_categories


def test_fine_grained_items_are_verified_independently_not_via_shared_category(db):
    """VI-1000(SPEC-021.md)은 스크래치/오염/파티클/핀홀을 모두 지원하지만,
    다른 장비는 일부만 지원할 수 있다 — 요구 항목이 여러 개면 각각 독립적으로
    PASS/FAIL이 매겨져야 한다(하나만 지원해도 전체가 PASS로 뭉개지면 안 됨)."""
    requirement = RequirementSchema(
        target=RequirementTarget(width_mm=800.0),
        inline_offline="inline",
        inspection_items=["scratch", "contamination"],
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=100)
    candidates = build_candidates(requirement, docs)
    vi1000 = next(c for c in candidates if c.source_document == "SPEC-021.md")
    by_item = {m.item: m for m in vi1000.matches}
    assert by_item["Scratch Detection"].result == "PASS"
    assert by_item["Contamination Detection"].result == "PASS"

    # SPEC-010(MultiSense MS-600)은 Defect Types에 Scratch는 있지만 Contamination은 없다
    # (Scratch, Crack, Particle, Coating Defect) — 두 항목이 독립적으로 판정되는지 확인.
    ms600 = next(c for c in candidates if c.source_document == "SPEC-010.md")
    by_item_ms600 = {m.item: m for m in ms600.matches}
    assert by_item_ms600["Scratch Detection"].result == "PASS"
    assert by_item_ms600["Contamination Detection"].result == "FAIL"


# ---------------------------------------------------------------
# 문제3: "3D Profile 검사기를 찾아줘"(두께 언급 없음)에서 thickness가 근거 없이
# 끼어들면 안 된다.
# ---------------------------------------------------------------
def test_reported_bug_profile_3d_query_does_not_hallucinate_thickness():
    requirement = _parse_with_empty_llm(
        "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘."
    )
    assert requirement.inspection_items == ["profile_3d"]
    assert "thickness" not in requirement.inspection_items


def test_thickness_llm_guess_still_trusted_when_no_contrary_evidence():
    """기존 정책(회귀 방지): raw_text에 리터럴 "두께" 키워드가 없어도, LLM이
    이미 thickness를 채웠고(예: "0~200 μm ... 정확도가 필요한 전극 검사기를
    찾아줘."처럼 항목을 특정하진 않았지만 두께 측정 문맥이 있는 경우) 텍스트에
    다른 항목을 가리키는 증거가 전혀 없다면 그 thickness 추정은 계속 신뢰해야
    한다. (주의: 이는 "아무 근거 없이 thickness를 지어내는 것"과 다르다 — LLM이
    빈 응답을 낸 진짜 모호한 질문에서는 thickness를 발명해서는 안 된다는
    정책이 test_integration_verification.py::test_7_ambiguous_query_does_not_invent_values
    로 이미 확립돼 있다.)"""
    user_text = "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."
    llm_guess = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_guess):
        requirement = parse_requirement_text(user_text)
    assert "thickness" in requirement.inspection_items


def test_ambiguous_query_with_no_llm_guess_does_not_invent_thickness():
    """test_7_ambiguous_query_does_not_invent_values와 동일한 정책을 이 파일
    안에서도 회귀 방지: LLM이 아무 것도 채우지 못했고 raw_text에도 어떤 항목의
    증거가 없다면 thickness를 포함한 그 어떤 inspection_item도 지어내면
    안 된다."""
    requirement = _parse_with_empty_llm("0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.")
    assert requirement.inspection_items == []


# ---------------------------------------------------------------
# 문제4: "3 μm 이하 크기의 스크래치"처럼 "결함"이라는 단어 없이 표현된 최소
# 검출 결함 크기.
# ---------------------------------------------------------------
def test_reported_bug_min_defect_size_extracted_without_literal_defect_word():
    requirement = _parse_with_empty_llm(
        "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘."
    )
    assert requirement.minimum_defect_size is not None
    assert requirement.minimum_defect_size.value == 3.0
    assert requirement.minimum_defect_size.unit == "um"
    assert requirement.minimum_defect_size.operator == "<="
    assert requirement.minimum_defect_size_um == 3.0


# ---------------------------------------------------------------
# 문제5: PASS > PARTIAL > FAIL 3단계 우선순위 — PARTIAL이 FAIL보다 항상 우선.
# ---------------------------------------------------------------
def _mk_candidate(source: str, status: str, pass_count: int, unknown_count: int, fail_count: int) -> CandidateEquipment:
    return CandidateEquipment(
        candidate_id=source,
        source_document=source,
        matches=[],
        hard_requirements_pass=(status == "PASS"),
        pass_count=pass_count,
        unknown_count=unknown_count,
        fail_count=fail_count,
        status=status,
    )


def test_partial_always_ranked_above_fail_even_with_fewer_passes():
    """PARTIAL 후보(fail=0, unknown>0)가 FAIL 후보(fail>0)보다 pass_count가
    낮아도 항상 먼저 추천되어야 한다 — 예전 tie-break((-pass_count, fail_count))은
    이를 보장하지 못했다(pass_count가 더 높은 FAIL 후보가 앞설 수 있었음)."""
    partial = _mk_candidate("PARTIAL.md", "PARTIAL", pass_count=2, unknown_count=1, fail_count=0)
    fail_with_more_passes = _mk_candidate("FAIL.md", "FAIL", pass_count=5, unknown_count=0, fail_count=1)
    best = select_best_candidate([fail_with_more_passes, partial])
    assert best.source_document == "PARTIAL.md"


def test_pass_always_ranked_above_partial():
    pass_candidate = _mk_candidate("PASS.md", "PASS", pass_count=1, unknown_count=0, fail_count=0)
    partial_candidate = _mk_candidate("PARTIAL.md", "PARTIAL", pass_count=10, unknown_count=1, fail_count=0)
    best = select_best_candidate([partial_candidate, pass_candidate])
    assert best.source_document == "PASS.md"


def test_status_field_computed_correctly_in_build_candidates():
    requirement = RequirementSchema(target=RequirementTarget(width_mm=100.0))
    pass_doc = Document(
        page_content="## Inspection Target\n\n- Maximum Electrode Width: 500 mm\n",
        metadata={"filename": "PASS-DOC.md", "source": "PASS-DOC.md", "source_type": "markdown", "chunk_id": 0},
    )
    unknown_doc = Document(
        page_content="## General\n\n- Manufacturer: X\n",
        metadata={"filename": "UNKNOWN-DOC.md", "source": "UNKNOWN-DOC.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [pass_doc, unknown_doc])
    by_source = {c.source_document: c for c in candidates}
    assert by_source["PASS-DOC.md"].status == "PASS"
    assert by_source["UNKNOWN-DOC.md"].status == "PARTIAL"


def test_select_best_candidate_empty_list_returns_none():
    assert select_best_candidate([]) is None
