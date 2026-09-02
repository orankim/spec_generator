"""
Retrieval MISS Root Cause Analysis — 실제 Ollama로 소규모(현재 MISS + No-Match
케이스만) per-query 상세 캐시를 만든 뒤, 그 캐시만으로 원인을 분류하고 Strategy
C/D/E를 오프라인 비교한다(요청서 19절: Ollama 호출 최소화 — 56개 전체가 아니라
"근본 원인 분석에 실제로 필요한" 케이스만 다시 검색한다).

MISS/No-Match 케이스는 benchmark_results/ranking_failure_cache.json(이미 실제
Ollama로 만들어진 k=10 결과)에서 동적으로 결정한다 — 하드코딩하지 않는다.

Production 함수를 그대로 재사용한다:
  - agent.requirement_parser.parse_requirement_text (실제 LLM)
  - agent.spec_retriever._build_queries (확장 질의 생성 로직 재사용, 재구현 아님)
  - agent.spec_retriever.get_embeddings + agent.chroma_store.SimpleChromaStore
    (production이 retrieve_for_requirement 내부에서 쓰는 것과 동일한 객체)
  - agent.candidate_matcher._extract_candidate_fact + agent.units.evaluate_hard_requirements
    (Strategy C의 "문서가 구조적으로 조건을 만족하는가" 판정 — 새 판정 로직을 만들지 않음)

DB는 scripts/ranking_failure_benchmark.py가 만든 것과 동일한 경로(_test_chroma_db_
ranking_failure)를 그대로 재사용한다(이미 있으면 재구축하지 않음 — 같은 corpus이므로
안전하게 재사용 가능, 불필요한 재구축 없음).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from agent import spec_retriever  # noqa: E402
from agent import units  # noqa: E402
from agent.candidate_matcher import _extract_candidate_fact  # noqa: E402
from agent.chroma_store import SimpleChromaStore  # noqa: E402
from agent.requirement_parser import parse_requirement_text  # noqa: E402
from tests import real_rag_lib as rag  # noqa: E402

from scripts.ground_truth_ambiguity_lib import load_cache  # noqa: E402
from scripts.ranking_failure_benchmark_lib import FUNNEL_RETRIEVAL_FAILURE, classify_funnel  # noqa: E402
from scripts.retrieval_root_cause_lib import RootCauseEvidence, classify_root_cause  # noqa: E402

_DB_PATH = _REPO_ROOT / "_test_chroma_db_ranking_failure"  # ranking_failure_benchmark.py와 동일 경로(재사용)
_RANKING_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_RESULTS_DIR = _REPO_ROOT / "benchmark_results"
_OUTPUT_CACHE_PATH = _RESULTS_DIR / "retrieval_root_cause_cache.json"

_LARGE_K = 50  # best_rank_across_queries 탐색용(production k=10보다 훨씬 크게)
_STRUCTURED_FIELDS = (
    "target.material", "target.width_mm", "measurement_principle", "measurement_method",
    "measurement_range", "accuracy", "measurement_speed", "minimum_defect_size", "inline_offline",
)

_STOPWORDS = {"이상", "이하", "미만", "초과", "있는", "있고", "찾아줘", "장비를", "검사할", "수", "을", "를", "의", "가", "은", "는"}


def _requirement_field_count(requirement) -> int:
    count = 0
    if requirement.target.material:
        count += 1
    if requirement.target.width_mm is not None:
        count += 1
    if requirement.measurement_principle:
        count += 1
    if requirement.measurement_method:
        count += 1
    if requirement.measurement_range is not None:
        count += 1
    if requirement.accuracy is not None and requirement.accuracy.value is not None:
        count += 1
    if requirement.measurement_speed is not None and requirement.measurement_speed.value is not None:
        count += 1
    if requirement.minimum_defect_size is not None and requirement.minimum_defect_size.value is not None:
        count += 1
    if requirement.inline_offline:
        count += 1
    if requirement.inspection_items:
        count += 1
    return count


def _tokenize(text: str) -> Set[str]:
    tokens = re.findall(r"[A-Za-z가-힣0-9]+", text)
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


def _lexical_overlap(raw_text: str, identity_text: str) -> tuple:
    q_tokens = _tokenize(raw_text)
    doc_tokens = _tokenize(identity_text)
    overlap = sorted(q_tokens & doc_tokens)
    return bool(overlap), overlap


def build_root_cause_cache(case_ids: List[str], k_values_for_db: Optional[List[int]] = None) -> Dict[str, Any]:
    print("=" * 90)
    print("환경 점검")
    print("=" * 90)
    env = rag.check_ollama_environment()
    if not env.server_reachable:
        raise SystemExit(f"[BLOCKED] Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        raise SystemExit(f"[BLOCKED] embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")
    print(f"  host={env.ollama_host} embedding_model={env.embedding_model} llm_model={env.llm_model}")

    print("\n" + "=" * 90)
    print("ChromaDB 준비")
    print("=" * 90)
    if _DB_PATH.exists():
        print(f"  기존 DB 재사용(재구축 안 함): {_DB_PATH}")
        db_path = str(_DB_PATH)
    else:
        stats = rag.build_real_vector_db(str(_DB_PATH))
        print(f"  신규 빌드: chunks={stats.indexed_chunk_count} dim={stats.embedding_dimension}")
        db_path = str(_DB_PATH)

    embeddings = spec_retriever.get_embeddings()
    vector_store = SimpleChromaStore(persist_directory=db_path, embedding_function=embeddings)

    from tests.regression_lib import load_regression_cases

    all_cases = {c["test_id"]: c for c in load_regression_cases()}

    ranking_cache = load_cache(_RANKING_CACHE_PATH)
    name_to_spec_ids_dummy = {}  # expected_spec_ids는 ranking_cache에 이미 계산되어 있으므로 재계산 불필요

    cache: Dict[str, Any] = {
        "environment": {"embedding_model": env.embedding_model, "llm_model": env.llm_model},
        "production_k": 10,
        "large_k": _LARGE_K,
        "cases": {},
    }

    print("\n" + "=" * 90)
    print(f"{len(case_ids)}개 케이스 per-query 상세 검색 (실제 Ollama)")
    print("=" * 90)
    for i, test_id in enumerate(case_ids, start=1):
        gt_case = all_cases[test_id]
        cached_case = ranking_cache["cases"][test_id]
        expected_spec_ids = set(cached_case["expected_spec_ids"])

        t0 = time.monotonic()
        requirement = parse_requirement_text(gt_case["user_query"])
        parse_s = time.monotonic() - t0

        expanded_queries = spec_retriever._build_queries(requirement)

        per_query_results = {}
        for q in expanded_queries:
            hits = vector_store.similarity_search_with_score(q, k=_LARGE_K)
            per_query_results[q] = [
                {"source": spec_retriever.source_label(doc), "score": score, "rank": rank + 1}
                for rank, (doc, score) in enumerate(hits)
            ]

        # Strategy C 근거 수집: expected 문서 전체 chunk를 metadata 필터로 직접 가져온다
        # (새 임베딩 호출 없음 — 단순 조회). agent.candidate_matcher._extract_candidate_fact를
        # 그대로 재사용해 그 문서가 구조적으로 이 requirement를 만족하는지 확인한다.
        expected_doc_facts = {}
        for spec_id in expected_spec_ids:
            raw = vector_store.get(where={"filename": spec_id}, include=["documents", "metadatas"])
            docs = raw.get("documents") or []
            metas = raw.get("metadatas") or []
            from langchain_core.documents import Document as LC_Document

            lc_docs = [LC_Document(page_content=d, metadata=m or {}) for d, m in zip(docs, metas)]
            fact = _extract_candidate_fact(lc_docs)
            expected_doc_facts[spec_id] = {
                "range": fact.range, "accuracy": fact.accuracy, "width_mm": fact.width_mm,
                "speed": fact.speed, "defect_size": fact.defect_size,
                "identity_text": " ".join(t for t in (fact.equipment_type_text, fact.notes_text) if t) or "",
            }

        cache["cases"][test_id] = {
            "name": gt_case.get("name"),
            "user_query": gt_case["user_query"],
            "expected_spec_ids": sorted(expected_spec_ids),
            "requirement_field_count": _requirement_field_count(requirement),
            "requirement_dump": requirement.model_dump(),
            "expanded_queries": expanded_queries,
            "per_query_results": per_query_results,
            "expected_doc_facts": expected_doc_facts,
            "parse_s": parse_s,
        }
        print(f"  [{i}/{len(case_ids)}] {test_id:8s} parse={parse_s:5.2f}s expanded_queries={len(expanded_queries)}개")

    _RESULTS_DIR.mkdir(exist_ok=True)
    _OUTPUT_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n캐시 저장됨: {_OUTPUT_CACHE_PATH}")
    return cache


def analyze_root_causes(cache: Dict[str, Any], miss_case_ids: List[str]) -> Dict[str, Any]:
    """Ollama 불필요 — 캐시만으로 원인 분류 + Strategy C/D/E 오프라인 비교."""
    results = {}
    for test_id in miss_case_ids:
        case = cache["cases"][test_id]
        expected_spec_ids = set(case["expected_spec_ids"])

        best_rank, best_rank_query = None, None
        unique_docs = set()
        for q, hits in case["per_query_results"].items():
            for h in hits[:10]:  # production 실제 cutoff(k=10)에서의 경쟁 문서 집계
                unique_docs.add(h["source"])
            for h in hits:
                if h["source"] in expected_spec_ids:
                    if best_rank is None or h["rank"] < best_rank:
                        best_rank, best_rank_query = h["rank"], q
                    break  # 이 query 안에서는 첫(최고 순위) 등장만 본다

        identity_text = " ".join(f["identity_text"] for f in case["expected_doc_facts"].values())
        lexical_overlap, overlap_terms = _lexical_overlap(case["user_query"], identity_text)

        ev = RootCauseEvidence(
            test_id=test_id, query=case["user_query"], production_k=cache["production_k"],
            requirement_field_count=case["requirement_field_count"], n_expanded_queries=len(case["expanded_queries"]),
            expanded_queries=case["expanded_queries"], best_rank_across_queries=best_rank, best_rank_query=best_rank_query,
            n_unique_docs_in_expanded_top_n=len(unique_docs), lexical_overlap=lexical_overlap, lexical_overlap_terms=overlap_terms,
            range_boost_applicable=case["requirement_dump"].get("measurement_range") is not None,
            inspection_item_boost_applicable=bool(case["requirement_dump"].get("inspection_items")),
        )
        classification = classify_root_cause(ev)

        # Strategy C: expected 문서 자체 fact가 구조적으로 요구조건을 만족하는가(agent.units 재사용).
        strategy_c_rescues = False
        for spec_id, facts in case["expected_doc_facts"].items():
            ok_parts = []
            req = case["requirement_dump"]
            if req.get("measurement_range") and facts["range"]:
                r = req["measurement_range"]
                try:
                    ok, _ = units.evaluate_hard_requirements(
                        required_range=(r["min"], r["max"], r.get("unit") or "um"), candidate_range=facts["range"]
                    )
                    ok_parts.append(ok)
                except units.UnitError:
                    pass
            if req.get("target", {}).get("width_mm") and facts["width_mm"] is not None:
                try:
                    ok, _ = units.evaluate_hard_requirements(
                        required_accuracy=(req["target"]["width_mm"], "mm", ">="), candidate_accuracy=(facts["width_mm"], "mm")
                    )
                    ok_parts.append(ok)
                except units.UnitError:
                    pass
            if req.get("accuracy") and req["accuracy"].get("value") is not None and facts["accuracy"]:
                try:
                    ok, _ = units.evaluate_hard_requirements(
                        required_accuracy=(req["accuracy"]["value"], req["accuracy"].get("unit") or "um", "<="),
                        candidate_accuracy=facts["accuracy"],
                    )
                    ok_parts.append(ok)
                except units.UnitError:
                    pass
            if ok_parts and all(ok_parts):
                strategy_c_rescues = True

        results[test_id] = {
            "root_cause": classification["cause"],
            "reasoning": classification["reasoning"],
            "best_rank_across_queries": best_rank,
            "best_rank_query": best_rank_query,
            "n_unique_docs_top10_union": len(unique_docs),
            "strategy_c_rescues": strategy_c_rescues,
        }
    return results


def _derive_miss_and_no_match_ids(ranking_cache: Dict[str, Any]) -> tuple:
    """ranking_failure_cache.json(k=10 실측 결과)에서 현재 MISS/No-Match 케이스를
    동적으로 도출한다 — 이전 리포트의 케이스 목록을 재사용하지 않는다."""
    miss_ids, no_match_ids = [], []
    for test_id, case in ranking_cache["cases"].items():
        expected = case.get("expected_spec_ids") or []
        if not expected:
            no_match_ids.append(test_id)
            continue
        docs_at_10 = {c["source_document"] for c in case["by_k"]["10"]["candidates"]}
        if not (set(expected) & docs_at_10):
            miss_ids.append(test_id)
    return sorted(miss_ids), sorted(no_match_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-cache", action="store_true", help="실제 Ollama 호출 없이 기존 retrieval_root_cause_cache.json만 재분석")
    args = parser.parse_args()

    ranking_cache = load_cache(_RANKING_CACHE_PATH)
    miss_ids, no_match_ids = _derive_miss_and_no_match_ids(ranking_cache)
    print(f"동적으로 도출한 현재 k=10 MISS 케이스({len(miss_ids)}개): {miss_ids}")
    print(f"동적으로 도출한 No-Match 케이스({len(no_match_ids)}개): {no_match_ids}")
    case_ids = miss_ids + no_match_ids

    if args.use_cache and _OUTPUT_CACHE_PATH.exists():
        cache = json.loads(_OUTPUT_CACHE_PATH.read_text(encoding="utf-8"))
        print(f"기존 캐시 재사용(Ollama 호출 없음): {_OUTPUT_CACHE_PATH}")
    else:
        cache = build_root_cause_cache(case_ids)

    root_causes = analyze_root_causes(cache, miss_ids)
    print("\n" + "=" * 90)
    print("Retrieval MISS Root Cause 분류 결과")
    print("=" * 90)
    for test_id, r in root_causes.items():
        print(f"  {test_id:8s} cause={r['root_cause']:32s} best_rank={r['best_rank_across_queries']} strategy_c_rescues={r['strategy_c_rescues']}")

    out_path = _RESULTS_DIR / "retrieval_root_cause_analysis.json"
    out_path.write_text(json.dumps({"miss_ids": miss_ids, "no_match_ids": no_match_ids, "root_causes": root_causes}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n분석 결과 저장됨: {out_path}")


if __name__ == "__main__":
    main()
