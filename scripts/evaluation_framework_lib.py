"""
Evaluation Framework 정밀 분석(요청서 3~6절) — 순수 함수 모듈, Ollama 호출 없음.

새 Production 정책이나 새 판정 로직을 만들지 않는다. 이 모듈은 오직
scripts/ground_truth_ambiguity_lib.py(Turn 6에서 이미 만든, production
select_best_candidate()/build_candidates() 결과를 그대로 재사용하는 분류기)의
결과를 다섯 개 이름 붙은 Metric(A~E)으로 재정리하고, Metric 간 관계(Q1~Q3)를
데이터로 답한다.

Metric 정의(요청서 4절):
  A. Strict Expected Top1 Accuracy — Top1 == Expected(정확히 그 SPEC).
     기존 ground_truth_ambiguity_lib의 strict_top1_rate와 동일 정의(분모는
     "랭킹 단계에 도달한 evaluable 케이스"만 — Retrieval/Validation Failure 제외).
  B. Acceptable Top1 Accuracy — Top1 == Expected 이거나, Top1이 Expected와
     동등하게 유효(MULTIPLE_VALID)한 경우. 기존 acceptable_top1_rate 재사용.
  C. Unique Ground Truth Accuracy — UNIQUE_VALID 케이스만 대상으로 한 Strict
     Accuracy. 기존 ground_truth_unique_accuracy 재사용.
  D. Requirement Satisfaction Top1 — Top1.status == PASS(Expected와 무관).
     기존 requirement_satisfaction_top1_rate 재사용.
  E. No-Match Safety — No-Match(정답 없음) 케이스에서 False PASS가 없는지.
     QA026(expected_final_status=PASS로 설계된 케이스)은 이 판정에서 제외한다
     — 임의 판단이 아니라 Ground Truth 자체의 expected_final_status 필드로
     확인한 사실이다(Turn 6/7에서 이미 확립).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from scripts.ground_truth_ambiguity_lib import (
    MULTIPLE_VALID,
    UNIQUE_VALID,
    GroundTruthAmbiguityResult,
    MetricsSummary,
    analyze_cache,
    compute_metrics,
)

# QA026: "300 μm 이하"(문맥 단어 없는 단독 숫자) 질의 — GT 자체가
# expected_final_status=PASS로 설계한 케이스(Turn 6에서 GT 필드로 직접 확인).
# No-Match Safety 판정에서는 제외한다. 하드코딩이 아니라, 아래 no_match_safety()가
# 매 실행마다 cache의 expected_final_status 필드를 직접 읽어 재확인한다 — 이
# 상수는 "왜 제외하는지"를 설명하는 참고용 이름일 뿐, 판정 로직은 필드 값을 본다.
_QA026_NOTE = "expected_final_status == 'PASS'인 No-Match 케이스는 설계상 PASS 의도이므로 Safety 위반 판정에서 제외한다."


@dataclass
class EvaluationFrameworkSummary:
    k: int
    metric_a_strict_top1: Optional[float]
    metric_b_acceptable_top1: Optional[float]
    metric_c_unique_gt_accuracy: Optional[float]
    metric_d_requirement_satisfaction: Optional[float]
    metric_e_no_match_safety: Dict[str, Any]
    category_counts: Dict[str, int]
    n_evaluable: int
    n_applicable: int  # Retrieval/Validation Failure(NOT_APPLICABLE) 제외한 랭킹 단계 도달 케이스 수


def no_match_safety(cache: Dict[str, Any], k: int) -> Dict[str, Any]:
    """Metric E. cache['cases']의 expected_spec_ids가 비어있는 케이스 전체를 No-Match로
    본다(하드코딩된 ID 목록을 쓰지 않는다). 그중 expected_final_status == 'PASS'인
    케이스만 안전성 판정에서 제외한다 — 이 필드 자체가 GT의 설계 의도를 담고 있다."""
    no_match_ids = sorted(cid for cid, c in cache["cases"].items() if not c.get("expected_spec_ids"))
    excluded = [cid for cid in no_match_ids if cache["cases"][cid].get("expected_final_status") == "PASS"]
    true_no_match_ids = [cid for cid in no_match_ids if cid not in excluded]

    raw_pass_ids = []
    false_pass_ids = []
    for cid in no_match_ids:
        candidates = cache["cases"][cid]["by_k"][str(k)]["candidates"]
        has_pass = any(c["status"] == "PASS" for c in candidates)
        if has_pass:
            raw_pass_ids.append(cid)
            if cid not in excluded:
                false_pass_ids.append(cid)

    return {
        "n_no_match_total": len(no_match_ids),
        "n_excluded_by_design": len(excluded),
        "excluded_case_ids": excluded,
        "n_true_no_match": len(true_no_match_ids),
        "raw_pass_count": len(raw_pass_ids),
        "raw_pass_case_ids": raw_pass_ids,
        "true_false_pass_count": len(false_pass_ids),
        "true_false_pass_case_ids": false_pass_ids,
    }


def status_priority_violations(cache: Dict[str, Any], k: int) -> List[str]:
    """PASS > PARTIAL > FAIL 정책 위반 케이스 id 목록(위반 없으면 빈 리스트).
    production select_best_candidate()를 그대로 재사용한다(재구현 아님)."""
    from agent.candidate_matcher import select_best_candidate
    from agent.schemas import CandidateEquipment

    def _to_candidate(d: dict) -> CandidateEquipment:
        return CandidateEquipment(
            candidate_id=d["candidate_id"], source_document=d["source_document"],
            manufacturer=d.get("manufacturer"), model=d.get("model"), status=d["status"],
            pass_count=d["pass_count"], unknown_count=d["unknown_count"], fail_count=d["fail_count"],
            rag_similarity_score=d.get("rag_similarity_score"), matches=[],
        )

    violations = []
    for cid, case in cache["cases"].items():
        raw = case["by_k"][str(k)]["candidates"]
        if not raw:
            continue
        candidates = [_to_candidate(d) for d in raw]
        chosen = select_best_candidate(candidates)
        statuses = {c.status for c in candidates}
        expected_status = "PASS" if "PASS" in statuses else ("PARTIAL" if "PARTIAL" in statuses else "FAIL")
        if chosen.status != expected_status:
            violations.append(cid)
    return violations


def summarize(cache: Dict[str, Any], k: int) -> EvaluationFrameworkSummary:
    results_by_k = analyze_cache(cache)
    results = results_by_k[k]
    summary: MetricsSummary = compute_metrics(results)
    safety = no_match_safety(cache, k)

    n_applicable = summary.n_evaluable - summary.category_counts.get("NOT_APPLICABLE", 0)

    return EvaluationFrameworkSummary(
        k=k,
        metric_a_strict_top1=summary.strict_top1_rate,
        metric_b_acceptable_top1=summary.acceptable_top1_rate,
        metric_c_unique_gt_accuracy=summary.ground_truth_unique_accuracy,
        metric_d_requirement_satisfaction=summary.requirement_satisfaction_top1_rate,
        metric_e_no_match_safety=safety,
        category_counts=summary.category_counts,
        n_evaluable=summary.n_evaluable,
        n_applicable=n_applicable,
    )


# ==========================================
# Metric 관계 분석(요청서 5절 Q1~Q3)
# ==========================================


def classify_low_strict_high_acceptable_cases(results: List[GroundTruthAmbiguityResult]) -> Dict[str, List[str]]:
    """Q1: Strict==False 이지만 Acceptable==True인 케이스들을 Ranking Bug 후보와
    Ground Truth Ambiguity로 나눈다. 이 모듈이 새로 "버그다/아니다"를 판단하지
    않는다 — classify_case()가 이미 만들어 둔 category(MULTIPLE_VALID 등)를
    그대로 옮길 뿐이다. category가 MULTIPLE_VALID이면 GT Ambiguity, 그 외
    (EXPECTED_CLEARLY_BETTER/TOP1_CLEARLY_BETTER/INSUFFICIENT_EVIDENCE)면
    Ranking Bug 후보로 분류한다(각각의 정의 자체가 이미 요청서 16절 기준 구조적
    비교 결과다)."""
    ground_truth_ambiguity = []
    ranking_bug_candidates = []
    for r in results:
        if not r.strict_top1 and r.acceptable_top1:
            if r.category == MULTIPLE_VALID:
                ground_truth_ambiguity.append(r.test_id)
            else:
                ranking_bug_candidates.append(r.test_id)
    return {"ground_truth_ambiguity": ground_truth_ambiguity, "ranking_bug_candidates": ranking_bug_candidates}


def unique_valid_recheck(results: List[GroundTruthAmbiguityResult]) -> Dict[str, Any]:
    """Q2: UNIQUE_VALID 케이스에서 Strict Accuracy가 실제로 높은지 재확인한다."""
    unique_cases = [r for r in results if r.category == UNIQUE_VALID]
    correct = [r.test_id for r in unique_cases if r.strict_top1]
    incorrect = [r.test_id for r in unique_cases if not r.strict_top1]
    return {
        "n_unique_valid": len(unique_cases),
        "n_correct": len(correct),
        "correct_case_ids": correct,
        "incorrect_case_ids": incorrect,
        "accuracy": (len(correct) / len(unique_cases)) if unique_cases else None,
    }


def multiple_valid_interpretation(results: List[GroundTruthAmbiguityResult]) -> Dict[str, Any]:
    """Q3: MULTIPLE_VALID을 Strict Accuracy 분모에 포함하는 두 해석을 병렬로 계산한다.
    어느 쪽이 "옳다"고 결정하지 않는다 — 두 숫자를 나란히 보여줄 뿐이다."""
    applicable = [r for r in results if r.category != "NOT_APPLICABLE"]
    n = len(applicable)
    if n == 0:
        return {
            "as_evaluation_metric_strict_rate": None,
            "as_production_quality_gate_rate": None,
            "n_multiple_valid": 0,
        }
    multiple_valid = [r for r in applicable if r.category == MULTIPLE_VALID]
    # 해석 1(Evaluation Metric으로 유지): 기존 정의 그대로 — Top1==Expected만 성공.
    as_evaluation_metric = sum(1 for r in applicable if r.strict_top1) / n
    # 해석 2(Production Quality Gate로 사용): MULTIPLE_VALID은 "여러 정답 중 하나를
    # 골랐다"는 뜻이므로 품질 게이트 관점에서는 성공으로 친다 — 이는 정확히
    # Acceptable Top1의 정의와 같다(별도 재계산이 아니라 같은 개념임을 보여준다).
    as_quality_gate = sum(1 for r in applicable if r.strict_top1 or r.category == MULTIPLE_VALID) / n
    return {
        "as_evaluation_metric_strict_rate": as_evaluation_metric,
        "as_production_quality_gate_rate": as_quality_gate,
        "n_multiple_valid": len(multiple_valid),
        "note": "as_production_quality_gate_rate는 acceptable_top1_rate와 동일한 개념/값이다(재확인용).",
    }


# ==========================================
# 6절: 제안 Regression Result 구조(문서화 목적 — 새 Production 코드 아님)
# ==========================================


def build_grouped_report(cache: Dict[str, Any], k: int) -> Dict[str, Any]:
    summary = summarize(cache, k)
    violations = status_priority_violations(cache, k)
    return {
        "1_exact_match": {"strict_expected_top1": summary.metric_a_strict_top1},
        "2_requirement_correctness": {
            "acceptable_top1": summary.metric_b_acceptable_top1,
            "requirement_satisfaction": summary.metric_d_requirement_satisfaction,
        },
        "3_unique_ground_truth": {"unique_gt_accuracy": summary.metric_c_unique_gt_accuracy},
        "4_safety": {
            "no_match_false_pass": summary.metric_e_no_match_safety["true_false_pass_count"],
            "status_priority_violations": len(violations),
        },
        "5_retrieval": {"category_counts": summary.category_counts, "n_evaluable": summary.n_evaluable},
    }
