"""
Final Combined Validation — Strategy A(k=15, 현행)/B(k=20)/C(k=15 + surface_defect
boost coverage 확장) 56개 Dataset 비교. Ollama 호출을 최소화하기 위해:

  - Strategy A/B: benchmark_results/ranking_failure_cache.json(이미 실제 Ollama로
    만든 k=[5,10,15,20] 캐시, production 코드가 이 캐시 생성 이후 변경되지 않았으므로
    여전히 유효)를 그대로 재사용한다. 새 호출 없음.
  - Strategy C: scripts/strategy_c_blast_radius.py(오프라인, 임베딩/LLM 호출 없음)로
    "실제로 candidate pool이 달라질 수 있는" 케이스를 정확히 8개로 좁혔다(QA002,
    QA009, QA021, QA023, T002, T005, T021, T022). 이 8개만 real RAG로 재실행하고,
    나머지 48개는 Strategy A와 수학적으로 동일함이 이미 증명됐으므로 그대로 복사한다.

캐시 경로는 기존 ranking_failure_cache.json과 절대 겹치지 않는 전용 경로
(benchmark_results/final_combined_validation_cache.json)를 쓴다 — 이전 턴에
캐시 clobbering 버그가 있었으므로 재발 방지.

Production 함수를 그대로 호출한다(재구현 없음): parse_requirement_text,
retrieve_for_requirement(내부에서 agent.spec_retriever._ITEM_BOOST_KEYWORDS
모듈 상태를 참조하므로, Strategy C 실행 시에만 이 dict를 일시적으로 확장하고
finally에서 반드시 원복한다 — 파일은 전혀 건드리지 않는다), build_candidates,
select_best_candidate.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from agent import spec_retriever  # noqa: E402
from agent.candidate_matcher import build_candidates, select_best_candidate  # noqa: E402
from agent.requirement_parser import parse_requirement_text  # noqa: E402
from tests import real_rag_lib as rag  # noqa: E402
from tests.regression_lib import load_regression_cases  # noqa: E402

from scripts.full_retrieval_recall_benchmark_lib import (  # noqa: E402
    build_equipment_name_to_spec_ids,
    resolve_expected_spec_ids,
)

_RANKING_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_OUTPUT_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "final_combined_validation_cache.json"
_PROD_DB_PATH = _REPO_ROOT / "chroma_db_specs"

_STRATEGY_C_AFFECTED_IDS = ["QA002", "QA009", "QA021", "QA023", "T002", "T005", "T021", "T022"]
_SUBTYPE_KEYS = ("scratch", "contamination", "particle", "pinhole", "void", "coating_non_uniformity", "edge_crack")


def _candidate_to_dict(c) -> dict:
    return {
        "candidate_id": c.candidate_id, "source_document": c.source_document,
        "manufacturer": c.manufacturer, "model": c.model, "status": c.status,
        "pass_count": c.pass_count, "unknown_count": c.unknown_count, "fail_count": c.fail_count,
        "rag_similarity_score": c.rag_similarity_score,
        "matches": [{"item": m.item, "field_key": m.field_key, "result": m.result} for m in c.matches],
    }


def run_strategy_c_for_affected_cases() -> Dict[str, Any]:
    """8개 영향받는 케이스만 real Ollama(bge-m3 + qwen2.5:3b)로 재실행한다.
    production ChromaDB(chroma_db_specs/, 이미 존재, 재구축 없음)를 그대로 쓴다."""
    env = rag.check_ollama_environment()
    if not env.server_reachable:
        raise SystemExit(f"[BLOCKED] Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        raise SystemExit(f"[BLOCKED] embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")
    if not _PROD_DB_PATH.exists():
        raise SystemExit(f"[BLOCKED] production DB가 없습니다: {_PROD_DB_PATH}")

    all_cases = {c["test_id"]: c for c in load_regression_cases()}
    name_to_spec_ids = build_equipment_name_to_spec_ids()

    union_keywords: List[str] = []
    for key in _SUBTYPE_KEYS:
        union_keywords.extend(spec_retriever._ITEM_BOOST_KEYWORDS[key])

    results: Dict[str, Any] = {}
    orig_keywords = dict(spec_retriever._ITEM_BOOST_KEYWORDS)
    try:
        spec_retriever._ITEM_BOOST_KEYWORDS["surface_defect"] = tuple(union_keywords)
        for i, test_id in enumerate(_STRATEGY_C_AFFECTED_IDS, start=1):
            gt_case = all_cases[test_id]
            t0 = time.monotonic()
            requirement = parse_requirement_text(gt_case["user_query"])
            parse_s = time.monotonic() - t0

            t1 = time.monotonic()
            retrieved_docs = spec_retriever.retrieve_for_requirement(
                requirement, db_path=str(_PROD_DB_PATH), k_per_query=15
            )
            retrieval_s = time.monotonic() - t1

            candidates = build_candidates(requirement, retrieved_docs)
            chosen = select_best_candidate(candidates)

            unique_docs = sorted({spec_retriever.source_label(d) for d in retrieved_docs})
            expected_spec_ids = resolve_expected_spec_ids(gt_case, name_to_spec_ids)
            results[test_id] = {
                "name": gt_case.get("name"),
                "user_query": gt_case["user_query"],
                "expected_spec_ids": sorted(expected_spec_ids),
                "retrieved_unique_documents": unique_docs,
                "candidates": [_candidate_to_dict(c) for c in candidates],
                "chosen_candidate_id": chosen.candidate_id if chosen else None,
                "chosen_source_document": chosen.source_document if chosen else None,
                "chosen_status": chosen.status if chosen else None,
                "parse_s": parse_s,
                "retrieval_s": retrieval_s,
            }
            print(f"  [{i}/{len(_STRATEGY_C_AFFECTED_IDS)}] {test_id:8s} parse={parse_s:5.2f}s retrieval={retrieval_s:5.2f}s "
                  f"pool={len(candidates)} top1={chosen.source_document if chosen else None}({chosen.status if chosen else None})")
    finally:
        spec_retriever._ITEM_BOOST_KEYWORDS.clear()
        spec_retriever._ITEM_BOOST_KEYWORDS.update(orig_keywords)

    return {
        "environment": {"embedding_model": env.embedding_model, "llm_model": env.llm_model},
        "affected_case_ids": _STRATEGY_C_AFFECTED_IDS,
        "union_keywords_used": union_keywords,
        "results": results,
    }


def main() -> None:
    print("=" * 90)
    print("Strategy C — 8개 영향 케이스 real RAG 재실행 (surface_defect boost 확장)")
    print("=" * 90)
    cache = run_strategy_c_for_affected_cases()
    _OUTPUT_CACHE_PATH.parent.mkdir(exist_ok=True, parents=True)
    _OUTPUT_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n캐시 저장됨: {_OUTPUT_CACHE_PATH}")


if __name__ == "__main__":
    main()
