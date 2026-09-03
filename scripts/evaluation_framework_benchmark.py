"""
Evaluation Framework 실측 실행 — Ollama 호출 없음. 기존 real Ollama 캐시
(benchmark_results/ranking_failure_cache.json, k_per_query=15가 포함된 k=[5,10,15,20]
캐시)를 재사용한다. 캐시 환경 metadata(embedding_model/llm_model/spec_count/
chunk_count)가 현재 corpus와 일치하는지 먼저 확인하고, 불일치하면 경고한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.evaluation_framework_lib import (  # noqa: E402
    build_grouped_report,
    classify_low_strict_high_acceptable_cases,
    multiple_valid_interpretation,
    summarize,
    unique_valid_recheck,
)
from scripts.ground_truth_ambiguity_lib import analyze_cache  # noqa: E402

_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"


def _verify_cache_matches_current_state(cache: dict) -> None:
    from glob import glob

    env = cache.get("environment", {})
    current_spec_count = len(glob(str(_REPO_ROOT / "sample_specs" / "SPEC-*.md")))
    issues = []
    if env.get("embedding_model") != "bge-m3":
        issues.append(f"embedding_model={env.get('embedding_model')} (기대: bge-m3)")
    if env.get("llm_model") != "qwen2.5:3b":
        issues.append(f"llm_model={env.get('llm_model')} (기대: qwen2.5:3b)")
    if env.get("indexed_spec_count") != current_spec_count:
        issues.append(f"indexed_spec_count={env.get('indexed_spec_count')} (현재 corpus: {current_spec_count})")
    if 15 not in cache.get("k_values", []):
        issues.append(f"k_values={cache.get('k_values')}에 15가 없음(현재 production 기본값)")
    if issues:
        print("[경고] 캐시가 현재 상태와 불일치합니다 — 아래 항목 재확인 필요:")
        for i in issues:
            print(f"   - {i}")
    else:
        print(f"캐시 검증 통과: embedding={env.get('embedding_model')}, llm={env.get('llm_model')}, "
              f"spec_count={env.get('indexed_spec_count')}(현재 {current_spec_count}과 일치), k_values={cache.get('k_values')}")


def main() -> None:
    cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    print("=" * 90)
    print("Evaluation Framework 정밀 분석 (real Ollama 캐시 재사용, Ollama 호출 없음)")
    print("=" * 90)
    _verify_cache_matches_current_state(cache)

    for k in (10, 15):
        print(f"\n--- k={k} ---")
        summary = summarize(cache, k)
        print(f"  Metric A (Strict Expected Top1): {summary.metric_a_strict_top1}")
        print(f"  Metric B (Acceptable Top1): {summary.metric_b_acceptable_top1}")
        print(f"  Metric C (Unique GT Accuracy): {summary.metric_c_unique_gt_accuracy}")
        print(f"  Metric D (Requirement Satisfaction): {summary.metric_d_requirement_satisfaction}")
        print(f"  Metric E (No-Match Safety): {summary.metric_e_no_match_safety}")
        print(f"  category_counts: {summary.category_counts}")

        results_by_k = analyze_cache(cache)
        q1 = classify_low_strict_high_acceptable_cases(results_by_k[k])
        print(f"  Q1 (Strict False & Acceptable True 분류): GT_ambiguity={len(q1['ground_truth_ambiguity'])}건 "
              f"ranking_bug_candidates={len(q1['ranking_bug_candidates'])}건 {q1['ranking_bug_candidates']}")
        q2 = unique_valid_recheck(results_by_k[k])
        print(f"  Q2 (UNIQUE_VALID 재확인): {q2}")
        q3 = multiple_valid_interpretation(results_by_k[k])
        print(f"  Q3 (MULTIPLE_VALID 두 해석): {q3}")

    out = {}
    for k in (10, 15):
        summary = summarize(cache, k)
        results_by_k = analyze_cache(cache)
        out[str(k)] = {
            "grouped_report": build_grouped_report(cache, k),
            "q1": classify_low_strict_high_acceptable_cases(results_by_k[k]),
            "q2": unique_valid_recheck(results_by_k[k]),
            "q3": multiple_valid_interpretation(results_by_k[k]),
        }
    out_path = _REPO_ROOT / "benchmark_results" / "evaluation_framework_analysis.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장됨: {out_path}")


if __name__ == "__main__":
    main()
