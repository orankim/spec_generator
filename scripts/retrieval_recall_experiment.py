"""
Retrieval Recall 실험 스크립트 (production code 변경 전, 순수 관찰용).

R1~R5 각각을 실제 LLM로 "한 번만" 파싱한 뒤(반복 파싱은 낭비이자 시간 소모),
그 RequirementSchema를 고정한 채 k_per_query만 [3,5,10,20,30,50,100]으로 바꿔가며
agent.spec_retriever.retrieve_for_requirement()과 agent.candidate_matcher를 그대로
호출한다 — production code는 전혀 건드리지 않는다.

각 (query, k) 조합에서 기록하는 것:
  - retrieved_docs에 "기대 후보의 SPEC 파일"이 하나라도 포함되는지 (Recall hit)
  - 최종 select_best_candidate() 결과(후보명/SPEC id/status)
  - retrieval 소요 시간, 검색된 chunk/문서 수

기대 SPEC id는 tests/ground_truth/regression_cases.json의 T001/T003/T004/T005 노트에서
그대로 가져왔다(추측 아님, 이미 사람이 원본 문서를 읽고 확정해 둔 값).

사용법:
    .venv/Scripts/python.exe scripts/retrieval_recall_experiment.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

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

_DB_PATH = str(_REPO_ROOT / "chroma_db_specs_real_rag_test")

# (query_id, query_text, expected SPEC ids — ground_truth/regression_cases.json T001/T003/T004/T005 notes 그대로)
_QUERIES = [
    ("R1", "폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, 0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘.", {"SPEC-013.md", "SPEC-051.md"}),
    ("R2", "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘.", {"SPEC-021.md"}),
    ("R3", "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘.", {"SPEC-009.md", "SPEC-039.md"}),
    ("R4", "폭 600 mm 이상의 전극을 Inline으로 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 측정 범위는 0~300 μm이다.", {"SPEC-051.md"}),
    ("R5", "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 정확도는 지정하지 않을게.", {"SPEC-051.md"}),
]

_K_VALUES = [3, 5, 10, 20, 30, 50, 100]


def _section(title: str) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def main() -> int:
    _section("환경 점검")
    env = rag.check_ollama_environment()
    if not env.server_reachable or not env.embedding_model_installed:
        print(f"[BLOCKED] {env}")
        return 2
    print(f"host={env.ollama_host} embedding_model={env.embedding_model} llm_model={env.llm_model}")

    _section("실제 bge-m3 임베딩으로 ChromaDB 재생성")
    stats = rag.build_real_vector_db(_DB_PATH)
    print(f"chunks={stats.indexed_chunk_count} dim={stats.embedding_dimension} build_seconds={stats.build_seconds:.1f}")

    _section("각 질의 실제 LLM 파싱 (1회씩만, 이후 k sweep에서 재사용)")
    parsed = {}
    for qid, query, expected in _QUERIES:
        t0 = time.monotonic()
        requirement = parse_requirement_text(query)
        elapsed = time.monotonic() - t0
        parsed[qid] = requirement
        print(f"[{qid}] parse_time={elapsed:.2f}s width={requirement.target.width_mm} items={requirement.inspection_items} accuracy={requirement.required_accuracy_um}")

    _section("k sweep 실행")
    # rows: list of dict for later table rendering
    rows = []
    for k in _K_VALUES:
        for qid, query, expected in _QUERIES:
            requirement = parsed[qid]
            t0 = time.monotonic()
            docs = spec_retriever.retrieve_for_requirement(requirement, db_path=stats.db_path, k_per_query=k)
            retrieval_s = time.monotonic() - t0

            sources = {spec_retriever.source_label(d) for d in docs}
            recall_hit = bool(sources & expected)

            t1 = time.monotonic()
            candidates = build_candidates(requirement, docs)
            chosen = select_best_candidate(candidates)
            candidate_s = time.monotonic() - t1

            chosen_name = rag.candidate_name(chosen)
            chosen_spec = chosen.source_document if chosen else None
            chosen_status = chosen.status if chosen else None
            expected_candidate_chosen = chosen_spec in expected if chosen_spec else False

            row = {
                "k": k,
                "query": qid,
                "expected_specs": sorted(expected),
                "recall_hit": recall_hit,
                "retrieved_chunks": len(docs),
                "retrieved_unique_docs": len(sources),
                "chosen_name": chosen_name,
                "chosen_spec": chosen_spec,
                "chosen_status": chosen_status,
                "expected_candidate_chosen": expected_candidate_chosen,
                "retrieval_s": retrieval_s,
                "candidate_s": candidate_s,
            }
            rows.append(row)
            print(
                f"k={k:4d} {qid}  recall_hit={str(recall_hit):5s}  chosen={chosen_name!r:28s} "
                f"({chosen_spec}) status={chosen_status}  chunks={len(docs):4d} docs={len(sources):3d}  "
                f"retrieval={retrieval_s:.2f}s"
            )

    _section("Recall 요약 테이블 (k x query)")
    header = "k".rjust(5) + "".join(qid.rjust(8) for qid, _, _ in _QUERIES)
    print(header)
    for k in _K_VALUES:
        line = str(k).rjust(5)
        for qid, _, _ in _QUERIES:
            hit = next(r for r in rows if r["k"] == k and r["query"] == qid)["recall_hit"]
            line += ("HIT".rjust(8) if hit else "MISS".rjust(8))
        print(line)

    _section("최종 후보 상태 요약 테이블 (k x query, status)")
    header = "k".rjust(5) + "".join(qid.rjust(10) for qid, _, _ in _QUERIES)
    print(header)
    for k in _K_VALUES:
        line = str(k).rjust(5)
        for qid, _, _ in _QUERIES:
            st = next(r for r in rows if r["k"] == k and r["query"] == qid)["chosen_status"]
            line += str(st).rjust(10)
        print(line)

    _section("성능 영향 (retrieval_s, k별 평균)")
    for k in _K_VALUES:
        vals = [r["retrieval_s"] for r in rows if r["k"] == k]
        print(f"k={k:4d}  avg_retrieval_s={sum(vals)/len(vals):.3f}s  min={min(vals):.3f}s  max={max(vals):.3f}s")

    out_path = _REPO_ROOT / "retrieval_recall_experiment_raw.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nraw rows saved to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
