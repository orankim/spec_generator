"""
Ranking Failure Analysis + Alternative Ranking Policy Benchmark 테스트.

Ollama 없이 실행 가능한 Unit Test(1~7, 요청서 21절)와 Real RAG Smoke Test로 나뉜다.
Unit Test는 scripts/ranking_failure_benchmark_lib.py의 순수 함수만 검증하며,
production select_best_candidate()를 직접 호출해 Policy A를 검증한다(정렬 로직을
재구현해 비교하지 않는다).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.candidate_matcher import select_best_candidate  # noqa: E402
from agent.schemas import CandidateEquipment, CandidateFieldMatch  # noqa: E402
from scripts.ranking_failure_benchmark_lib import (  # noqa: E402
    FUNNEL_RANKING_FAILURE,
    FUNNEL_RETRIEVAL_FAILURE,
    FUNNEL_SUCCESS,
    FUNNEL_VALIDATION_FAILURE,
    POLICIES,
    classify_ambiguity,
    classify_funnel,
    classify_ranking_loss_reason,
    is_false_pass,
    policy_a_key,
    rank_candidates_offline,
    status_priority_holds,
    top_n_via_production_selection,
)


def _cand(candidate_id, source_document, status="PASS", pass_count=1, unknown_count=0, fail_count=0, rag_similarity_score=0.5, matches=None):
    return CandidateEquipment(
        candidate_id=candidate_id,
        source_document=source_document,
        manufacturer="SynthCo",
        model=candidate_id,
        status=status,
        pass_count=pass_count,
        unknown_count=unknown_count,
        fail_count=fail_count,
        rag_similarity_score=rag_similarity_score,
        matches=matches or [],
    )


def _match(item, result):
    return CandidateFieldMatch(item=item, field_key=item.lower().replace(" ", "_"), result=result)


# ==========================================
# Test 1 — Policy A는 production select_best_candidate()와 항상 동일해야 한다
# ==========================================
@pytest.mark.parametrize(
    "pool",
    [
        [_cand("A", "SPEC-A.md", status="PASS", pass_count=2), _cand("B", "SPEC-B.md", status="PARTIAL")],
        [_cand("A", "SPEC-A.md", status="FAIL"), _cand("B", "SPEC-B.md", status="FAIL", fail_count=2)],
        [_cand("A", "SPEC-A.md", pass_count=3, rag_similarity_score=0.1), _cand("B", "SPEC-B.md", pass_count=3, rag_similarity_score=0.9)],
        [_cand("Z", "SPEC-Z.md", pass_count=1, rag_similarity_score=0.5), _cand("A", "SPEC-A.md", pass_count=1, rag_similarity_score=0.5)],
        [],
    ],
)
def test_policy_a_matches_production_select_best_candidate(pool):
    production_chosen = select_best_candidate(pool)
    offline_ranked = rank_candidates_offline(pool, policy_a_key)
    offline_top1 = offline_ranked[0] if offline_ranked else None

    if production_chosen is None:
        assert offline_top1 is None
    else:
        assert offline_top1 is not None
        assert offline_top1.candidate_id == production_chosen.candidate_id


# ==========================================
# Test 2 — Expected Candidate가 Candidate Pool에 존재하면 classify_funnel()이
# RETRIEVAL_FAILURE로 잘못 분류하지 않는다(Candidate Extraction이 정상 인식됨).
# ==========================================
def test_classify_funnel_recognizes_expected_candidate_present_in_pool():
    pool = [_cand("A", "SPEC-A.md", status="PASS"), _cand("B", "SPEC-B.md", status="PASS")]
    result = classify_funnel(pool, expected_spec_ids={"SPEC-A.md"})
    assert result.stage != FUNNEL_RETRIEVAL_FAILURE
    assert result.expected_in_pool is True


# ==========================================
# Test 3 — Top-N은 production 반복 선택 방식과 policy_a_key 정렬 결과가 일치해야 한다
# ==========================================
def test_top_n_production_matches_policy_a_offline_ranking():
    pool = [
        _cand("A", "SPEC-A.md", pass_count=3),
        _cand("B", "SPEC-B.md", pass_count=5),
        _cand("C", "SPEC-C.md", status="PARTIAL"),
        _cand("D", "SPEC-D.md", status="FAIL"),
    ]
    top_n = top_n_via_production_selection(pool, 3)
    offline_top_n = rank_candidates_offline(pool, policy_a_key)[:3]
    assert [c.candidate_id for c in top_n] == [c.candidate_id for c in offline_top_n]


# ==========================================
# Test 4 — Failure 분류가 구조적으로 일관됨(요청서 21절 Test 4 pseudo logic)
# ==========================================
def test_funnel_classification_retrieval_failure_when_expected_absent():
    pool = [_cand("A", "SPEC-A.md", status="PASS")]
    result = classify_funnel(pool, expected_spec_ids={"SPEC-NOT-PRESENT.md"})
    assert result.stage == FUNNEL_RETRIEVAL_FAILURE


def test_funnel_classification_validation_failure_when_expected_not_pass():
    pool = [_cand("A", "SPEC-A.md", status="PARTIAL"), _cand("B", "SPEC-B.md", status="PASS")]
    result = classify_funnel(pool, expected_spec_ids={"SPEC-A.md"})
    assert result.stage == FUNNEL_VALIDATION_FAILURE


def test_funnel_classification_success_when_expected_is_top1():
    pool = [_cand("A", "SPEC-A.md", status="PASS", pass_count=5), _cand("B", "SPEC-B.md", status="PASS", pass_count=1)]
    result = classify_funnel(pool, expected_spec_ids={"SPEC-A.md"})
    assert result.stage == FUNNEL_SUCCESS
    assert result.top1_is_expected is True


def test_funnel_classification_ranking_failure_when_expected_pass_but_not_top1():
    pool = [_cand("A", "SPEC-A.md", status="PASS", pass_count=1), _cand("B", "SPEC-B.md", status="PASS", pass_count=5)]
    result = classify_funnel(pool, expected_spec_ids={"SPEC-A.md"})
    assert result.stage == FUNNEL_RANKING_FAILURE
    assert result.top1.source_document == "SPEC-B.md"


# ==========================================
# Test 5 — 4개 Policy 전부 PASS > PARTIAL > FAIL을 위반하지 않는다
# ==========================================
def test_all_policies_preserve_status_priority():
    pool = [
        _cand("A", "SPEC-A.md", status="FAIL", rag_similarity_score=0.99),
        _cand("B", "SPEC-B.md", status="PARTIAL", rag_similarity_score=0.5),
        _cand("C", "SPEC-C.md", status="PASS", rag_similarity_score=0.01),
        _cand("D", "SPEC-D.md", status="PASS", pass_count=1, rag_similarity_score=0.02),
    ]
    for name, key_fn in POLICIES.items():
        ranked = rank_candidates_offline(pool, key_fn)
        assert status_priority_holds(ranked), f"{name}가 PASS>PARTIAL>FAIL을 위반했습니다: {[c.status for c in ranked]}"


# ==========================================
# Test 6 — 대안 Policy도 결정론적이어야 한다(같은 입력 -> 항상 같은 출력)
# ==========================================
def test_alternative_policies_are_deterministic():
    pool = [
        _cand("B", "SPEC-B.md", pass_count=2, rag_similarity_score=0.4),
        _cand("A", "SPEC-A.md", pass_count=2, rag_similarity_score=0.4),
        _cand("C", "SPEC-C.md", pass_count=3, rag_similarity_score=0.1),
    ]
    for name, key_fn in POLICIES.items():
        run1 = [c.candidate_id for c in rank_candidates_offline(pool, key_fn)]
        run2 = [c.candidate_id for c in rank_candidates_offline(list(reversed(pool)), key_fn)]
        assert run1 == run2, f"{name}가 입력 순서에 따라 다른 결과를 냈습니다: {run1} vs {run2}"


# ==========================================
# Test 7 — No-Match Case에서 False PASS 판정이 정확함
# ==========================================
def test_is_false_pass_detects_pass_status():
    assert is_false_pass("PASS") is True
    assert is_false_pass("PARTIAL") is False
    assert is_false_pass("FAIL") is False
    assert is_false_pass(None) is False


# ==========================================
# 추가: Ranking Loss Reason 분류 정확성(요청서 9절)
# ==========================================
def test_ranking_loss_reason_pass_count():
    expected = _cand("E", "SPEC-E.md", pass_count=2, unknown_count=0, fail_count=0, rag_similarity_score=0.5)
    top1 = _cand("T", "SPEC-T.md", pass_count=5, unknown_count=0, fail_count=0, rag_similarity_score=0.3)
    assert classify_ranking_loss_reason(expected, top1) == "PASS_COUNT_LOSS"


def test_ranking_loss_reason_similarity():
    expected = _cand("E", "SPEC-E.md", pass_count=3, unknown_count=0, fail_count=0, rag_similarity_score=0.1)
    top1 = _cand("T", "SPEC-T.md", pass_count=3, unknown_count=0, fail_count=0, rag_similarity_score=0.9)
    assert classify_ranking_loss_reason(expected, top1) == "SIMILARITY_LOSS"


def test_ranking_loss_reason_candidate_id_tiebreak():
    expected = _cand("Z", "SPEC-Z.md", pass_count=3, unknown_count=0, fail_count=0, rag_similarity_score=0.5)
    top1 = _cand("A", "SPEC-A.md", pass_count=3, unknown_count=0, fail_count=0, rag_similarity_score=0.5)
    assert classify_ranking_loss_reason(expected, top1) == "CANDIDATE_ID_TIEBREAK"


def test_classify_ambiguity_both_valid_when_same_pass_items():
    expected = _cand("E", "SPEC-E.md", matches=[_match("Width", "PASS"), _match("Inline", "PASS")])
    top1 = _cand("T", "SPEC-T.md", matches=[_match("Width", "PASS"), _match("Inline", "PASS")])
    assert classify_ambiguity(expected, top1) == "BOTH_VALID"


def test_classify_ambiguity_expected_clearly_better():
    expected = _cand("E", "SPEC-E.md", matches=[_match("Width", "PASS"), _match("Inline", "PASS"), _match("Speed", "PASS")])
    top1 = _cand("T", "SPEC-T.md", matches=[_match("Width", "PASS")])
    assert classify_ambiguity(expected, top1) == "EXPECTED_CLEARLY_BETTER"


def test_classify_ambiguity_insufficient_evidence_when_disjoint():
    expected = _cand("E", "SPEC-E.md", matches=[_match("Width", "PASS")])
    top1 = _cand("T", "SPEC-T.md", matches=[_match("Speed", "PASS")])
    assert classify_ambiguity(expected, top1) == "INSUFFICIENT_EVIDENCE"


# ==========================================
# Real RAG Smoke Test — real_rag 마커 재사용. Ollama 없으면 자동 SKIP.
# ==========================================
_SMOKE_CASE_IDS = ["T001", "T003", "T009", "QA023"]


@pytest.mark.real_rag
def test_ranking_failure_benchmark_smoke_with_real_ollama():
    from tests import real_rag_lib as rag

    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        pytest.skip(f"embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    from scripts.ranking_failure_benchmark import analyze, run_real_pass

    # 전용 cache_path를 명시한다 — 기본 공유 캐시(benchmark_results/ranking_failure_
    # cache.json)에 쓰면 전체 56케이스로 만든 캐시를 이 smoke test의 4케이스 결과로
    # 덮어써 버리는 문제가 실제로 있었다(회귀 스위트가 이 테스트를 돌릴 때마다
    # ground_truth_ambiguity_benchmark.py가 참조하는 전체 캐시가 축소됨).
    smoke_cache_path = Path(__file__).resolve().parent.parent / "benchmark_results" / "_smoke_ranking_failure_cache.json"
    cache = run_real_pass(k_values=[10], case_ids=_SMOKE_CASE_IDS, cache_path=smoke_cache_path)
    analysis = analyze(cache)

    assert not analysis["policy_a_verification_errors"], analysis["policy_a_verification_errors"]
    funnel = analysis["funnel_by_k"][10]
    assert sum(funnel.values()) == len([c for c in cache["cases"].values() if c["expected_spec_ids"]])
    print(f"\n[smoke] funnel@k=10: {funnel}")
    print(f"[smoke] policy_comparison: {analysis['policy_comparison']}")

    import shutil

    shutil.rmtree(Path(__file__).resolve().parent.parent / "_test_chroma_db_ranking_failure", ignore_errors=True)
    smoke_cache_path.unlink(missing_ok=True)
