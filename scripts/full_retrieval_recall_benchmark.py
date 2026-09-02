"""
Full Retrieval Recall Benchmark — tests/ground_truth/regression_cases.json의 전체
Dataset(T001~T027 + QA001~QA029, 개수 하드코딩 없음)을 실제 Ollama(bge-m3 임베딩 +
.env OLLAMA_MODEL LLM 파싱) + 실제 ChromaDB로 돌려 Production Retrieval의 Recall@K를
측정한다.

Production 코드(agent/spec_retriever.py::retrieve_for_requirement,
agent/candidate_matcher.py::build_candidates/select_best_candidate,
agent/requirement_parser.py::parse_requirement_text)를 있는 그대로 호출하며,
Retrieval 로직이나 Ranking 로직을 이 스크립트가 재구현하지 않는다 — 순수 로직
(Dataset 발견/Expected Candidate 정규화/Recall 계산)은 scripts/
full_retrieval_recall_benchmark_lib.py에 있다.

scripts/retrieval_recall_experiment.py(기존, R1~R5 5개 질의 전용 k 스윕)와는 별개
스크립트다 — 그 파일을 수정하거나 대체하지 않는다. 이 스크립트는 그 5개 질의를
포함한 전체 56개 Ground Truth 질의로 범위를 넓힌 것이며, DB 빌드/실제 파이프라인
호출은 tests/real_rag_lib.py의 헬퍼를 그대로 재사용한다(중복 구현 금지).

사용법:
    .venv/Scripts/python.exe scripts/full_retrieval_recall_benchmark.py
    .venv/Scripts/python.exe scripts/full_retrieval_recall_benchmark.py --k-values 5 10 15 20
    .venv/Scripts/python.exe scripts/full_retrieval_recall_benchmark.py --cases T001 T003 QA007  # 부분 실행(디버그용)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from agent import spec_retriever  # noqa: E402
from agent.candidate_matcher import build_candidates, select_best_candidate  # noqa: E402
from agent.requirement_parser import parse_requirement_text  # noqa: E402
from tests import real_rag_lib as rag  # noqa: E402
from tests.regression_lib import RegressionRunResult, candidate_name, check_requirement_field  # noqa: E402

from scripts.full_retrieval_recall_benchmark_lib import (  # noqa: E402
    build_equipment_name_to_spec_ids,
    candidate_level_documents,
    compute_funnel_summary,
    compute_recall_at_k,
    discover_benchmark_cases,
    discover_sample_spec_files,
    evaluate_recall_for_case,
    resolve_expected_spec_ids,
)

_DB_PATH = str(_REPO_ROOT / "_test_chroma_db_full_benchmark")
_RESULTS_DIR = _REPO_ROOT / "benchmark_results"
_DEFAULT_K_VALUES = [5, 10, 15, 20]


def _classify_miss_stage(
    case: Dict[str, Any],
    requirement,
    doc_scores: Dict[str, Optional[float]],
    candidates,
    expected_spec_ids,
) -> tuple:
    """근거 없이 추측하지 않는다(요청서 14/22절) — 실제로 관찰 가능한 사실만으로
    분류한다. 분류하지 못하면 "D(추정)"로 남기고 근거(무엇을 확인했는지)를 그대로
    적는다. Ground Truth 문제(A)는 이 스크립트가 자동으로 단정하지 않는다 — 사람이
    판단하도록 근거만 남긴다."""
    parsing_problems = []
    for field, expected in (case.get("expected_requirement") or {}).items():
        problem = check_requirement_field(requirement, field, expected)
        if problem:
            parsing_problems.append(problem)
    if parsing_problems:
        return "B. Requirement Parsing 문제", parsing_problems

    candidate_sources = {c.source_document for c in candidates}
    present_but_unmapped = (set(doc_scores.keys()) & expected_spec_ids) - candidate_sources
    if present_but_unmapped:
        return (
            "E. Candidate Mapping 문제",
            [f"{sorted(present_but_unmapped)}가 retrieved_docs에는 있지만 build_candidates() 결과 candidate로 그룹화되지 않음"],
        )

    return (
        "D. Semantic Retrieval 문제(추정 — Ground Truth 문제일 가능성도 배제 안 됨, 사람 확인 필요)",
        [f"expected_spec_ids={sorted(expected_spec_ids)}가 retrieved_docs에 전혀 없음(scored/boost 어느 경로로도 없음)"],
    )


def run_benchmark(k_values: List[int], case_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    print("=" * 90)
    print("환경 점검")
    print("=" * 90)
    env = rag.check_ollama_environment()
    if not env.server_reachable:
        raise SystemExit(f"[BLOCKED] Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        raise SystemExit(f"[BLOCKED] embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")
    print(f"  host={env.ollama_host} embedding_model={env.embedding_model} llm_model={env.llm_model}")
    print(f"  installed_models={env.installed_models}")

    print("\n" + "=" * 90)
    print("Corpus / Dataset 확인 (동적 discovery)")
    print("=" * 90)
    spec_files = discover_sample_spec_files()
    all_cases = discover_benchmark_cases()
    cases = [c for c in all_cases if case_ids is None or c["test_id"] in case_ids]
    print(f"  sample_specs/SPEC-*.md 개수: {len(spec_files)}")
    print(f"  Ground Truth 총 케이스 수: {len(all_cases)} (이번 실행 대상: {len(cases)})")
    name_to_spec_ids = build_equipment_name_to_spec_ids()
    dupes = {k: v for k, v in name_to_spec_ids.items() if len(v) > 1}
    print(f"  고유 장비명 수: {len(name_to_spec_ids)} (중복 이름: {dupes or '없음'})")

    print("\n" + "=" * 90)
    print("실제 bge-m3 임베딩으로 ChromaDB 재생성")
    print("=" * 90)
    stats = rag.build_real_vector_db(_DB_PATH)
    print(f"  chunks={stats.indexed_chunk_count} dim={stats.embedding_dimension} build_seconds={stats.build_seconds:.1f}")

    print("\n" + "=" * 90)
    print(f"질의 {len(cases)}개 실제 LLM 파싱 (1회씩만, 이후 k별 재사용)")
    print("=" * 90)
    parsed: Dict[str, Any] = {}
    parse_timing: Dict[str, float] = {}
    for i, case in enumerate(cases, start=1):
        t0 = time.monotonic()
        requirement = parse_requirement_text(case["user_query"])
        elapsed = time.monotonic() - t0
        parsed[case["test_id"]] = requirement
        parse_timing[case["test_id"]] = elapsed
        n_queries = len(spec_retriever._build_queries(requirement))
        print(f"  [{i}/{len(cases)}] {case['test_id']:8s} parse={elapsed:5.2f}s query_expansion={n_queries}개 items={requirement.inspection_items}")

    print("\n" + "=" * 90)
    print(f"k sweep 실행: {k_values}")
    print("=" * 90)
    per_k_rows: Dict[int, List[Dict[str, Any]]] = {k: [] for k in k_values}
    for k in k_values:
        print(f"\n--- k={k} ---")
        for i, case in enumerate(cases, start=1):
            requirement = parsed[case["test_id"]]
            expected_spec_ids = resolve_expected_spec_ids(case, name_to_spec_ids)

            t0 = time.monotonic()
            retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=stats.db_path, k_per_query=k)
            retrieval_s = time.monotonic() - t0

            doc_scores = candidate_level_documents(retrieved_docs)
            recall_eval = evaluate_recall_for_case(expected_spec_ids, doc_scores)

            t1 = time.monotonic()
            candidates = build_candidates(requirement, retrieved_docs)
            chosen = select_best_candidate(candidates)
            candidate_s = time.monotonic() - t1

            result = RegressionRunResult(requirement, candidates, chosen)
            final_name = candidate_name(chosen) if chosen else None
            final_status = chosen.status if chosen else None
            expected_pass_names = case.get("expected_pass_candidates") or []
            if expected_pass_names:
                final_matches_expected = bool(chosen) and final_name in expected_pass_names and final_status == "PASS"
            else:
                final_matches_expected = final_status == case.get("expected_final_status")

            # Candidate Extraction 단계 hit 여부 — Retrieval에는 있었지만 build_candidates()
            # 결과 candidate로 그룹화되지 않은 경우를 Retrieval HIT과 분리해서 본다(요청서 7-4/8절).
            candidate_sources = {c.source_document for c in candidates}
            candidate_extraction_hit = (
                bool(expected_spec_ids & candidate_sources) if recall_eval.evaluable else None
            )

            miss_stage, miss_evidence = (None, None)
            if recall_eval.evaluable and not recall_eval.hit:
                miss_stage, miss_evidence = _classify_miss_stage(case, requirement, doc_scores, candidates, expected_spec_ids)

            row = {
                "test_id": case["test_id"],
                "name": case.get("name"),
                "user_query": case["user_query"],
                "expected_pass_candidates": expected_pass_names,
                "expected_spec_ids": sorted(expected_spec_ids),
                "evaluable": recall_eval.evaluable,
                "hit": recall_eval.hit,
                "rank": recall_eval.rank,
                "rank_kind": recall_eval.rank_kind,
                "matched_spec": recall_eval.matched_spec,
                "candidate_extraction_hit": candidate_extraction_hit,
                "retrieved_chunk_count": len(retrieved_docs),
                "retrieved_unique_doc_count": len(doc_scores),
                "candidate_count": len(candidates),
                "final_recommendation": final_name,
                "final_status": final_status,
                "final_matches_expected": final_matches_expected,
                "retrieval_s": retrieval_s,
                "candidate_extraction_s": candidate_s,
                "requirement_parsing_s": parse_timing[case["test_id"]],
                "miss_stage": miss_stage,
                "miss_evidence": miss_evidence,
            }
            per_k_rows[k].append(row)
            hit_disp = "HIT " if recall_eval.hit else ("MISS" if recall_eval.evaluable else "N/A ")
            print(f"  [{i}/{len(cases)}] {case['test_id']:8s} {hit_disp} rank={str(recall_eval.rank):>4s}({recall_eval.rank_kind:10s}) final={final_name!r} status={final_status} t={retrieval_s:.2f}s")

    print("\n" + "=" * 90)
    print("k별 Recall@K 요약")
    print("=" * 90)
    summaries = {}
    funnel_summaries = {}
    for k in k_values:
        evals = [(r["test_id"], _row_to_eval(r)) for r in per_k_rows[k]]
        summary = compute_recall_at_k(k, evals)
        summaries[k] = summary
        funnel = compute_funnel_summary(k, per_k_rows[k])
        funnel_summaries[k] = funnel
        print(
            f"  k={k:3d}  recall={_fmt(summary.recall)}  hit={summary.n_hit}/{summary.n_evaluable}  "
            f"miss={summary.n_miss}  avg_rank={_fmt(summary.avg_rank)}  median_rank={_fmt(summary.median_rank)}  "
            f"worst_rank={summary.worst_rank}  mrr={_fmt(summary.mrr)}  boost_only_hit={summary.n_boost_only_hit}"
        )
        print(
            f"         candidate_extraction_hit_rate={_fmt(funnel.candidate_extraction_hit_rate)}  "
            f"final_pass_rate={_fmt(funnel.final_pass_rate)}  expected_top1_rate={_fmt(funnel.expected_candidate_top1_rate)}  "
            f"avg_retrieved_docs={funnel.avg_retrieved_documents:.1f}  avg_candidate_pool={funnel.avg_candidate_pool_size:.1f}  "
            f"no_match_safety_rate={_fmt(funnel.no_match_safety_rate)}"
        )

    # k_per_query(각 확장 질의당 top-k)와 실제 중복제거된 검색 문서 수는 다른 개념이다
    # (여러 확장 질의 + range_boost + inspection_item_boost + 후보 확정 후 전체 문서
    # pull이 합쳐지므로, 최종 결과는 k_per_query보다 훨씬 많아진다) — 요청서 7-2절이
    # 명시적으로 요구한 구분을 raw 데이터에도 남긴다.
    k_vs_retrieved: Dict[int, Dict[str, float]] = {}
    for k in k_values:
        chunk_counts = [r["retrieved_chunk_count"] for r in per_k_rows[k]]
        doc_counts = [r["retrieved_unique_doc_count"] for r in per_k_rows[k]]
        k_vs_retrieved[k] = {
            "avg_retrieved_chunk_count": sum(chunk_counts) / len(chunk_counts) if chunk_counts else 0.0,
            "avg_retrieved_unique_doc_count": sum(doc_counts) / len(doc_counts) if doc_counts else 0.0,
        }

    return {
        "environment": {
            "ollama_host": env.ollama_host,
            "installed_models": env.installed_models,
            "embedding_model": env.embedding_model,
            "embedding_dimension": stats.embedding_dimension,
            "llm_model": env.llm_model,
            "indexed_spec_count": stats.indexed_spec_count,
            "indexed_chunk_count": stats.indexed_chunk_count,
            "db_build_seconds": stats.build_seconds,
        },
        "dataset": {
            "n_spec_files": len(spec_files),
            "n_cases_total": len(all_cases),
            "n_cases_run": len(cases),
            "n_unique_equipment_names": len(name_to_spec_ids),
            "duplicate_equipment_names": {k: sorted(v) for k, v in dupes.items()},
        },
        "k_values": k_values,
        "summaries": {k: vars(s) for k, s in summaries.items()},
        "funnel_summaries": {k: vars(s) for k, s in funnel_summaries.items()},
        "k_vs_retrieved": k_vs_retrieved,
        "rows": per_k_rows,
    }


def _row_to_eval(row: Dict[str, Any]):
    from scripts.full_retrieval_recall_benchmark_lib import RecallEvaluation

    return RecallEvaluation(
        evaluable=row["evaluable"], hit=row["hit"], rank=row["rank"],
        rank_kind=row["rank_kind"], matched_spec=row["matched_spec"],
    )


def _fmt(v: Optional[float]) -> str:
    return f"{v:.3f}" if v is not None else "N/A"


def write_reports(result: Dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    json_path = output_dir / "full_retrieval_recall_latest.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = ["# Full Retrieval Recall Benchmark 결과\n"]
    env = result["environment"]
    md_lines.append("## Environment\n")
    md_lines.append(f"- Ollama host: {env['ollama_host']}")
    md_lines.append(f"- Installed models: {env['installed_models']}")
    md_lines.append(f"- Embedding model: {env['embedding_model']} (dim={env['embedding_dimension']})")
    md_lines.append(f"- LLM model: {env['llm_model']}")
    md_lines.append(f"- Indexed SPEC: {env['indexed_spec_count']}, chunks: {env['indexed_chunk_count']}\n")

    ds = result["dataset"]
    md_lines.append("## Dataset\n")
    md_lines.append(f"- SPEC files: {ds['n_spec_files']}")
    md_lines.append(f"- Total Ground Truth cases: {ds['n_cases_total']} (run: {ds['n_cases_run']})")
    md_lines.append(f"- Unique equipment names: {ds['n_unique_equipment_names']}")
    md_lines.append(f"- Duplicate names: {ds['duplicate_equipment_names'] or '없음'}\n")

    md_lines.append("## K별 Recall@K\n")
    md_lines.append("| K | Recall | HIT | MISS | Avg Rank | Median Rank | Worst Rank | MRR | Boost-only HIT |")
    md_lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k, s in result["summaries"].items():
        md_lines.append(
            f"| {k} | {_fmt(s['recall'])} | {s['n_hit']} | {s['n_miss']} | {_fmt(s['avg_rank'])} | "
            f"{_fmt(s['median_rank'])} | {s['worst_rank'] if s['worst_rank'] is not None else 'N/A'} | "
            f"{_fmt(s['mrr'])} | {s['n_boost_only_hit']} |"
        )
    md_lines.append("")

    md_lines.append("## K별 Pipeline Funnel 요약\n")
    md_lines.append(
        "| K | Retrieval Recall | Candidate Extraction Hit Rate | Final PASS Rate | "
        "Expected Candidate Top1 Rate | Avg Retrieved Documents | Avg Candidate Pool Size | No-Match Safety Rate |"
    )
    md_lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k, f in result["funnel_summaries"].items():
        md_lines.append(
            f"| {k} | {_fmt(f['retrieval_recall'])} | {_fmt(f['candidate_extraction_hit_rate'])} | "
            f"{_fmt(f['final_pass_rate'])} | {_fmt(f['expected_candidate_top1_rate'])} | "
            f"{f['avg_retrieved_documents']:.1f} | {f['avg_candidate_pool_size']:.1f} | "
            f"{_fmt(f['no_match_safety_rate'])} |"
        )
    md_lines.append("")
    md_lines.append(
        "(Avg Retrieved Documents/Avg Candidate Pool Size는 전체 실행 케이스 기준. "
        "Retrieval Recall/Candidate Extraction Hit Rate/Final PASS Rate/Expected Candidate Top1 Rate는 "
        "Expected Candidate가 존재하는 케이스만 대상. No-Match Safety Rate는 Expected Candidate가 없는 "
        "케이스 중 최종 status가 잘못 PASS로 나오지 않은 비율.)\n"
    )

    md_lines.append("## k_per_query vs 실제 검색된 문서 수\n")
    md_lines.append(
        "`k_per_query`는 확장 질의 1개당 semantic top-k 개수이고, 최종 `retrieved_docs`는 "
        "여러 확장 질의 + range_boost + inspection_item_boost + 후보 확정 후 전체 문서 pull이 "
        "합쳐진 결과라 항상 그보다 많다(agent/spec_retriever.py::retrieve_for_requirement 참고).\n"
    )
    md_lines.append("| k_per_query | Avg Retrieved Chunks | Avg Retrieved Unique Documents |")
    md_lines.append("|--:|--:|--:|")
    for k, v in result["k_vs_retrieved"].items():
        md_lines.append(f"| {k} | {v['avg_retrieved_chunk_count']:.1f} | {v['avg_retrieved_unique_doc_count']:.1f} |")
    md_lines.append("")

    md_lines.append("## Query별 결과 (production 기본값 기준 k만 발췌, 전체는 JSON 참고)\n")
    default_k = 10 if 10 in result["rows"] else result["k_values"][0]
    md_lines.append(f"(production default k={default_k})\n")
    md_lines.append("| Test ID | Expected | HIT@default_k | Rank | Final Recommendation | Final Status | Matches Expected |")
    md_lines.append("|---|---|---|---:|---|---|---|")
    for row in result["rows"][default_k]:
        md_lines.append(
            f"| {row['test_id']} | {row['expected_pass_candidates'] or '(N/A)'} | "
            f"{'N/A' if not row['evaluable'] else ('HIT' if row['hit'] else 'MISS')} | "
            f"{row['rank'] if row['rank'] is not None else '-'} | {row['final_recommendation']} | "
            f"{row['final_status']} | {row['final_matches_expected']} |"
        )
    md_lines.append("")

    md_lines.append("## MISS Cases (k별 전체)\n")
    for k in result["k_values"]:
        miss_rows = [r for r in result["rows"][k] if r["evaluable"] and not r["hit"]]
        md_lines.append(f"### k={k} ({len(miss_rows)}건)\n")
        if not miss_rows:
            md_lines.append("없음\n")
            continue
        for row in miss_rows:
            md_lines.append(f"#### {row['test_id']} — {row['name']}\n")
            md_lines.append(f"- Original Query: {row['user_query']}")
            md_lines.append(f"- Expected: {row['expected_pass_candidates']} (SPEC: {row['expected_spec_ids']})")
            md_lines.append(f"- MISS Stage Classification: {row['miss_stage']}")
            md_lines.append(f"- Evidence: {row['miss_evidence']}\n")

    md_lines.append(f"## Pipeline Funnel 분석 (k={default_k} 대표 사례)\n")
    default_rows = result["rows"][default_k]
    hit_example = next((r for r in default_rows if r["evaluable"] and r["hit"]), None)
    miss_example = next((r for r in default_rows if r["evaluable"] and not r["hit"]), None)
    no_match_example = next((r for r in default_rows if not r["evaluable"]), None)
    for label, row in (("HIT", hit_example), ("MISS", miss_example), ("No-Match(Expected Candidate 없음)", no_match_example)):
        md_lines.append(f"### {label} 사례: {row['test_id'] if row else '(해당 없음)'}\n")
        if row is None:
            md_lines.append("해당 유형의 케이스가 없습니다.\n")
            continue
        md_lines.append(f"- Expected: {row['expected_pass_candidates'] or '(N/A)'} (SPEC: {row['expected_spec_ids'] or '(N/A)'})")
        md_lines.append(f"- Retrieved? {'HIT' if row['evaluable'] and row['hit'] else ('N/A' if not row['evaluable'] else 'MISS')} (rank={row['rank']}, {row['rank_kind']})")
        md_lines.append(f"- Candidate Extracted? {row['candidate_extraction_hit']}")
        md_lines.append(f"- Candidate Pool Size: {row['candidate_count']}")
        md_lines.append(f"- Final Recommendation: {row['final_recommendation']} / status={row['final_status']}")
        md_lines.append(f"- Matches Expected(Top1)? {row['final_matches_expected']}\n")

    (output_dir / "full_retrieval_recall_latest.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n결과 저장됨: {json_path}")
    print(f"결과 저장됨: {output_dir / 'full_retrieval_recall_latest.md'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Full Retrieval Recall Benchmark (T001~T027 + QA001~QA029)")
    parser.add_argument("--k-values", type=int, nargs="+", default=_DEFAULT_K_VALUES)
    parser.add_argument("--cases", type=str, nargs="+", default=None, help="특정 test_id만 실행(디버그용)")
    parser.add_argument("--output-dir", type=str, default=str(_RESULTS_DIR))
    args = parser.parse_args()

    result = run_benchmark(args.k_values, case_ids=args.cases)
    write_reports(result, Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
