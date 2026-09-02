"""
Strategy C(Exact Requirement Boost) No-Match Safety 검증 — 12개 순수 No-Match 케이스
(QA026 제외: expected_final_status=PASS로 설계된 케이스라 제외)에 대해, corpus 전체
52개 SPEC 문서 중 "자기 자신의 구조화 facts가 parsed requirement를 그대로 만족하는"
문서가 하나라도 있는지 스캔한다.

Ollama 호출 없음 — 기존 로컬 ChromaDB(_test_chroma_db_ranking_failure)에서
vector_store.get()으로 메타데이터만 읽는다(임베딩 계산 없음). production의
agent.candidate_matcher._extract_candidate_fact / agent.units.evaluate_hard_requirements를
그대로 재사용한다(재구현 없음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from agent import spec_retriever  # noqa: E402
from agent import units  # noqa: E402
from agent.candidate_matcher import _extract_candidate_fact  # noqa: E402
from agent.chroma_store import SimpleChromaStore  # noqa: E402
from langchain_core.documents import Document as LC_Document  # noqa: E402

_DB_PATH = _REPO_ROOT / "_test_chroma_db_ranking_failure"
_ROOT_CAUSE_CACHE = _REPO_ROOT / "benchmark_results" / "retrieval_root_cause_cache.json"

_TRUE_NO_MATCH_IDS = [
    "QA017", "QA018", "QA019", "QA020", "T012", "T013", "T014", "T015", "T018", "T019", "T020", "T023",
]  # QA026은 expected_final_status=PASS로 설계된 케이스라 "false PASS 금지" 대상에서 제외


def _check_boost(req: dict, facts) -> bool:
    ok_parts = []
    if req.get("measurement_range") and facts.range:
        r = req["measurement_range"]
        try:
            ok, _ = units.evaluate_hard_requirements(required_range=(r["min"], r["max"], r.get("unit") or "um"), candidate_range=facts.range)
            ok_parts.append(ok)
        except units.UnitError:
            pass
    if req.get("target", {}).get("width_mm") and facts.width_mm is not None:
        try:
            ok, _ = units.evaluate_hard_requirements(required_accuracy=(req["target"]["width_mm"], "mm", ">="), candidate_accuracy=(facts.width_mm, "mm"))
            ok_parts.append(ok)
        except units.UnitError:
            pass
    if req.get("accuracy") and req["accuracy"].get("value") is not None and facts.accuracy:
        try:
            ok, _ = units.evaluate_hard_requirements(
                required_accuracy=(req["accuracy"]["value"], req["accuracy"].get("unit") or "um", "<="), candidate_accuracy=facts.accuracy
            )
            ok_parts.append(ok)
        except units.UnitError:
            pass
    return bool(ok_parts) and all(ok_parts)


def main() -> None:
    cache = json.loads(_ROOT_CAUSE_CACHE.read_text(encoding="utf-8"))
    embeddings = spec_retriever.get_embeddings()
    vector_store = SimpleChromaStore(persist_directory=str(_DB_PATH), embedding_function=embeddings)

    spec_ids = sorted(p.name for p in (_REPO_ROOT / "sample_specs").glob("SPEC-*.md"))
    print(f"corpus 문서 수: {len(spec_ids)}")

    doc_facts = {}
    for spec_id in spec_ids:
        raw = vector_store.get(where={"filename": spec_id}, include=["documents", "metadatas"])
        docs = raw.get("documents") or []
        metas = raw.get("metadatas") or []
        lc_docs = [LC_Document(page_content=d, metadata=m or {}) for d, m in zip(docs, metas)]
        doc_facts[spec_id] = _extract_candidate_fact(lc_docs)

    total_false_pass = 0
    for test_id in _TRUE_NO_MATCH_IDS:
        req = cache["cases"][test_id]["requirement_dump"]
        fired = [spec_id for spec_id, facts in doc_facts.items() if _check_boost(req, facts)]
        status = "FALSE_PASS!" if fired else "safe"
        print(f"  {test_id:8s} [{status}] boost 발동 문서 수={len(fired)}  {fired if fired else ''}")
        total_false_pass += len(fired)

    print(f"\nStrategy C No-Match Safety: 총 False PASS 발동 = {total_false_pass} (0이면 안전)")


if __name__ == "__main__":
    main()
