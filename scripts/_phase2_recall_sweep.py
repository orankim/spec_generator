"""
Phase 2 recall k-sweep — full_retrieval_recall_benchmark.py와 동일한 로직을 쓰되,
이미 만들어진 production chroma_db_specs/를 재사용해(재구축 30분 생략) 반복 실행
비용을 줄인다. T009는 이 환경의 LLM(qwen2.5:3b, production 의도값 qwen2.5:14b보다
훨씬 작음)이 구조화 출력에서 무한 반복 후 JSON이 잘리는 환경 한계로 스킵한다
(sample_specs 데이터와 무관 — Requirement Parsing 단계에서 발생, Retrieval 이전).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

from agent import spec_retriever
from agent.candidate_matcher import build_candidates, select_best_candidate
from agent.requirement_parser import parse_requirement_text
from agent.paths import DEFAULT_CHROMA_DB_PATH
from tests.regression_lib import RegressionRunResult, candidate_name

from scripts.full_retrieval_recall_benchmark_lib import (
    build_equipment_name_to_spec_ids,
    candidate_level_documents,
    compute_recall_at_k,
    discover_benchmark_cases,
    evaluate_recall_for_case,
    resolve_expected_spec_ids,
)

SKIP_CASE_IDS = {"T009"}  # 이 환경 LLM(qwen2.5:3b) 구조화 출력 실패 — 데이터 무관, Requirement Parsing 단계


def main() -> None:
    k_values = [5, 10, 15, 20, 25]
    all_cases = discover_benchmark_cases()
    cases = [c for c in all_cases if c["test_id"] not in SKIP_CASE_IDS]
    print(f"cases: {len(cases)} (skipped: {sorted(SKIP_CASE_IDS)})")
    name_to_spec_ids = build_equipment_name_to_spec_ids()

    parsed = {}
    for i, case in enumerate(cases, start=1):
        t0 = time.monotonic()
        try:
            requirement = parse_requirement_text(case["user_query"])
        except Exception as e:
            print(f"  [{i}/{len(cases)}] {case['test_id']:8s} PARSE FAILED: {e}")
            continue
        parsed[case["test_id"]] = requirement
        print(f"  [{i}/{len(cases)}] {case['test_id']:8s} parsed in {time.monotonic()-t0:.1f}s")

    per_k_rows = {k: [] for k in k_values}
    for k in k_values:
        print(f"\n--- k={k} ---")
        for case in cases:
            requirement = parsed.get(case["test_id"])
            if requirement is None:
                continue
            expected_spec_ids = resolve_expected_spec_ids(case, name_to_spec_ids)
            retrieved_docs = spec_retriever.retrieve_for_requirement(
                requirement, db_path=DEFAULT_CHROMA_DB_PATH, k_per_query=k
            )
            doc_scores = candidate_level_documents(retrieved_docs)
            recall_eval = evaluate_recall_for_case(expected_spec_ids, doc_scores)
            candidates = build_candidates(requirement, retrieved_docs)
            chosen = select_best_candidate(candidates)
            per_k_rows[k].append((case["test_id"], recall_eval))
            hit_disp = "HIT " if recall_eval.hit else ("MISS" if recall_eval.evaluable else "N/A ")
            print(f"  {case['test_id']:8s} {hit_disp} rank={recall_eval.rank} final={candidate_name(chosen) if chosen else None!r}")

    print("\n" + "=" * 70)
    print("k별 Recall@K 요약")
    print("=" * 70)
    for k in k_values:
        summary = compute_recall_at_k(k, per_k_rows[k])
        print(
            f"k={k:3d}  recall={summary.recall:.3f}  hit={summary.n_hit}/{summary.n_evaluable}  "
            f"miss={summary.n_miss}  avg_rank={summary.avg_rank}  worst_rank={summary.worst_rank}  mrr={summary.mrr}"
        )


if __name__ == "__main__":
    main()
