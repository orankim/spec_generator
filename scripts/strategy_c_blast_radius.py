"""
Strategy C(surface_defect boost coverage 확장)가 56개 Dataset 전체 중 실제로
'어떤 케이스에 영향을 줄 수 있는지'를 오프라인으로(임베딩/LLM 호출 없음) 정확히
좁힌다. agent.spec_retriever._inspection_item_boost_docs()는 순수 키워드 매칭
함수이므로, production ChromaDB(chroma_db_specs/, .get()만 호출)에 대해 실제로
호출해 "새로 추가되는 문서가 있는가"만 확인한다.

각 케이스의 inspection_items는 기존 real Ollama 캐시(ranking_failure_cache.json,
k=15)의 matches 필드(field_key='inspection_item_<item>')에서 역으로 복원한다 —
이 필드는 production requirement_parser가 실제로 만들어낸 hard_requirements에서
나온 것이므로 새로 파싱하지 않고도 신뢰할 수 있다. 단, 이 방법은 "그 케이스가
실제로 검사항목으로 물어본 것"만 드러내므로 다른 구조화 필드(material/range/...)는
모른다 — 그래서 이 스크립트는 "Strategy C가 A와 달라질 수 있는 케이스 후보군"만
좁히고, 실제 최종 결과(PASS/Top1)는 그 후보군에 대해서만 real RAG 재실행으로 확정한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Set

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agent import spec_retriever  # noqa: E402
from agent.chroma_store import SimpleChromaStore  # noqa: E402
from agent.schemas import RequirementSchema  # noqa: E402

_RANKING_CACHE = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_PROD_DB_PATH = _REPO_ROOT / "chroma_db_specs"

_SUBTYPE_KEYS = ("scratch", "contamination", "particle", "pinhole", "void", "coating_non_uniformity", "edge_crack")


def _reconstruct_inspection_items(case: dict, k: str = "15") -> Set[str]:
    items = set()
    for c in case["by_k"][k]["candidates"]:
        for m in c["matches"]:
            fk = m["field_key"]
            if fk.startswith("inspection_item_"):
                items.add(fk[len("inspection_item_"):])
    return items


def main() -> None:
    cache = json.loads(_RANKING_CACHE.read_text(encoding="utf-8"))
    embeddings = spec_retriever.get_embeddings()
    vs = SimpleChromaStore(persist_directory=str(_PROD_DB_PATH), embedding_function=embeddings)

    union_keywords = []
    for key in _SUBTYPE_KEYS:
        union_keywords.extend(spec_retriever._ITEM_BOOST_KEYWORDS[key])

    orig = dict(spec_retriever._ITEM_BOOST_KEYWORDS)
    affected_cases: Dict[str, dict] = {}
    unaffected_count = 0
    try:
        for cid, case in cache["cases"].items():
            items = _reconstruct_inspection_items(case)
            if "surface_defect" not in items:
                continue  # boost 자체가 이 케이스에서 호출은 되지만 surface_defect가 없으면 A/C 동일

            req = RequirementSchema(inspection_items=sorted(items))

            spec_retriever._ITEM_BOOST_KEYWORDS.pop("surface_defect", None)
            current_docs = {spec_retriever.source_label(d) for d in spec_retriever._inspection_item_boost_docs(req, vs)}

            spec_retriever._ITEM_BOOST_KEYWORDS["surface_defect"] = tuple(union_keywords)
            hypothetical_docs = {spec_retriever.source_label(d) for d in spec_retriever._inspection_item_boost_docs(req, vs)}

            existing_pool = {c["source_document"] for c in case["by_k"]["15"]["candidates"]}
            delta = hypothetical_docs - current_docs
            new_to_pool = delta - existing_pool

            if new_to_pool:
                affected_cases[cid] = {
                    "reconstructed_inspection_items": sorted(items),
                    "existing_k15_pool_size": len(existing_pool),
                    "boost_delta_docs": sorted(delta),
                    "new_docs_not_already_in_pool": sorted(new_to_pool),
                }
            else:
                unaffected_count += 1
    finally:
        spec_retriever._ITEM_BOOST_KEYWORDS.clear()
        spec_retriever._ITEM_BOOST_KEYWORDS.update(orig)

    print(f"surface_defect를 포함하는 케이스 중 Strategy C가 실제로 candidate pool을 바꿀 수 있는 케이스: {len(affected_cases)}개")
    for cid, info in affected_cases.items():
        print(f"  {cid}: items={info['reconstructed_inspection_items']} new_docs={info['new_docs_not_already_in_pool']}")
    print(f"surface_defect 포함하지만 pool 변화 없는 케이스: {unaffected_count}개")

    out_path = _REPO_ROOT / "benchmark_results" / "strategy_c_blast_radius.json"
    out_path.write_text(json.dumps(affected_cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장됨: {out_path}")
    print(f"\nreal RAG 재실행이 필요한 케이스 목록: {sorted(affected_cases.keys())}")


if __name__ == "__main__":
    main()
