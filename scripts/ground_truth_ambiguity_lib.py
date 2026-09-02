"""
Ground Truth Ambiguity 분류 + 신규 평가 지표(Strict/Acceptable/Requirement Satisfaction/
Ground Truth Unique Accuracy)의 순수 로직 모듈. Ollama를 전혀 호출하지 않는다 —
scripts/ranking_failure_benchmark.py가 실제 Ollama로 만든 candidate pool 캐시
(benchmark_results/ranking_failure_cache.json)를 그대로 재사용한다(요청서 19절:
Ollama 호출 최소화 — 이 캐시는 production build_candidates()가 이미 계산해 둔 값이므로
다시 검색/판정하지 않는다).

Production 정렬 로직(agent/candidate_matcher.py::select_best_candidate,
_STATUS_RANK)은 이 파일에서 재구현하지 않는다 — "Top1이 무엇인가"는 캐시에 이미
`chosen_candidate_id`로 저장되어 있고, 이 값 자체가 production 함수의 실제 반환값이다
(scripts/ranking_failure_benchmark.py::analyze()가 이미 이 값을 production
select_best_candidate() 재호출로 검증했다 — "Policy A 검증" 절 참고).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from scripts.ranking_failure_benchmark_lib import (
    FUNNEL_RANKING_FAILURE,
    FUNNEL_RETRIEVAL_FAILURE,
    FUNNEL_SUCCESS,
    FUNNEL_VALIDATION_FAILURE,
    classify_ambiguity,
    classify_funnel,
)

# ==========================================
# Ground Truth Ambiguity Category (요청서 5절)
# ==========================================
UNIQUE_VALID = "UNIQUE_VALID"
MULTIPLE_VALID = "MULTIPLE_VALID"
EXPECTED_CLEARLY_BETTER = "EXPECTED_CLEARLY_BETTER"
TOP1_CLEARLY_BETTER = "TOP1_CLEARLY_BETTER"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NOT_APPLICABLE = "NOT_APPLICABLE"  # Retrieval/Validation Failure — 이 분류의 대상이 아님


class _CandidateView:
    """캐시 dict를 ranking_failure_benchmark_lib의 함수(속성 접근 기반)에 그대로
    넣기 위한 최소 래퍼. 값 재계산 없음 — 전부 1단계 real Ollama pass가 이미 계산해
    캐시에 저장한 값을 그대로 옮긴다."""

    def __init__(self, d: Dict[str, Any]):
        self.candidate_id = d["candidate_id"]
        self.source_document = d["source_document"]
        self.status = d["status"]
        self.pass_count = d["pass_count"]
        self.unknown_count = d["unknown_count"]
        self.fail_count = d["fail_count"]
        self.rag_similarity_score = d["rag_similarity_score"]
        self.matches = d["matches"]


@dataclass
class GroundTruthAmbiguityResult:
    test_id: str
    k: int
    category: str
    funnel_stage: str  # RETRIEVAL_FAILURE / VALIDATION_FAILURE / RANKING_FAILURE / SUCCESS
    expected_source: Optional[str] = None
    top1_source: Optional[str] = None
    other_pass_candidates: List[str] = field(default_factory=list)
    # 신규 지표 계산용 boolean
    strict_top1: bool = False       # Top1 == Expected(정확히 그 SPEC)
    acceptable_top1: bool = False   # Top1 == Expected 이거나, Top1이 Expected와 동등하게 유효(MULTIPLE_VALID/BOTH_VALID)
    requirement_satisfaction_top1: bool = False  # Top1.status == PASS (Expected와 무관)


def classify_case(
    test_id: str,
    k: int,
    candidates: List[Dict[str, Any]],
    expected_spec_ids: Set[str],
) -> GroundTruthAmbiguityResult:
    """candidates: 캐시에 저장된 candidate dict 목록(해당 case, 해당 k). Retrieval/
    Validation Failure 케이스는 UNIQUE_VALID/MULTIPLE_VALID 등 판단 대상이 아니므로
    NOT_APPLICABLE로 남긴다(요청서 §5가 이 분류를 "PASS 대 PASS" 비교로 전제하므로)."""
    views = [_CandidateView(c) for c in candidates]
    classification = classify_funnel(views, expected_spec_ids)

    requirement_satisfaction_top1 = bool(
        classification.top1 is not None and classification.top1.status == "PASS"
    )

    if classification.stage in (FUNNEL_RETRIEVAL_FAILURE, FUNNEL_VALIDATION_FAILURE):
        return GroundTruthAmbiguityResult(
            test_id=test_id, k=k, category=NOT_APPLICABLE, funnel_stage=classification.stage,
            requirement_satisfaction_top1=requirement_satisfaction_top1,
        )

    # 여기부터는 Expected가 PASS로 존재(FUNNEL_SUCCESS 또는 FUNNEL_RANKING_FAILURE).
    expected_pass = [c for c in classification.expected_candidates_in_pool if c.status == "PASS"]
    # pass_count가 가장 높은 expected 후보를 대표로 사용(동일 이름이 여러 SPEC에 걸쳐
    # 있는 경우에도 결정론적으로 하나를 고른다).
    expected_rep = max(expected_pass, key=lambda c: c.pass_count)

    other_pass = [c for c in views if c.status == "PASS" and c.source_document not in expected_spec_ids]

    if not other_pass:
        category = UNIQUE_VALID
    elif classification.stage == FUNNEL_SUCCESS:
        # Expected가 이겼지만 다른 PASS 후보도 있었다 — 여러 유효 후보 중 하나가
        # (마침 Expected가) 선택된 경우.
        category = MULTIPLE_VALID
    else:
        # RANKING_FAILURE: Expected와 실제 Top1을 구조적으로 비교(요청서 16절과 동일 로직).
        ambiguity = classify_ambiguity(expected_rep, classification.top1)
        category = {
            "BOTH_VALID": MULTIPLE_VALID,
            "EXPECTED_CLEARLY_BETTER": EXPECTED_CLEARLY_BETTER,
            "TOP1_CLEARLY_BETTER": TOP1_CLEARLY_BETTER,
            "INSUFFICIENT_EVIDENCE": INSUFFICIENT_EVIDENCE,
        }[ambiguity]

    strict_top1 = classification.stage == FUNNEL_SUCCESS
    acceptable_top1 = strict_top1 or category == MULTIPLE_VALID

    return GroundTruthAmbiguityResult(
        test_id=test_id,
        k=k,
        category=category,
        funnel_stage=classification.stage,
        expected_source=expected_rep.source_document,
        top1_source=classification.top1.source_document if classification.top1 else None,
        other_pass_candidates=sorted(c.source_document for c in other_pass),
        strict_top1=strict_top1,
        acceptable_top1=acceptable_top1,
        requirement_satisfaction_top1=requirement_satisfaction_top1,
    )


@dataclass
class MetricsSummary:
    k: int
    n_evaluable: int
    strict_top1_rate: Optional[float]
    acceptable_top1_rate: Optional[float]
    requirement_satisfaction_top1_rate: Optional[float]
    n_unique_valid: int
    ground_truth_unique_accuracy: Optional[float]  # UNIQUE_VALID 케이스만 대상 strict top1
    category_counts: Dict[str, int]


def compute_metrics(results: List[GroundTruthAmbiguityResult]) -> MetricsSummary:
    applicable = [r for r in results if r.category != NOT_APPLICABLE]
    n = len(applicable)
    k = results[0].k if results else -1

    category_counts: Dict[str, int] = {}
    for cat in (UNIQUE_VALID, MULTIPLE_VALID, EXPECTED_CLEARLY_BETTER, TOP1_CLEARLY_BETTER, INSUFFICIENT_EVIDENCE):
        category_counts[cat] = sum(1 for r in applicable if r.category == cat)
    category_counts[NOT_APPLICABLE] = sum(1 for r in results if r.category == NOT_APPLICABLE)

    unique_valid_cases = [r for r in applicable if r.category == UNIQUE_VALID]

    return MetricsSummary(
        k=k,
        n_evaluable=len(results),
        strict_top1_rate=(sum(r.strict_top1 for r in applicable) / n) if n else None,
        acceptable_top1_rate=(sum(r.acceptable_top1 for r in applicable) / n) if n else None,
        requirement_satisfaction_top1_rate=(
            sum(r.requirement_satisfaction_top1 for r in results) / len(results) if results else None
        ),
        n_unique_valid=len(unique_valid_cases),
        ground_truth_unique_accuracy=(
            sum(r.strict_top1 for r in unique_valid_cases) / len(unique_valid_cases) if unique_valid_cases else None
        ),
        category_counts=category_counts,
    )


def load_cache(cache_path) -> Dict[str, Any]:
    import json
    from pathlib import Path

    return json.loads(Path(cache_path).read_text(encoding="utf-8"))


def analyze_cache(cache: Dict[str, Any]) -> Dict[int, List[GroundTruthAmbiguityResult]]:
    """캐시 전체(모든 k, 모든 case)를 분류한다. 이 함수는 Ollama를 호출하지 않는다."""
    results_by_k: Dict[int, List[GroundTruthAmbiguityResult]] = {}
    k_values = cache["k_values"]
    for k in k_values:
        rows = []
        for test_id, case in cache["cases"].items():
            expected_spec_ids = set(case["expected_spec_ids"])
            if not expected_spec_ids:
                continue  # No-Match 케이스는 이 분류 대상이 아님(별도 Safety 분석)
            entry = case["by_k"][str(k)]
            rows.append(classify_case(test_id, k, entry["candidates"], expected_spec_ids))
        results_by_k[k] = rows
    return results_by_k
