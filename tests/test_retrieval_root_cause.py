"""
Retrieval MISS Root Cause 분류 Unit Test — 전부 Synthetic Evidence, Ollama 불필요.
scripts/retrieval_root_cause_lib.py의 순수 분류 함수만 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.retrieval_root_cause_lib import (  # noqa: E402
    CAUSE_A_VOCABULARY_MISMATCH,
    CAUSE_B_GENERIC_QUERY_COMPETITION,
    CAUSE_C_SPARSE_REQUIREMENT_QUERY,
    CAUSE_D_QUERY_EXPANSION_WEAKNESS,
    CAUSE_E_RANKING_IN_RETRIEVAL_STAGE,
    CAUSE_F_CORPUS_REPRESENTATION_PROBLEM,
    RootCauseEvidence,
    classify_root_cause,
)


def _ev(**overrides):
    defaults = dict(
        test_id="T1", query="q", production_k=10, requirement_field_count=3,
        n_expanded_queries=4, expanded_queries=["a", "b", "c", "d"],
        best_rank_across_queries=None, best_rank_query=None,
        n_unique_docs_in_expanded_top_n=5, lexical_overlap=True, lexical_overlap_terms=["thickness"],
        range_boost_applicable=False, inspection_item_boost_applicable=False,
    )
    defaults.update(overrides)
    return RootCauseEvidence(**defaults)


def test_cause_e_when_found_beyond_production_k():
    ev = _ev(best_rank_across_queries=15, best_rank_query="q2", production_k=10)
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_E_RANKING_IN_RETRIEVAL_STAGE


def test_cause_c_when_sparse_requirement():
    ev = _ev(best_rank_across_queries=None, requirement_field_count=1)
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_C_SPARSE_REQUIREMENT_QUERY


def test_cause_d_when_few_expanded_queries():
    ev = _ev(best_rank_across_queries=None, requirement_field_count=3, n_expanded_queries=1)
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_D_QUERY_EXPANSION_WEAKNESS


def test_cause_a_when_no_lexical_overlap():
    ev = _ev(best_rank_across_queries=None, requirement_field_count=3, n_expanded_queries=4, lexical_overlap=False)
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_A_VOCABULARY_MISMATCH


def test_cause_b_when_generic_competition():
    ev = _ev(
        best_rank_across_queries=None, requirement_field_count=3, n_expanded_queries=4,
        lexical_overlap=True, n_unique_docs_in_expanded_top_n=20,
    )
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_B_GENERIC_QUERY_COMPETITION


def test_cause_f_when_no_other_evidence_applies():
    ev = _ev(
        best_rank_across_queries=None, requirement_field_count=3, n_expanded_queries=4,
        lexical_overlap=True, n_unique_docs_in_expanded_top_n=5,
    )
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_F_CORPUS_REPRESENTATION_PROBLEM


def test_cause_e_takes_priority_over_others():
    """found_beyond_k 증거가 있으면 다른 조건(sparse 등)과 무관하게 항상 E가 우선한다
    (E는 직접 관찰된 사실, 나머지는 소거법 추론이므로)."""
    ev = _ev(best_rank_across_queries=12, best_rank_query="q1", requirement_field_count=1, n_expanded_queries=1, lexical_overlap=False)
    result = classify_root_cause(ev)
    assert result["cause"] == CAUSE_E_RANKING_IN_RETRIEVAL_STAGE


@pytest.mark.parametrize("rank,production_k", [(11, 10), (50, 10), (16, 15)])
def test_cause_e_boundary(rank, production_k):
    ev = _ev(best_rank_across_queries=rank, best_rank_query="q", production_k=production_k)
    assert classify_root_cause(ev)["cause"] == CAUSE_E_RANKING_IN_RETRIEVAL_STAGE
