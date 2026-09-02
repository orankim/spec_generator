"""
k=10(Previous Production) vs k=15(New Production) 비교 — 이미 실측된 real Ollama
캐시(benchmark_results/ranking_failure_cache.json, 56케이스 x k=[5,10,15,20])를
재사용한다(Ollama 호출 없음). production의 select_best_candidate()를 캐시 dict에서
복원한 실제 CandidateEquipment 객체에 그대로 호출해 Top1/3/5/10을 얻는다(재구현 없음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agent.candidate_matcher import select_best_candidate  # noqa: E402
from agent.schemas import CandidateEquipment  # noqa: E402
from scripts.ground_truth_ambiguity_lib import analyze_cache, compute_metrics  # noqa: E402

_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"


def _to_candidate(d: dict) -> CandidateEquipment:
    return CandidateEquipment(
        candidate_id=d["candidate_id"],
        source_document=d["source_document"],
        manufacturer=d.get("manufacturer"),
        model=d.get("model"),
        status=d["status"],
        pass_count=d["pass_count"],
        unknown_count=d["unknown_count"],
        fail_count=d["fail_count"],
        rag_similarity_score=d.get("rag_similarity_score"),
        matches=[],
    )


def _top_n(candidates: List[CandidateEquipment], n: int) -> List[CandidateEquipment]:
    pool = list(candidates)
    top = []
    for _ in range(min(n, len(pool))):
        chosen = select_best_candidate(pool)
        if chosen is None:
            break
        top.append(chosen)
        pool = [c for c in pool if c.candidate_id != chosen.candidate_id]
    return top


def compute_metrics_for_k(cache: dict, k: str) -> Dict:
    evaluable_ids = [cid for cid, c in cache["cases"].items() if c.get("expected_spec_ids")]
    n = len(evaluable_ids)

    n_retrieval_hit = 0
    n_candidate_extraction_hit = 0
    n_expected_pass = 0
    n_strict_top1 = 0
    n_top3 = 0
    n_top5 = 0
    n_top10 = 0
    pool_sizes = []

    for cid in evaluable_ids:
        case = cache["cases"][cid]
        expected = set(case["expected_spec_ids"])
        raw_candidates = case["by_k"][k]["candidates"]
        pool_sizes.append(len(raw_candidates))

        docs_in_pool = {c["source_document"] for c in raw_candidates}
        if expected & docs_in_pool:
            n_retrieval_hit += 1
            # Candidate Extraction Hit Rate: build_candidates()는 검색된 모든 고유
            # source_document를 무조건 후보화하므로, Retrieval Hit이면 항상
            # Candidate Extraction Hit이기도 하다(불일치 시 원인 조사 대상).
            n_candidate_extraction_hit += 1

        expected_pass = any(c["source_document"] in expected and c["status"] == "PASS" for c in raw_candidates)
        if expected_pass:
            n_expected_pass += 1

        candidates = [_to_candidate(c) for c in raw_candidates]
        top10 = _top_n(candidates, 10)
        top10_docs = [c.source_document for c in top10]

        if top10_docs and top10_docs[0] in expected:
            n_strict_top1 += 1  # 주의: 이 값은 "43케이스 전체 대비"(end-to-end) 비율이다.
            # ground_truth_ambiguity_lib의 공식 Strict Top1 Rate는 분모가 다르다(랭킹
            # 단계에 도달한 케이스만, Retrieval/Validation Failure 제외) — main()에서
            # 그 공식 값을 별도로 함께 출력한다. 두 정의를 섞지 않기 위해 이 값은
            # "top1_end_to_end_rate"로만 부른다(아래 리턴 dict 참고).
        if any(d in expected for d in top10_docs[:3]):
            n_top3 += 1
        if any(d in expected for d in top10_docs[:5]):
            n_top5 += 1
        if any(d in expected for d in top10_docs[:10]):
            n_top10 += 1

    return {
        "k": k,
        "n_evaluable": n,
        "retrieval_recall": n_retrieval_hit / n,
        "candidate_extraction_hit_rate": n_candidate_extraction_hit / n,
        "invariant_recall_eq_extraction": n_retrieval_hit == n_candidate_extraction_hit,
        "expected_candidate_pass_rate": n_expected_pass / n,
        "top1_end_to_end_rate": n_strict_top1 / n,
        "top3": n_top3 / n,
        "top5": n_top5 / n,
        "top10": n_top10 / n,
        "avg_candidate_pool_size": sum(pool_sizes) / len(pool_sizes),
    }


def compute_miss_transition(cache: dict) -> List[Dict]:
    evaluable_ids = sorted(cid for cid, c in cache["cases"].items() if c.get("expected_spec_ids"))
    rows = []
    for cid in evaluable_ids:
        case = cache["cases"][cid]
        expected = set(case["expected_spec_ids"])
        k10_docs = {c["source_document"] for c in case["by_k"]["10"]["candidates"]}
        k15_docs = {c["source_document"] for c in case["by_k"]["15"]["candidates"]}
        hit10 = bool(expected & k10_docs)
        hit15 = bool(expected & k15_docs)
        if hit10 and hit15:
            change = "HIT -> HIT"
        elif not hit10 and hit15:
            change = "MISS -> HIT"
        elif hit10 and not hit15:
            change = "HIT -> MISS (REGRESSION)"
        else:
            change = "MISS -> MISS"
        if change != "HIT -> HIT":
            rows.append({"test_id": cid, "k10": "HIT" if hit10 else "MISS", "k15": "HIT" if hit15 else "MISS", "change": change})
    return rows


def main() -> None:
    cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))

    print("=" * 90)
    print("k=10 vs k=15 핵심 비교 (real Ollama 캐시 재사용, 추가 호출 없음)")
    print("=" * 90)
    m10 = compute_metrics_for_k(cache, "10")
    m15 = compute_metrics_for_k(cache, "15")
    for m in (m10, m15):
        print(f"\n--- k={m['k']} ---")
        for key, val in m.items():
            print(f"  {key}: {val}")

    # 공식 Strict/Acceptable/Unique GT Accuracy — scripts/ground_truth_ambiguity_lib.py의
    # 기존 정의를 그대로 재사용한다(분모가 다른 새 정의를 여기서 만들지 않는다).
    results_by_k = analyze_cache(cache)
    official = {}
    for k_int in (10, 15):
        summary = compute_metrics(results_by_k[k_int])
        official[k_int] = summary
        print(f"\n--- k={k_int} 공식 Ground Truth Ambiguity 지표(ground_truth_ambiguity_lib 재사용) ---")
        print(f"  strict_top1_rate(applicable={summary.n_evaluable - summary.category_counts.get('NOT_APPLICABLE', 0)}): {summary.strict_top1_rate}")
        print(f"  acceptable_top1_rate: {summary.acceptable_top1_rate}")
        print(f"  requirement_satisfaction_top1_rate: {summary.requirement_satisfaction_top1_rate}")
        print(f"  ground_truth_unique_accuracy(n={summary.n_unique_valid}): {summary.ground_truth_unique_accuracy}")

    print("\n" + "=" * 90)
    print("Retrieval MISS 전이(k=10 -> k=15), HIT->HIT 케이스는 생략")
    print("=" * 90)
    rows = compute_miss_transition(cache)
    for r in rows:
        print(f"  {r['test_id']:8s} k10={r['k10']:4s} k15={r['k15']:4s} -> {r['change']}")

    regressions = [r for r in rows if "REGRESSION" in r["change"]]
    print(f"\nRetrieval Regression(HIT->MISS) 건수: {len(regressions)}")

    out = {
        "k10": m10,
        "k15": m15,
        "official_ambiguity_metrics": {
            str(k): {
                "strict_top1_rate": s.strict_top1_rate,
                "acceptable_top1_rate": s.acceptable_top1_rate,
                "requirement_satisfaction_top1_rate": s.requirement_satisfaction_top1_rate,
                "ground_truth_unique_accuracy": s.ground_truth_unique_accuracy,
                "n_unique_valid": s.n_unique_valid,
            }
            for k, s in official.items()
        },
        "miss_transitions": rows,
        "n_retrieval_regressions": len(regressions),
    }
    out_path = _REPO_ROOT / "benchmark_results" / "k_per_query_10_vs_15_comparison.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장됨: {out_path}")


if __name__ == "__main__":
    main()
