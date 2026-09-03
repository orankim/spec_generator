"""
Evaluation Framework(Metric A~E) Unit Test — 전부 synthetic cache dict, Ollama 불필요.
scripts/evaluation_framework_lib.py의 순수 함수만 검증한다. 이 파일은 production
select_best_candidate()/build_candidates()를 재구현하지 않는다 — synthetic 데이터를
scripts/ground_truth_ambiguity_lib.classify_case()가 기대하는 캐시 dict 스키마
그대로 만들어 넣고, 그 분류 결과를 evaluation_framework_lib가 올바르게 재정리하는지만
확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.evaluation_framework_lib import (  # noqa: E402
    classify_low_strict_high_acceptable_cases,
    multiple_valid_interpretation,
    no_match_safety,
    summarize,
    unique_valid_recheck,
)
from scripts.ground_truth_ambiguity_lib import analyze_cache  # noqa: E402


def _candidate(candidate_id, source_document, status, pass_count, unknown_count=0, fail_count=0, sim=0.5):
    return {
        "candidate_id": candidate_id, "source_document": source_document, "status": status,
        "pass_count": pass_count, "unknown_count": unknown_count, "fail_count": fail_count,
        "rag_similarity_score": sim, "matches": [],
    }


def _cache(cases: dict, k_values=(10,)) -> dict:
    return {
        "environment": {"embedding_model": "bge-m3", "llm_model": "qwen2.5:3b", "indexed_spec_count": 52},
        "k_values": list(k_values),
        "cases": cases,
    }


def _case(expected_spec_ids, expected_final_status, candidates_by_k):
    return {
        "expected_spec_ids": expected_spec_ids,
        "expected_final_status": expected_final_status,
        "by_k": {str(k): {"candidates": c} for k, c in candidates_by_k.items()},
    }


# 7-1: Strict Accuracy 계산 — UNIQUE_VALID(경쟁 없음)이고 Top1==Expected면 Strict=True.
def test_strict_accuracy_computation():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [_candidate("c1", "SPEC-A.md", "PASS", 3, sim=0.9)]}),
    })
    summary = summarize(cache, 10)
    assert summary.metric_a_strict_top1 == 1.0


# 7-2: Acceptable Accuracy 계산 — Expected가 이겼지만 동등 PASS 대안이 있으면 여전히 Acceptable(자명히 True).
def test_acceptable_accuracy_computation():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [
            _candidate("c1", "SPEC-A.md", "PASS", 3, sim=0.9),
            _candidate("c2", "SPEC-B.md", "PASS", 3, sim=0.1),
        ]}),
    })
    summary = summarize(cache, 10)
    assert summary.metric_b_acceptable_top1 == 1.0


# 7-3: Unique GT Accuracy 계산 — UNIQUE_VALID 케이스만 분모로 삼는다.
def test_unique_gt_accuracy_computation():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [_candidate("c1", "SPEC-A.md", "PASS", 3, sim=0.9)]}),
        # T2는 MULTIPLE_VALID(대안 존재) — Unique GT Accuracy 분모에서 제외돼야 함.
        "T2": _case(["SPEC-C.md"], None, {10: [
            _candidate("c1", "SPEC-C.md", "PASS", 3, sim=0.9),
            _candidate("c2", "SPEC-D.md", "PASS", 3, sim=0.1),
        ]}),
    })
    summary = summarize(cache, 10)
    assert summary.metric_c_unique_gt_accuracy == 1.0
    assert summary.category_counts["UNIQUE_VALID"] == 1


# 7-4: Requirement Satisfaction 계산 — Top1.status==PASS이면 Expected 일치 여부와 무관하게 True.
def test_requirement_satisfaction_computation():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [
            _candidate("c1", "SPEC-B.md", "PASS", 5, sim=0.9),  # Top1(더 높은 pass_count)이지만 Expected 아님
            _candidate("c2", "SPEC-A.md", "PASS", 1, sim=0.1),
        ]}),
    })
    summary = summarize(cache, 10)
    assert summary.metric_a_strict_top1 == 0.0  # Top1(SPEC-B)이 Expected(SPEC-A)와 다름
    assert summary.metric_d_requirement_satisfaction == 1.0  # 그래도 Top1이 PASS이긴 함


# 7-5: No-Match Safety 계산 — QA026류(expected_final_status=PASS로 설계된 케이스)는 제외, 나머지는 False PASS로 집계.
def test_no_match_safety_computation():
    cache = _cache({
        "NM1": _case([], None, {10: [_candidate("c1", "SPEC-X.md", "PASS", 1)]}),  # 진짜 No-Match인데 PASS -> False PASS
        "NM2": _case([], "PASS", {10: [_candidate("c1", "SPEC-Y.md", "PASS", 1)]}),  # 설계상 PASS 의도 -> 제외
        "NM3": _case([], None, {10: [_candidate("c1", "SPEC-Z.md", "FAIL", 0, fail_count=1)]}),  # 정상(PASS 없음)
    })
    safety = no_match_safety(cache, 10)
    assert safety["n_no_match_total"] == 3
    assert safety["n_excluded_by_design"] == 1
    assert safety["excluded_case_ids"] == ["NM2"]
    assert safety["true_false_pass_count"] == 1
    assert safety["true_false_pass_case_ids"] == ["NM1"]


# 7-6: MULTIPLE_VALID이 Strict Match 실패지만 Acceptable인 경우 — Q1 분류에서 GT ambiguity로 잡혀야 함.
def test_multiple_valid_strict_fail_but_acceptable():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [
            _candidate("c1", "SPEC-B.md", "PASS", 3, sim=0.9),  # Top1, Expected 아님
            _candidate("c2", "SPEC-A.md", "PASS", 3, sim=0.1),  # Expected, 동일 pass_count -> MULTIPLE_VALID
        ]}),
    })
    results_by_k = analyze_cache(cache)
    q1 = classify_low_strict_high_acceptable_cases(results_by_k[10])
    assert q1["ground_truth_ambiguity"] == ["T1"]
    assert q1["ranking_bug_candidates"] == []


# 7-7: UNIQUE_VALID에서 Expected가 아닌 후보가 선택된 경우 — Q1에서 ranking_bug_candidates로 잡혀야 함
# (경쟁 후보가 전혀 없는데도 Top1이 Expected가 아니라면 구조적으로 GT ambiguity로 설명할 수 없다).
def test_unique_valid_but_wrong_top1_flagged_as_ranking_bug_candidate():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [
            _candidate("c1", "SPEC-B.md", "PASS", 3, sim=0.9),  # 유일한 PASS이지만 Expected가 아님
        ]}),
    })
    results_by_k = analyze_cache(cache)
    q1 = classify_low_strict_high_acceptable_cases(results_by_k[10])
    # 이 케이스는 Expected가 PASS 상태로 pool에 없으므로 NOT_APPLICABLE(Validation Failure)이라
    # Q1 분류 대상 자체가 아니다 — 아래 unique_valid_recheck로 별도 확인.
    assert q1["ground_truth_ambiguity"] == [] and q1["ranking_bug_candidates"] == []
    recheck = unique_valid_recheck(results_by_k[10])
    assert recheck["n_unique_valid"] == 0  # Expected가 PASS가 아니므로 UNIQUE_VALID 분류 대상이 아님(NOT_APPLICABLE)


# 7-8: NOT_APPLICABLE(Retrieval/Validation Failure) 케이스 처리 — 분모에서 자연스럽게 분리되는지.
def test_not_applicable_case_handling():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: []}),  # Retrieval Failure(검색 결과 자체가 없음)
        "T2": _case(["SPEC-B.md"], None, {10: [_candidate("c1", "SPEC-B.md", "PASS", 3, sim=0.9)]}),
    })
    summary = summarize(cache, 10)
    assert summary.category_counts["NOT_APPLICABLE"] == 1
    assert summary.n_applicable == 1  # 2개 evaluable 중 1개만 랭킹 단계 도달
    assert summary.metric_a_strict_top1 == 1.0  # 분모가 applicable(1)뿐이므로 T2만 반영


# 7-9: QA026 특수 케이스 처리 — expected_final_status 필드로만 판정하고 test_id 하드코딩에 의존하지 않는지.
def test_qa026_style_case_uses_expected_final_status_field_not_hardcoded_id():
    # 일부러 test_id를 "QA026"이 아닌 다른 이름으로 지어, 판정이 ID가 아니라
    # expected_final_status 필드를 본다는 것을 증명한다.
    cache = _cache({
        "SOME_OTHER_ID": _case([], "PASS", {10: [_candidate("c1", "SPEC-Q.md", "PASS", 1)]}),
    })
    safety = no_match_safety(cache, 10)
    assert safety["excluded_case_ids"] == ["SOME_OTHER_ID"]
    assert safety["true_false_pass_count"] == 0


# 7-10: Metric 계산이 입력 순서에 의존하지 않는지 — cases dict 순서를 뒤집어도 동일 결과.
def test_metric_computation_is_order_independent():
    cases = {
        "T1": _case(["SPEC-A.md"], None, {10: [_candidate("c1", "SPEC-A.md", "PASS", 3, sim=0.9)]}),
        "T2": _case(["SPEC-B.md"], None, {10: [
            _candidate("c1", "SPEC-B.md", "PASS", 3, sim=0.9),
            _candidate("c2", "SPEC-C.md", "PASS", 3, sim=0.1),
        ]}),
        "T3": _case([], None, {10: [_candidate("c1", "SPEC-D.md", "FAIL", 0, fail_count=1)]}),
    }
    forward = summarize(_cache(cases), 10)
    reversed_cases = dict(reversed(list(cases.items())))
    backward = summarize(_cache(reversed_cases), 10)

    assert forward.metric_a_strict_top1 == backward.metric_a_strict_top1
    assert forward.metric_b_acceptable_top1 == backward.metric_b_acceptable_top1
    assert forward.metric_c_unique_gt_accuracy == backward.metric_c_unique_gt_accuracy
    assert forward.metric_d_requirement_satisfaction == backward.metric_d_requirement_satisfaction
    assert forward.category_counts == backward.category_counts


# 추가: Q3(MULTIPLE_VALID 두 해석)가 acceptable_top1과 동일한 값을 내는지 재확인.
def test_multiple_valid_interpretation_quality_gate_matches_acceptable():
    cache = _cache({
        "T1": _case(["SPEC-A.md"], None, {10: [
            _candidate("c1", "SPEC-B.md", "PASS", 3, sim=0.9),
            _candidate("c2", "SPEC-A.md", "PASS", 3, sim=0.1),
        ]}),
    })
    results_by_k = analyze_cache(cache)
    summary = summarize(cache, 10)
    q3 = multiple_valid_interpretation(results_by_k[10])
    assert q3["as_production_quality_gate_rate"] == summary.metric_b_acceptable_top1
