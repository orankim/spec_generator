"""
Ground Truth Ambiguity 분류 Unit Test — 전부 Synthetic Candidate, Ollama 불필요.
scripts/ground_truth_ambiguity_lib.py의 순수 함수만 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ground_truth_ambiguity_lib import (  # noqa: E402
    EXPECTED_CLEARLY_BETTER,
    INSUFFICIENT_EVIDENCE,
    MULTIPLE_VALID,
    NOT_APPLICABLE,
    TOP1_CLEARLY_BETTER,
    UNIQUE_VALID,
    classify_case,
    compute_metrics,
)


def _cand(candidate_id, source_document, status="PASS", pass_count=1, unknown_count=0, fail_count=0, rag_similarity_score=0.5, matches=None):
    return {
        "candidate_id": candidate_id, "source_document": source_document, "manufacturer": "SynthCo", "model": candidate_id,
        "status": status, "pass_count": pass_count, "unknown_count": unknown_count, "fail_count": fail_count,
        "rag_similarity_score": rag_similarity_score, "matches": matches or [],
    }


def _match(item, result):
    return {"item": item, "field_key": item.lower(), "result": result}


# ==========================================
# 1. UNIQUE_VALID
# ==========================================
def test_unique_valid_when_only_expected_is_pass():
    candidates = [_cand("A", "SPEC-A.md", status="PASS"), _cand("B", "SPEC-B.md", status="PARTIAL")]
    result = classify_case("T1", 10, candidates, {"SPEC-A.md"})
    assert result.category == UNIQUE_VALID
    assert result.strict_top1 is True
    assert result.acceptable_top1 is True


# ==========================================
# 2. MULTIPLE_VALID (Expected가 이겼지만 다른 PASS도 있음)
# ==========================================
def test_multiple_valid_when_expected_wins_but_other_pass_exists():
    candidates = [_cand("A", "SPEC-A.md", status="PASS", pass_count=5), _cand("B", "SPEC-B.md", status="PASS", pass_count=1)]
    result = classify_case("T2", 10, candidates, {"SPEC-A.md"})
    assert result.category == MULTIPLE_VALID
    assert result.strict_top1 is True
    assert result.acceptable_top1 is True


# ==========================================
# 2b. MULTIPLE_VALID (Expected가 졌지만 PASS 항목이 동일 — BOTH_VALID 매핑)
# ==========================================
def test_multiple_valid_when_expected_loses_but_pass_items_equal():
    matches = [_match("Width", "PASS"), _match("Inline", "PASS")]
    candidates = [
        _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=matches),
        _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=matches),
    ]
    result = classify_case("T3", 10, candidates, {"SPEC-A.md"})
    assert result.category == MULTIPLE_VALID
    assert result.strict_top1 is False
    assert result.acceptable_top1 is True  # Top1이 Expected와 동등하게 유효하므로 acceptable


# ==========================================
# 3. EXPECTED_CLEARLY_BETTER
# ==========================================
def test_expected_clearly_better():
    candidates = [
        _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=[_match("Width", "PASS"), _match("Speed", "PASS")]),
        _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=[_match("Width", "PASS")]),
    ]
    result = classify_case("T4", 10, candidates, {"SPEC-A.md"})
    assert result.category == EXPECTED_CLEARLY_BETTER
    assert result.strict_top1 is False
    assert result.acceptable_top1 is False  # Top1이 Expected보다 못하므로 acceptable 아님


# ==========================================
# 4. TOP1_CLEARLY_BETTER
# ==========================================
def test_top1_clearly_better():
    candidates = [
        _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=[_match("Width", "PASS")]),
        _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=[_match("Width", "PASS"), _match("Speed", "PASS")]),
    ]
    result = classify_case("T5", 10, candidates, {"SPEC-A.md"})
    assert result.category == TOP1_CLEARLY_BETTER
    assert result.acceptable_top1 is False


# ==========================================
# 5. INSUFFICIENT_EVIDENCE
# ==========================================
def test_insufficient_evidence_when_disjoint_pass_items():
    candidates = [
        _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=[_match("Width", "PASS")]),
        _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=[_match("Speed", "PASS")]),
    ]
    result = classify_case("T6", 10, candidates, {"SPEC-A.md"})
    assert result.category == INSUFFICIENT_EVIDENCE
    assert result.acceptable_top1 is False


# ==========================================
# NOT_APPLICABLE — Retrieval/Validation Failure는 이 분류 대상이 아님
# ==========================================
def test_not_applicable_when_expected_absent():
    candidates = [_cand("A", "SPEC-A.md", status="PASS")]
    result = classify_case("T7", 10, candidates, {"SPEC-NOT-PRESENT.md"})
    assert result.category == NOT_APPLICABLE
    assert result.strict_top1 is False
    assert result.acceptable_top1 is False


def test_not_applicable_when_expected_not_pass():
    candidates = [_cand("A", "SPEC-A.md", status="PARTIAL"), _cand("B", "SPEC-B.md", status="PASS")]
    result = classify_case("T8", 10, candidates, {"SPEC-A.md"})
    assert result.category == NOT_APPLICABLE


# ==========================================
# Acceptable Top1: Expected가 아니지만 동등하게 유효 -> True (요청서 22절)
# ==========================================
def test_acceptable_top1_true_when_not_strict_but_multiple_valid():
    matches = [_match("Width", "PASS")]
    candidates = [
        _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=matches),
        _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=matches),
    ]
    result = classify_case("T9", 10, candidates, {"SPEC-A.md"})
    assert result.strict_top1 is False
    assert result.acceptable_top1 is True


# ==========================================
# Ground Truth Unique Accuracy — UNIQUE_VALID 케이스만 필터링되는지
# ==========================================
def test_compute_metrics_unique_accuracy_filters_correctly():
    results = [
        classify_case("U1", 10, [_cand("A", "SPEC-A.md", status="PASS")], {"SPEC-A.md"}),  # UNIQUE_VALID, strict=True
        classify_case(
            "M1", 10,
            [
                _cand("A", "SPEC-A.md", status="PASS", pass_count=1, rag_similarity_score=0.1, matches=[_match("W", "PASS")]),
                _cand("B", "SPEC-B.md", status="PASS", pass_count=1, rag_similarity_score=0.9, matches=[_match("W", "PASS")]),
            ],
            {"SPEC-A.md"},
        ),  # MULTIPLE_VALID, strict=False
    ]
    summary = compute_metrics(results)
    assert summary.n_unique_valid == 1
    assert summary.ground_truth_unique_accuracy == 1.0  # UNIQUE_VALID 케이스(U1)만 봤을 때 100% strict top1
    # 전체 strict_top1_rate는 2건 중 1건만 True이므로 0.5
    assert summary.strict_top1_rate == pytest.approx(0.5)
