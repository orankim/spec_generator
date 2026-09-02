"""
Ranking Failure Analysis + Alternative Ranking Policy Offline Benchmark.

핵심 질문(직전 Full Retrieval Recall Benchmark에서 발견): Expected Candidate가
Candidate Pool에 있는데도(Retrieval Recall@20=100%) 왜 Top1으로 선택되지 않는가
(Expected Candidate Top1 Rate가 k=20에서 오히려 18.6%로 하락)?

두 단계로 나뉜다.

1. Real RAG Pass(실제 Ollama, 1회만) — 56개 Ground Truth 질의 × k=[5,10,15,20]에
   대해 production 파이프라인(agent.requirement_parser.parse_requirement_text ->
   agent.spec_retriever.retrieve_for_requirement -> agent.candidate_matcher.
   build_candidates)을 그대로 실행하고, 이번에는 candidate pool 전체(status/
   pass_count/unknown_count/fail_count/rag_similarity_score/PASS 항목 목록)를
   JSON 캐시에 저장한다(요청서 23절: "실제 Pipeline 결과를 캐시해서 분석").
2. Offline Analysis(Ollama 불필요, 캐시만 사용) — scripts/ranking_failure_
   benchmark_lib.py의 순수 함수로 Retrieval/Validation/Ranking Failure를
   분류하고, Policy A~D를 비교한다. --use-cache로 1단계를 건너뛰고 이미 저장된
   캐시만으로 재분석할 수 있다(반복 실행 시 Ollama를 다시 호출하지 않기 위함).

Production 코드(agent/candidate_matcher.py 등)는 이 스크립트가 전혀 수정하지
않는다 — Policy A는 반드시 agent.candidate_matcher.select_best_candidate()를
그대로 호출한 결과와 비교해 검증한다(§14, 아래 _verify_policy_a에서 수행).

사용법:
    .venv/Scripts/python.exe scripts/ranking_failure_benchmark.py
    .venv/Scripts/python.exe scripts/ranking_failure_benchmark.py --use-cache
    .venv/Scripts/python.exe scripts/ranking_failure_benchmark.py --cases T001 QA023 --k-values 10
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

from scripts.full_retrieval_recall_benchmark_lib import (  # noqa: E402
    build_equipment_name_to_spec_ids,
    discover_benchmark_cases,
    discover_sample_spec_files,
    resolve_expected_spec_ids,
)
from scripts.ranking_failure_benchmark_lib import (  # noqa: E402
    FUNNEL_RANKING_FAILURE,
    FUNNEL_RETRIEVAL_FAILURE,
    FUNNEL_SUCCESS,
    FUNNEL_VALIDATION_FAILURE,
    POLICIES,
    classify_ambiguity,
    classify_funnel,
    classify_ranking_loss_reason_multi,
    is_false_pass,
    rank_candidates_offline,
    status_priority_holds,
    top_n_via_production_selection,
)

_DB_PATH = str(_REPO_ROOT / "_test_chroma_db_ranking_failure")
_RESULTS_DIR = _REPO_ROOT / "benchmark_results"
_CACHE_PATH = _RESULTS_DIR / "ranking_failure_cache.json"
_DEFAULT_K_VALUES = [5, 10, 15, 20]


def _serialize_candidate(c) -> Dict[str, Any]:
    return {
        "candidate_id": c.candidate_id,
        "source_document": c.source_document,
        "manufacturer": c.manufacturer,
        "model": c.model,
        "status": c.status,
        "pass_count": c.pass_count,
        "unknown_count": c.unknown_count,
        "fail_count": c.fail_count,
        "rag_similarity_score": c.rag_similarity_score,
        "matches": [{"item": m.item, "field_key": m.field_key, "result": m.result} for m in c.matches],
    }


def run_real_pass(
    k_values: List[int], case_ids: Optional[List[str]] = None, cache_path: Optional[Path] = None
) -> Dict[str, Any]:
    """1단계: 실제 Ollama로 후보 pool 전체를 캐시에 저장한다(Ranking 판단은 여기서
    전혀 하지 않는다 — 순수 데이터 수집).

    cache_path를 지정하지 않으면 기본 공유 캐시(_CACHE_PATH)에 쓴다 — 부분 실행
    (case_ids로 일부만 돌리는 smoke test 등)이 이 기본 경로에 쓰면 전체 56케이스로
    만든 캐시를 덮어써 버리는 문제가 실제로 발생했다(pytest 회귀 스위트가 smoke
    test를 실행할 때마다 전체 캐시가 4케이스짜리로 축소됨) — 그래서 smoke test는
    반드시 별도 cache_path를 넘겨야 한다."""
    print("=" * 90)
    print("환경 점검")
    print("=" * 90)
    env = rag.check_ollama_environment()
    if not env.server_reachable:
        raise SystemExit(f"[BLOCKED] Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        raise SystemExit(f"[BLOCKED] embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")
    print(f"  host={env.ollama_host} embedding_model={env.embedding_model} llm_model={env.llm_model}")

    spec_files = discover_sample_spec_files()
    all_cases = discover_benchmark_cases()
    cases = [c for c in all_cases if case_ids is None or c["test_id"] in case_ids]
    name_to_spec_ids = build_equipment_name_to_spec_ids()
    print(f"  SPEC 파일: {len(spec_files)}, Ground Truth 케이스: {len(all_cases)}(실행 대상 {len(cases)})")

    print("\n" + "=" * 90)
    print("실제 bge-m3 임베딩으로 ChromaDB 재생성")
    print("=" * 90)
    stats = rag.build_real_vector_db(_DB_PATH)
    print(f"  chunks={stats.indexed_chunk_count} dim={stats.embedding_dimension} build_seconds={stats.build_seconds:.1f}")

    print("\n" + "=" * 90)
    print(f"질의 {len(cases)}개 실제 LLM 파싱 (1회씩만, 이후 k별 재사용)")
    print("=" * 90)
    parsed: Dict[str, Any] = {}
    for i, case in enumerate(cases, start=1):
        t0 = time.monotonic()
        requirement = parse_requirement_text(case["user_query"])
        elapsed = time.monotonic() - t0
        parsed[case["test_id"]] = requirement
        print(f"  [{i}/{len(cases)}] {case['test_id']:8s} parse={elapsed:5.2f}s")

    print("\n" + "=" * 90)
    print(f"k sweep 실행 + candidate pool 캐시 저장: {k_values}")
    print("=" * 90)
    cache: Dict[str, Any] = {
        "environment": {
            "ollama_host": env.ollama_host, "embedding_model": env.embedding_model,
            "embedding_dimension": stats.embedding_dimension, "llm_model": env.llm_model,
            "indexed_spec_count": stats.indexed_spec_count, "indexed_chunk_count": stats.indexed_chunk_count,
        },
        "k_values": k_values,
        "cases": {},
    }
    for case in cases:
        expected_spec_ids = sorted(resolve_expected_spec_ids(case, name_to_spec_ids))
        cache["cases"][case["test_id"]] = {
            "name": case.get("name"),
            "user_query": case["user_query"],
            "expected_pass_candidates": case.get("expected_pass_candidates") or [],
            "expected_spec_ids": expected_spec_ids,
            "expected_final_status": case.get("expected_final_status"),
            "by_k": {},
        }

    for k in k_values:
        print(f"\n--- k={k} ---")
        for i, case in enumerate(cases, start=1):
            requirement = parsed[case["test_id"]]
            retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=stats.db_path, k_per_query=k)
            candidates = build_candidates(requirement, retrieved_docs)
            chosen = select_best_candidate(candidates)
            cache["cases"][case["test_id"]]["by_k"][str(k)] = {
                "candidates": [_serialize_candidate(c) for c in candidates],
                "chosen_candidate_id": chosen.candidate_id if chosen else None,
                "chosen_status": chosen.status if chosen else None,
                "retrieved_unique_doc_count": len({d.metadata.get("filename") or d.metadata.get("source") for d in retrieved_docs}),
            }
            print(f"  [{i}/{len(cases)}] {case['test_id']:8s} candidates={len(candidates)} chosen={(chosen.source_document if chosen else None)}")

    resolved_cache_path = Path(cache_path) if cache_path is not None else _CACHE_PATH
    resolved_cache_path.parent.mkdir(exist_ok=True, parents=True)
    resolved_cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n캐시 저장됨: {resolved_cache_path}")
    return cache


class _CandidateView:
    """캐시에서 복원한 dict를 select_best_candidate()에 그대로 넣을 수 있도록 하는
    최소 래퍼 — CandidateEquipment 재구성이 아니라, ranking_failure_benchmark_lib의
    _get() 헬퍼가 이미 dict를 지원하므로 사실 dict를 그대로 써도 되지만, production
    select_best_candidate()는 pydantic 모델의 속성 접근(.status 등)을 기대하므로
    여기서만 얇게 감싼다. 값 자체는 전부 1단계에서 이미 계산되어 캐시된 것을 그대로
    옮길 뿐, 어떤 재계산도 하지 않는다."""

    def __init__(self, d: Dict[str, Any]):
        self._d = d
        self.candidate_id = d["candidate_id"]
        self.source_document = d["source_document"]
        self.manufacturer = d["manufacturer"]
        self.model = d["model"]
        self.status = d["status"]
        self.pass_count = d["pass_count"]
        self.unknown_count = d["unknown_count"]
        self.fail_count = d["fail_count"]
        self.rag_similarity_score = d["rag_similarity_score"]
        self.matches = d["matches"]


def _load_candidates(case_k_entry: Dict[str, Any]) -> List[_CandidateView]:
    return [_CandidateView(c) for c in case_k_entry["candidates"]]


def analyze(cache: Dict[str, Any]) -> Dict[str, Any]:
    """2단계: Ollama 불필요, 캐시만으로 분석한다."""
    k_values = cache["k_values"]
    cases = cache["cases"]

    funnel_by_k: Dict[int, Dict[str, int]] = {}
    ranking_failures_by_k: Dict[int, List[Dict[str, Any]]] = {}
    topn_by_k: Dict[int, Dict[str, float]] = {}
    no_match_by_k: Dict[int, Dict[str, Any]] = {}
    policy_a_verification_errors: List[str] = []

    for k in k_values:
        counts = {FUNNEL_RETRIEVAL_FAILURE: 0, FUNNEL_VALIDATION_FAILURE: 0, FUNNEL_RANKING_FAILURE: 0, FUNNEL_SUCCESS: 0}
        rf_rows = []
        topn_hits = {1: 0, 3: 0, 5: 0, 10: 0}
        n_evaluable = 0
        false_pass_count = 0
        n_no_match = 0
        status_match_count = 0

        for test_id, case in cases.items():
            entry = case["by_k"][str(k)]
            candidates = _load_candidates(entry)
            expected_spec_ids = set(case["expected_spec_ids"])

            if not expected_spec_ids:
                n_no_match += 1
                chosen_status = entry["chosen_status"]
                if is_false_pass(chosen_status):
                    false_pass_count += 1
                if chosen_status == case["expected_final_status"]:
                    status_match_count += 1
                continue

            n_evaluable += 1
            classification = classify_funnel(candidates, expected_spec_ids)
            counts[classification.stage] += 1

            # Policy A 검증(§14): 캐시된 chosen_candidate_id(1단계에서
            # select_best_candidate()로 얻음)와 이 분석 단계에서 다시 select_best_
            # candidate()를 호출한 결과가 반드시 같아야 한다.
            recomputed_chosen = select_best_candidate(candidates)
            recomputed_id = recomputed_chosen.candidate_id if recomputed_chosen else None
            if recomputed_id != entry["chosen_candidate_id"]:
                policy_a_verification_errors.append(
                    f"{test_id}@k={k}: 1단계 chosen={entry['chosen_candidate_id']} vs 재계산 chosen={recomputed_id}"
                )

            # Top-N (production 반복 선택 방식, §10)
            top10 = top_n_via_production_selection(candidates, 10)
            top_ids = [c.source_document for c in top10]
            for n in (1, 3, 5, 10):
                if expected_spec_ids & set(top_ids[:n]):
                    topn_hits[n] += 1

            if classification.stage == FUNNEL_RANKING_FAILURE:
                loss_reason = classify_ranking_loss_reason_multi(classification.expected_candidates_in_pool, classification.top1)
                ambiguity = classify_ambiguity(
                    max(classification.expected_candidates_in_pool, key=lambda c: c.pass_count),
                    classification.top1,
                )
                rf_rows.append({
                    "test_id": test_id,
                    "query": case["user_query"],
                    "expected_pass_candidates": case["expected_pass_candidates"],
                    "expected_spec_ids": sorted(expected_spec_ids),
                    "expected_candidates": [
                        {"source_document": c.source_document, "status": c.status, "pass_count": c.pass_count,
                         "unknown_count": c.unknown_count, "fail_count": c.fail_count, "rag_similarity_score": c.rag_similarity_score}
                        for c in classification.expected_candidates_in_pool
                    ],
                    "top1": {
                        "source_document": classification.top1.source_document, "status": classification.top1.status,
                        "pass_count": classification.top1.pass_count, "unknown_count": classification.top1.unknown_count,
                        "fail_count": classification.top1.fail_count, "rag_similarity_score": classification.top1.rag_similarity_score,
                    },
                    "loss_reason": loss_reason,
                    "ambiguity": ambiguity,
                })

        funnel_by_k[k] = counts
        ranking_failures_by_k[k] = rf_rows
        topn_by_k[k] = {f"top{n}_rate": (hits / n_evaluable if n_evaluable else None) for n, hits in topn_hits.items()}
        no_match_by_k[k] = {
            "n_no_match": n_no_match,
            "false_pass_count": false_pass_count,
            "false_pass_rate": (false_pass_count / n_no_match) if n_no_match else None,
            "status_match_rate": (status_match_count / n_no_match) if n_no_match else None,
        }

    # Policy 비교 (요청서 12/13절) — 캐시된 candidate pool에 각 policy의 key로
    # 재정렬만 적용한다(재검색/재판정 없음).
    policy_comparison = {}
    for policy_name, key_fn in POLICIES.items():
        n_evaluable = 0
        topn_hits = {1: 0, 3: 0, 5: 0}
        false_pass_total = 0
        n_no_match_total = 0
        status_safety_violations = 0
        k = k_values[len(k_values) // 2] if len(k_values) > 2 else k_values[0]  # 대표 k(중앙값)로 비교, 아래서 k=10 있으면 그걸 사용
        if 10 in k_values:
            k = 10
        for test_id, case in cases.items():
            entry = case["by_k"][str(k)]
            candidates = _load_candidates(entry)
            expected_spec_ids = set(case["expected_spec_ids"])
            ranked = rank_candidates_offline(candidates, key_fn)
            if not status_priority_holds(ranked):
                status_safety_violations += 1
            if not expected_spec_ids:
                n_no_match_total += 1
                if ranked and ranked[0].status == "PASS":
                    false_pass_total += 1
                continue
            n_evaluable += 1
            top_ids = [c.source_document for c in ranked]
            for n in (1, 3, 5):
                if expected_spec_ids & set(top_ids[:n]):
                    topn_hits[n] += 1
        policy_comparison[policy_name] = {
            "k_used": k,
            "top1_rate": topn_hits[1] / n_evaluable if n_evaluable else None,
            "top3_rate": topn_hits[3] / n_evaluable if n_evaluable else None,
            "top5_rate": topn_hits[5] / n_evaluable if n_evaluable else None,
            "false_pass_count": false_pass_total,
            "n_no_match": n_no_match_total,
            "status_safety_violations": status_safety_violations,
        }

    return {
        "funnel_by_k": funnel_by_k,
        "ranking_failures_by_k": ranking_failures_by_k,
        "topn_by_k": topn_by_k,
        "no_match_by_k": no_match_by_k,
        "policy_comparison": policy_comparison,
        "policy_a_verification_errors": policy_a_verification_errors,
        "n_evaluable_total": len([c for c in cases.values() if c["expected_spec_ids"]]),
    }


def write_report(cache: Dict[str, Any], analysis: Dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    (output_dir / "ranking_failure_analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    lines = ["# Ranking Failure Analysis + Ranking Policy Benchmark 결과\n"]
    env = cache["environment"]
    lines.append("## Environment\n")
    lines.append(f"- Embedding: {env['embedding_model']} (dim={env['embedding_dimension']})")
    lines.append(f"- LLM: {env['llm_model']}")
    lines.append(f"- Corpus: {env['indexed_spec_count']} SPEC / {env['indexed_chunk_count']} chunks\n")

    lines.append(f"## Policy A 검증 (production select_best_candidate()와 100% 일치해야 함)\n")
    errs = analysis["policy_a_verification_errors"]
    lines.append("PASS — 전체 케이스에서 재계산 결과가 1단계 결과와 일치\n" if not errs else "\n".join(["FAIL:"] + errs) + "\n")

    lines.append("## k별 Funnel\n")
    lines.append("| K | Retrieval Failure | Validation Failure | Ranking Failure | Success | Top1 | Top3 | Top5 | Top10 |")
    lines.append("|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k in cache["k_values"]:
        f = analysis["funnel_by_k"][k]
        t = analysis["topn_by_k"][k]
        lines.append(
            f"| {k} | {f[FUNNEL_RETRIEVAL_FAILURE]} | {f[FUNNEL_VALIDATION_FAILURE]} | {f[FUNNEL_RANKING_FAILURE]} | {f[FUNNEL_SUCCESS]} | "
            f"{_fmt(t['top1_rate'])} | {_fmt(t['top3_rate'])} | {_fmt(t['top5_rate'])} | {_fmt(t['top10_rate'])} |"
        )
    lines.append("")

    lines.append("## No-Match Safety (Expected Candidate 없음 케이스)\n")
    lines.append("| K | 케이스 수 | False PASS | False PASS Rate | Expected Status Match Rate |")
    lines.append("|--:|--:|--:|--:|--:|")
    for k in cache["k_values"]:
        nm = analysis["no_match_by_k"][k]
        lines.append(f"| {k} | {nm['n_no_match']} | {nm['false_pass_count']} | {_fmt(nm['false_pass_rate'])} | {_fmt(nm['status_match_rate'])} |")
    lines.append("")

    lines.append("## Ranking Failure 상세 (k=10)\n")
    default_k = 10 if 10 in cache["k_values"] else cache["k_values"][0]
    rf = analysis["ranking_failures_by_k"][default_k]
    if not rf:
        lines.append("없음\n")
    else:
        lines.append("| Test ID | Expected | Expected(pass/unk/fail/sim) | Top1 | Top1(pass/unk/fail/sim) | Loss Reason | Ambiguity |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in rf:
            e = row["expected_candidates"][0]
            t = row["top1"]
            lines.append(
                f"| {row['test_id']} | {e['source_document']} | {e['pass_count']}/{e['unknown_count']}/{e['fail_count']}/{_fmt(e['rag_similarity_score'])} | "
                f"{t['source_document']} | {t['pass_count']}/{t['unknown_count']}/{t['fail_count']}/{_fmt(t['rag_similarity_score'])} | "
                f"{row['loss_reason']} | {row['ambiguity']} |"
            )
    lines.append("")

    lines.append("## Alternative Ranking Policy 비교 (k=10 candidate pool 재사용, 재검색 없음)\n")
    lines.append("| Policy | Top1 | Top3 | Top5 | False PASS | Status Safety Violations |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for name, pc in analysis["policy_comparison"].items():
        lines.append(f"| {name} | {_fmt(pc['top1_rate'])} | {_fmt(pc['top3_rate'])} | {_fmt(pc['top5_rate'])} | {pc['false_pass_count']} | {pc['status_safety_violations']} |")
    lines.append("")

    (output_dir / "ranking_failure_latest.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"결과 저장됨: {output_dir / 'ranking_failure_latest.md'}")
    print(f"결과 저장됨: {output_dir / 'ranking_failure_analysis.json'}")


def _fmt(v: Optional[float]) -> str:
    return f"{v:.3f}" if v is not None else "N/A"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ranking Failure Analysis + Policy Benchmark")
    parser.add_argument("--k-values", type=int, nargs="+", default=_DEFAULT_K_VALUES)
    parser.add_argument("--cases", type=str, nargs="+", default=None)
    parser.add_argument("--use-cache", action="store_true", help="1단계(실제 Ollama)를 건너뛰고 기존 캐시로만 분석")
    parser.add_argument("--output-dir", type=str, default=str(_RESULTS_DIR))
    args = parser.parse_args()

    if args.use_cache:
        if not _CACHE_PATH.exists():
            raise SystemExit(f"[BLOCKED] 캐시가 없습니다: {_CACHE_PATH}. --use-cache 없이 먼저 실행하세요.")
        cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        cache["k_values"] = [k for k in cache["k_values"] if k in args.k_values] or cache["k_values"]
        print(f"캐시 재사용: {_CACHE_PATH}")
    else:
        cache = run_real_pass(args.k_values, case_ids=args.cases)

    analysis = analyze(cache)
    write_report(cache, analysis, Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
