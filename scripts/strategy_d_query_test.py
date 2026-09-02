"""
Strategy D(Query Expansion Improvement) 소규모 실측 — 6개 현재 MISS 케이스에 대해,
이미 파싱된 RequirementSchema 구조화 값(폭/정확도/범위/검사항목)만 그대로 이어붙인
"필드 기반 질의"를 1개씩 추가로 만들어 검색해본다. 새 synonym dictionary는 전혀
만들지 않는다 — 이미 parse_requirement_text()가 뽑아낸 값만 재사용한다.

임베딩 계산만 필요(질의 몇 개 추가 검색) — LLM 호출은 없음(요청은 이미 파싱되어
retrieval_root_cause_cache.json에 저장돼 있음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agent import spec_retriever  # noqa: E402
from agent.chroma_store import SimpleChromaStore  # noqa: E402

_DB_PATH = _REPO_ROOT / "_test_chroma_db_ranking_failure"
_CACHE = _REPO_ROOT / "benchmark_results" / "retrieval_root_cause_cache.json"

_MISS_IDS = ["QA005", "QA008", "QA014", "QA015", "QA023", "T016"]


def _build_field_query(req: dict) -> str:
    parts = []
    t = req.get("target") or {}
    if t.get("width_mm"):
        parts.append(f"폭 {t['width_mm']}mm")
    mr = req.get("measurement_range")
    if mr:
        parts.append(f"측정범위 {mr['min']}~{mr['max']}{mr.get('unit','')}")
    acc = req.get("accuracy")
    if acc and acc.get("value") is not None:
        parts.append(f"정확도 {acc['value']}{acc.get('unit','')}")
    sp = req.get("measurement_speed")
    if sp and sp.get("value") is not None:
        parts.append(f"속도 {sp['value']}{sp.get('unit','')}")
    for item in req.get("inspection_items") or []:
        parts.append(str(item))
    return " ".join(parts)


def main() -> None:
    cache = json.loads(_CACHE.read_text(encoding="utf-8"))
    embeddings = spec_retriever.get_embeddings()
    vector_store = SimpleChromaStore(persist_directory=str(_DB_PATH), embedding_function=embeddings)

    for test_id in _MISS_IDS:
        case = cache["cases"][test_id]
        req = case["requirement_dump"]
        expected_spec_ids = set(case["expected_spec_ids"])
        field_query = _build_field_query(req)
        if not field_query:
            print(f"  {test_id:8s} 필드값 없음 — 스킵")
            continue

        hits = vector_store.similarity_search_with_score(field_query, k=50)
        rank = None
        for i, (doc, score) in enumerate(hits, start=1):
            if spec_retriever.source_label(doc) in expected_spec_ids:
                rank = i
                break

        prior_best = None
        for q, qhits in case["per_query_results"].items():
            for h in qhits:
                if h["source"] in expected_spec_ids:
                    if prior_best is None or h["rank"] < prior_best:
                        prior_best = h["rank"]
                    break

        improved = "IMPROVED" if (rank is not None and prior_best is not None and rank < prior_best) else ("RESCUED<=10" if (rank is not None and rank <= 10) else "no change")
        print(f"  {test_id:8s} field_query='{field_query}' -> rank={rank} (기존 best={prior_best}) [{improved}]")


if __name__ == "__main__":
    main()
