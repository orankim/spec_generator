"""
QA023(k=15에서도 남은 유일한 Retrieval MISS) 정밀 분석 — production 함수를 그대로
호출한다(재구현 없음). 두 개의 기존 real Ollama 산출물을 최대한 재사용해 불필요한
Ollama 호출을 피한다:

  1) benchmark_results/retrieval_root_cause_cache.json (Turn 6에서 실제 Ollama로
     만든, QA023의 확장 질의별 top-50 검색 결과 + requirement 파싱 결과) — 여기서
     Requirement Parsing/Query Expansion/Per-Query Rank(Step A/B)를 그대로 읽는다.
     재검증: 이 캐시는 embedding/llm 모델이 현재와 동일(bge-m3/qwen2.5:3b)하고,
     _build_queries()/parse_requirement_text() 자체가 이번 턴에서 변경되지 않았으므로
     (k_per_query 기본값만 바뀌었고 이 두 함수는 k와 무관) 유효하다.
  2) chroma_db_specs/ (production이 실제로 쓰는 영구 ChromaDB, 52 SPEC/383 chunk) —
     _inspection_item_boost_docs()는 순수 키워드 매칭이라 임베딩 호출이 필요 없다.
     이 DB에 대해 .get()만 호출해(임베딩 계산 없음) Step C/Strategy C를 실측한다.

Production 코드는 이 스크립트 안에서 절대 수정하지 않는다 — Strategy C 가설은
`agent.spec_retriever._ITEM_BOOST_KEYWORDS`를 메모리에서 일시적으로만 바꾸고
원복한다(파일 변경 없음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agent import spec_retriever  # noqa: E402
from agent import categorical_match  # noqa: E402
from agent.chroma_store import SimpleChromaStore  # noqa: E402
from agent.schemas import RequirementSchema  # noqa: E402

_ROOT_CAUSE_CACHE = _REPO_ROOT / "benchmark_results" / "retrieval_root_cause_cache.json"
_RANKING_CACHE = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_PROD_DB_PATH = _REPO_ROOT / "chroma_db_specs"  # production이 실제로 쓰는 영구 DB (읽기 전용 사용)
_EXPECTED_SPEC = "SPEC-009.md"


def _load_query_expansion_and_rank() -> Dict[str, Any]:
    """Step A/B — 기존 real Ollama 캐시에서 그대로 읽는다(재호출 없음)."""
    cache = json.loads(_ROOT_CAUSE_CACHE.read_text(encoding="utf-8"))
    case = cache["cases"]["QA023"]
    per_query_ranks = {}
    for q, hits in case["per_query_results"].items():
        rank_of_expected = next((h["rank"] for h in hits if h["source"] == _EXPECTED_SPEC), None)
        top5 = [(h["source"], h["rank"]) for h in hits[:5]]
        per_query_ranks[q] = {"spec009_rank": rank_of_expected, "top5_competing": top5}
    return {
        "user_query": case["user_query"],
        "requirement_field_count": case["requirement_field_count"],
        "requirement_dump": case["requirement_dump"],
        "expanded_queries": case["expanded_queries"],
        "per_query_ranks": per_query_ranks,
        "expected_doc_facts": case["expected_doc_facts"]["SPEC-009.md"],
    }


def _read_spec009_raw_text() -> str:
    return (_REPO_ROOT / "sample_specs" / "SPEC-009.md").read_text(encoding="utf-8")


def _current_boost_simulation() -> Dict[str, Any]:
    """Step C — 현재 production _inspection_item_boost_docs()를 실제로 호출한다
    (production DB의 .get()만 씀, 임베딩 호출 없음)."""
    embeddings = spec_retriever.get_embeddings()
    vs = SimpleChromaStore(persist_directory=str(_PROD_DB_PATH), embedding_function=embeddings)
    req = RequirementSchema(raw_text="표면 결함 검사기를 찾아줘. 폭 조건은 따로 없어.", inspection_items=["surface_defect"])

    current_docs = spec_retriever._inspection_item_boost_docs(req, vs)
    current_sources = sorted({spec_retriever.source_label(d) for d in current_docs})

    item_boost_keyword_lookup = spec_retriever._ITEM_BOOST_KEYWORDS.get("surface_defect")
    capability_lookup = categorical_match.INSPECTION_ITEM_CAPABILITY_KEYWORDS.get("surface_defect")

    return {
        "item_boost_keyword_entry_for_surface_defect": item_boost_keyword_lookup,
        "capability_keyword_entry_for_surface_defect": capability_lookup,
        "current_boost_doc_count": len(current_sources),
        "current_boost_includes_spec009": _EXPECTED_SPEC in current_sources,
        "current_boost_matched_docs": current_sources,
    }


def _strategy_c_simulation() -> Dict[str, Any]:
    """Strategy C — surface_defect 키를 '기존에 이미 정의된' 하위 결함 타입 키워드의
    합집합으로 매핑했다면 어떻게 되는지 오프라인으로 시뮬레이션한다. 새 키워드를
    임의로 만들지 않는다 — _ITEM_BOOST_KEYWORDS에 이미 있는 값만 재사용한다."""
    embeddings = spec_retriever.get_embeddings()
    vs = SimpleChromaStore(persist_directory=str(_PROD_DB_PATH), embedding_function=embeddings)
    req = RequirementSchema(raw_text="표면 결함 검사기를 찾아줘. 폭 조건은 따로 없어.", inspection_items=["surface_defect"])

    subtype_keys = ("scratch", "contamination", "particle", "pinhole", "void", "coating_non_uniformity", "edge_crack")
    union_keywords = []
    for key in subtype_keys:
        union_keywords.extend(spec_retriever._ITEM_BOOST_KEYWORDS[key])

    orig = dict(spec_retriever._ITEM_BOOST_KEYWORDS)
    try:
        spec_retriever._ITEM_BOOST_KEYWORDS["surface_defect"] = tuple(union_keywords)
        hypothetical_docs = spec_retriever._inspection_item_boost_docs(req, vs)
    finally:
        spec_retriever._ITEM_BOOST_KEYWORDS.clear()
        spec_retriever._ITEM_BOOST_KEYWORDS.update(orig)

    hyp_sources = sorted({spec_retriever.source_label(d) for d in hypothetical_docs})
    return {
        "hypothetical_boost_keyword_union": union_keywords,
        "hypothetical_boost_doc_count": len(hyp_sources),
        "hypothetical_boost_includes_spec009": _EXPECTED_SPEC in hyp_sources,
        "hypothetical_boost_matched_docs": hyp_sources,
    }


def _pool_sizes_from_ranking_cache() -> Dict[str, Any]:
    cache = json.loads(_RANKING_CACHE.read_text(encoding="utf-8"))
    qa023 = cache["cases"]["QA023"]
    out = {}
    for k in ("10", "15", "20"):
        cands = qa023["by_k"][k]["candidates"]
        docs = {c["source_document"] for c in cands}
        out[k] = {"pool_size": len(cands), "hit": _EXPECTED_SPEC in docs}
    return out


def main() -> None:
    print("=" * 90)
    print("QA023 Retrieval Root Cause 정밀 분석")
    print("=" * 90)

    step_ab = _load_query_expansion_and_rank()
    print("\n--- Step A: Requirement Parsing / Query Expansion (기존 real Ollama 캐시 재사용) ---")
    print(f"  user_query: {step_ab['user_query']}")
    print(f"  requirement_field_count: {step_ab['requirement_field_count']}")
    print(f"  inspection_items: {step_ab['requirement_dump']['inspection_items']}")
    print(f"  expanded_queries: {step_ab['expanded_queries']}")

    print("\n--- Step B: Per-Query SPEC-009 Rank ---")
    for q, r in step_ab["per_query_ranks"].items():
        print(f"  query={q!r}")
        print(f"    SPEC-009 rank: {r['spec009_rank']}")
        print(f"    top5 경쟁 문서: {r['top5_competing']}")

    print("\n--- Step C: Inspection Item Boost 분석 (production DB 재사용, 임베딩 호출 없음) ---")
    boost = _current_boost_simulation()
    for k, v in boost.items():
        print(f"  {k}: {v}")

    print("\n--- Step D: SPEC-009 Content ---")
    raw = _read_spec009_raw_text()
    defect_line = [ln for ln in raw.splitlines() if "Defect Types" in ln]
    print(f"  Defect Types 행: {defect_line}")
    print(f"  'scratch' 포함 여부(소문자 비교): {'scratch' in raw.lower()}")
    print(f"  'crack' 포함 여부: {'crack' in raw.lower()}")
    print(f"  'edge crack'(공백 포함 정확 문구) 포함 여부: {'edge crack' in raw.lower()}")

    print("\n--- Strategy C 시뮬레이션(오프라인, 기존 키워드 재사용) ---")
    strategy_c = _strategy_c_simulation()
    for k, v in strategy_c.items():
        print(f"  {k}: {v}")

    print("\n--- Strategy A/B 후보 풀 크기 (기존 real 캐시 재사용) ---")
    pools = _pool_sizes_from_ranking_cache()
    for k, v in pools.items():
        print(f"  k={k}: {v}")

    out = {
        "step_ab": step_ab,
        "step_c_current_boost": boost,
        "step_d_spec009_content": {
            "defect_types_line": defect_line,
            "contains_scratch": "scratch" in raw.lower(),
            "contains_crack": "crack" in raw.lower(),
            "contains_edge_crack_phrase": "edge crack" in raw.lower(),
        },
        "strategy_c_simulation": strategy_c,
        "pool_sizes_by_k": pools,
    }
    out_path = _REPO_ROOT / "benchmark_results" / "qa023_retrieval_analysis.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장됨: {out_path}")


if __name__ == "__main__":
    main()
