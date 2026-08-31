"""
Full Retrieval Recall Benchmark 테스트.

두 층으로 나뉜다(요청서 18절).

1. Ollama 없이 실행 가능한 Unit Test(18-1) — scripts/full_retrieval_recall_benchmark_lib.py의
   순수 함수(Dataset Discovery/Expected Candidate 정규화/Metric 계산)만 검증한다.
   Synthetic 데이터로 Metric 계산을 검증하되, Production Ranking 로직은 재구현하지 않는다
   (에초에 그 로직을 호출하지도 않는 순수 함수들이다).

2. Real RAG Smoke Test(18-2) — real_rag 마커를 재사용(새 마커 없음)해 소규모 대표
   질의(5개)로 scripts/full_retrieval_recall_benchmark.py::run_benchmark()을 실제
   Ollama로 한 번 돌려 전체 파이프라인이 깨지지 않았는지만 빠르게 확인한다. 56개
   전체 Dataset × 4개 k값의 Full Benchmark는 느리므로 pytest에 넣지 않는다(요청서
   19절) — `python scripts/full_retrieval_recall_benchmark.py`로 별도 실행한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.full_retrieval_recall_benchmark_lib import (  # noqa: E402
    RecallEvaluation,
    build_equipment_name_to_spec_ids,
    candidate_level_documents,
    compute_recall_at_k,
    discover_benchmark_cases,
    discover_sample_spec_files,
    evaluate_recall_for_case,
    rank_candidates_by_score,
    resolve_expected_spec_ids,
)


# ==========================================
# 18-1. Dataset Discovery
# ==========================================
def test_discover_sample_spec_files_is_dynamic_not_hardcoded():
    """개수를 하드코딩하지 않고 실제 glob 결과와 일치하는지 확인 — 이 assertion
    자체도 숫자를 박아넣지 않고 독립적인 glob 재호출과 비교한다."""
    from_lib = discover_sample_spec_files()
    fresh_glob = sorted(Path(__file__).resolve().parent.parent.glob("sample_specs/SPEC-*.md"))
    assert [p.name for p in from_lib] == [p.name for p in fresh_glob]
    assert len(from_lib) > 0


def test_discover_benchmark_cases_matches_raw_json_and_covers_t_and_qa():
    import json

    raw_path = Path(__file__).resolve().parent / "ground_truth" / "regression_cases.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    cases = discover_benchmark_cases()

    assert len(cases) == len(raw["cases"]), "discover_benchmark_cases()가 JSON의 cases 배열과 개수가 다릅니다"
    ids = {c["test_id"] for c in cases}
    assert any(i.startswith("T") for i in ids), "T 시리즈 케이스가 하나도 없습니다"
    assert any(i.startswith("QA") for i in ids), "QA 시리즈 케이스가 하나도 없습니다"
    # 새 케이스(T028, QA030 등)가 추가되면 이 테스트를 고치지 않아도 자동으로 포함되는지 —
    # 즉 이 테스트가 특정 test_id 존재를 강제하지 않는지 스스로 확인.
    assert ids == {c["test_id"] for c in raw["cases"]}


# ==========================================
# 18-1. Expected Candidate Normalization
# ==========================================
def test_equipment_name_mapping_finds_the_one_known_duplicate():
    """TESTING.md에 문서화된 유일한 중복 장비명("MultiInspect MI-800",
    SPEC-044.md/SPEC-051.md)이 실제로 그렇게 매핑되는지 확인 — corpus 데이터 사실에
    대한 회귀 가드(코드 로직이 아니라 현재 corpus 상태를 기준으로 한 assertion)."""
    mapping = build_equipment_name_to_spec_ids()
    dupes = {k: v for k, v in mapping.items() if len(v) > 1}
    assert dupes == {"MultiInspect MI-800": {"SPEC-044.md", "SPEC-051.md"}}, (
        f"코퍼스의 중복 장비명 목록이 예상과 다릅니다(SPEC 파일이 추가/변경되었을 수 있음): {dupes}"
    )


def test_resolve_expected_spec_ids_single_candidate():
    case = {"expected_pass_candidates": ["A"]}
    name_map = {"A": {"SPEC-001.md"}}
    assert resolve_expected_spec_ids(case, name_map) == {"SPEC-001.md"}


def test_resolve_expected_spec_ids_multiple_candidates_use_or_semantics():
    case = {"expected_pass_candidates": ["A", "B"]}
    name_map = {"A": {"SPEC-001.md"}, "B": {"SPEC-002.md"}}
    assert resolve_expected_spec_ids(case, name_map) == {"SPEC-001.md", "SPEC-002.md"}


def test_resolve_expected_spec_ids_respects_candidate_spec_ids_override():
    case = {"expected_pass_candidates": ["Dup"], "candidate_spec_ids": {"Dup": "SPEC-099.md"}}
    name_map = {"Dup": {"SPEC-098.md", "SPEC-099.md"}}
    # 오버라이드가 있으면 모호한 이름의 전체 집합이 아니라 오버라이드된 파일 "하나만" 써야 한다.
    assert resolve_expected_spec_ids(case, name_map) == {"SPEC-099.md"}


def test_resolve_expected_spec_ids_empty_when_no_expected_candidates():
    case = {"expected_pass_candidates": []}
    assert resolve_expected_spec_ids(case, {"A": {"SPEC-001.md"}}) == set()

    case2 = {}  # 필드 자체가 없는 경우도 방어적으로 처리되는지
    assert resolve_expected_spec_ids(case2, {"A": {"SPEC-001.md"}}) == set()


# ==========================================
# 18-1. Candidate-Level Recall/Rank Metric 계산 (Synthetic Data)
# ==========================================
class _FakeDoc:
    def __init__(self, filename, score=None):
        self.metadata = {"filename": filename}
        if score is not None:
            self.metadata["score"] = score


def test_candidate_level_documents_dedups_multiple_chunks_to_one_candidate():
    """동일 SPEC의 여러 chunk는 하나의 candidate(문서)로 취급하고, score가 있는
    chunk 중 최댓값을 그 문서의 대표 score로 쓴다(요청서 15절)."""
    docs = [
        _FakeDoc("SPEC-051.md", score=0.5),
        _FakeDoc("SPEC-051.md", score=0.8),  # 같은 문서, 더 높은 score
        _FakeDoc("SPEC-051.md"),  # 같은 문서, score 없음(boost로 들어온 chunk)
        _FakeDoc("SPEC-020.md", score=0.3),
    ]
    result = candidate_level_documents(docs)
    assert result == {"SPEC-051.md": 0.8, "SPEC-020.md": 0.3}


def test_rank_candidates_by_score_orders_descending_and_separates_unscored():
    doc_scores = {"SPEC-A.md": 0.9, "SPEC-B.md": 0.5, "SPEC-C.md": None, "SPEC-D.md": 0.7}
    ranked = rank_candidates_by_score(doc_scores)
    scored_part = [r for r in ranked if r[2] is not None]
    assert [name for name, _s, _r in scored_part] == ["SPEC-A.md", "SPEC-D.md", "SPEC-B.md"]
    assert [rank for _n, _s, rank in scored_part] == [1, 2, 3]
    unscored_part = [r for r in ranked if r[2] is None]
    assert [name for name, _s, _r in unscored_part] == ["SPEC-C.md"]


def test_evaluate_recall_hit_scored():
    doc_scores = {"SPEC-051.md": 0.9, "SPEC-020.md": 0.5}
    ev = evaluate_recall_for_case({"SPEC-051.md"}, doc_scores)
    assert ev.evaluable and ev.hit and ev.rank == 1 and ev.rank_kind == "scored"


def test_evaluate_recall_hit_boost_only():
    """score가 전혀 없는(=boost로만 들어온) 문서는 hit이지만 rank는 매길 수 없다."""
    doc_scores = {"SPEC-051.md": None, "SPEC-020.md": 0.5}
    ev = evaluate_recall_for_case({"SPEC-051.md"}, doc_scores)
    assert ev.evaluable and ev.hit and ev.rank is None and ev.rank_kind == "boost_only"


def test_evaluate_recall_miss():
    doc_scores = {"SPEC-020.md": 0.5}
    ev = evaluate_recall_for_case({"SPEC-051.md"}, doc_scores)
    assert ev.evaluable and not ev.hit and ev.rank_kind == "miss"


def test_evaluate_recall_not_evaluable_when_no_expected_candidate():
    ev = evaluate_recall_for_case(set(), {"SPEC-020.md": 0.5})
    assert not ev.evaluable


def test_evaluate_recall_multiple_expected_uses_best_rank():
    """여러 개 허용 후보 중 가장 높은(작은) 순위를 쓴다(요청서 7절)."""
    doc_scores = {"SPEC-A.md": 0.9, "SPEC-B.md": 0.5, "SPEC-C.md": 0.1}
    # expected = {A, C}; A가 rank 1, C가 rank 3 -> best는 A(rank 1)
    ev = evaluate_recall_for_case({"SPEC-A.md", "SPEC-C.md"}, doc_scores)
    assert ev.hit and ev.rank == 1 and ev.matched_spec == "SPEC-A.md"


def test_compute_recall_at_k_basic_math():
    evals = [
        ("T1", RecallEvaluation(evaluable=True, hit=True, rank=1, rank_kind="scored")),
        ("T2", RecallEvaluation(evaluable=True, hit=True, rank=3, rank_kind="scored")),
        ("T3", RecallEvaluation(evaluable=True, hit=False, rank_kind="miss")),
        ("T4", RecallEvaluation(evaluable=False)),  # 분모에서 제외
        ("T5", RecallEvaluation(evaluable=True, hit=True, rank=None, rank_kind="boost_only")),
    ]
    summary = compute_recall_at_k(10, evals)
    assert summary.n_total_cases == 5
    assert summary.n_evaluable == 4  # T4 제외
    assert summary.n_excluded_no_expected == 1
    assert summary.n_hit == 3  # T1, T2, T5
    assert summary.n_miss == 1  # T3
    assert summary.recall == pytest.approx(3 / 4)
    assert summary.n_boost_only_hit == 1
    # rank 통계는 scored만(T1=1, T2=3) — boost_only(T5)는 제외
    assert summary.avg_rank == pytest.approx(2.0)
    assert summary.median_rank == pytest.approx(2.0)
    assert summary.worst_rank == 3
    assert summary.mrr == pytest.approx((1 / 1 + 1 / 3) / 2)


def test_compute_recall_at_k_handles_no_evaluable_cases():
    evals = [("T1", RecallEvaluation(evaluable=False))]
    summary = compute_recall_at_k(10, evals)
    assert summary.n_evaluable == 0
    assert summary.recall is None
    assert summary.avg_rank is None
    assert summary.mrr is None


# ==========================================
# 18-2. Real RAG Smoke Test — real_rag 마커 재사용, 새 마커 없음. Ollama 없으면 자동 SKIP.
# ==========================================
_SMOKE_CASE_IDS = ["T001", "T003", "T004", "T005", "T009"]


@pytest.mark.real_rag
def test_full_benchmark_smoke_with_real_ollama():
    """56개 전체가 아니라 대표 5개 케이스 × k=10(production default)만 빠르게 실행해
    scripts/full_retrieval_recall_benchmark.py::run_benchmark()이 실제 Ollama
    환경에서 예외 없이 끝까지 도는지 확인한다. 전체 Dataset Full Benchmark는 이
    테스트가 아니라 별도 스크립트 실행으로 한다(요청서 19절)."""
    from tests import real_rag_lib as rag

    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        pytest.skip(f"embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    from scripts.full_retrieval_recall_benchmark import run_benchmark

    result = run_benchmark(k_values=[10], case_ids=_SMOKE_CASE_IDS)

    assert result["dataset"]["n_cases_run"] == len(_SMOKE_CASE_IDS)
    summary = result["summaries"][10]
    assert summary["n_evaluable"] > 0
    assert summary["recall"] is not None
    print(f"\n[smoke] k=10 recall={summary['recall']:.2f} hit={summary['n_hit']}/{summary['n_evaluable']}")

    import shutil

    shutil.rmtree(Path(__file__).resolve().parent.parent / "_test_chroma_db_full_benchmark", ignore_errors=True)
