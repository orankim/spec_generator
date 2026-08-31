"""
Real RAG Stability 테스트 (Level 2 — Semantic Recommendation Validity).

실제 Ollama(bge-m3 임베딩 + LLM 파싱) + 실제 ChromaDB로 동일 질의를 3회 반복
실행한다. tests/test_real_rag.py(기존, 커밋됨)와 마찬가지로 real_rag 마커를
그대로 재사용하며 새 마커를 만들지 않는다. Ollama/bge-m3가 없으면 자동 SKIP —
CI/다른 개발자 PC에서 이 파일 때문에 실패하지 않는다.

핵심 원칙(요청서 4-2/12절): 실제 임베딩은 질의마다 top-k 순위가 흔들릴 수 있으므로
"Top Candidate 이름이 항상 완전히 동일해야 한다"고 가정하지 않는다. 대신 매 회차마다
Ranking Policy(PASS > PARTIAL > FAIL, 후보 풀에 실재하는 후보인지)가 지켜지는지만
검증한다 — 이름이 달라지는 것 자체는 관찰 대상이지 실패 조건이 아니다.

이 파일은 production ranking 코드를 전혀 수정하지 않고, 있는 그대로(mock 없이)
반복 호출만 한다. 결과를 강제로 동일하게 만들기 위한 어떤 코드 변경도 하지 않는다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

import pytest
from dotenv import load_dotenv

from agent.candidate_matcher import select_best_candidate
from agent.schemas import CandidateEquipment

# main.py는 기동 시 load_dotenv()를 호출하지만 pytest 단독 실행은 그 경로를 타지
# 않는다 — tests/test_retrieval_recall.py에서 이미 확인된 문제(OLLAMA_MODEL이
# .env 없이는 fallback "qwen2.5:14b"로 떨어져 실제 LLM 호출이 404로 실패)와
# 동일해 이 파일에서도 미리 로드한다.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from tests import real_rag_lib as rag  # noqa: E402

_DB_PATH = str(Path(__file__).resolve().parent.parent / "_test_chroma_db_real_rag_stability")
_REPEAT_COUNT = 3

# tests/real_rag_lib.py / scripts/verify_real_rag_r1_r5.py와 동일한 5개 질의(기존
# Ground Truth T001/T003/T004/T005와 동일 문장, T002 근접 — 새 corpus/질의를
# 만들지 않는다).
_QUERIES = [
    ("R1_thickness", "폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, 0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘."),
    ("R2_vision_defect", "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘."),
    ("R3_3d_profile", "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘."),
    ("R4_multi_item", "폭 600 mm 이상의 전극을 Inline으로 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 측정 범위는 0~300 μm이다."),
    ("R5_no_accuracy", "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 정확도는 지정하지 않을게."),
]


@pytest.fixture(scope="module")
def ollama_env():
    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        pytest.skip(f"embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")

    version = None
    try:
        proc = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            version = proc.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    print("\n" + "=" * 70)
    print("Real RAG Stability — Environment")
    print("=" * 70)
    print(f"  ollama --version : {version or '(확인 불가 — CLI 없음, API로는 서버 연결 확인됨)'}")
    print(f"  ollama_host      : {env.ollama_host}")
    print(f"  server_reachable : {env.server_reachable}")
    print(f"  EMBEDDING_MODEL  : {env.embedding_model}")
    print(f"  OLLAMA_MODEL     : {env.llm_model}")
    return env


@pytest.fixture(scope="module")
def real_db(ollama_env):
    stats = rag.build_real_vector_db(_DB_PATH)
    print(f"  ChromaDB collection : langchain (agent/chroma_store.py 기본 collection name)")
    print(f"  embedding_dimension : {stats.embedding_dimension}")
    print(f"  indexed SPEC 수      : {stats.indexed_spec_count}")
    print(f"  indexed chunk 수     : {stats.indexed_chunk_count}")
    return stats


def _assert_candidate_pool_integrity(candidates: List[CandidateEquipment], label: str) -> None:
    for c in candidates:
        assert isinstance(c.source_document, str) and c.source_document, f"[{label}] source_document 비어있음"
        assert isinstance(c.candidate_id, str) and c.candidate_id, f"[{label}] candidate_id 비어있음"
        assert c.status in ("PASS", "PARTIAL", "FAIL"), f"[{label}] status={c.status!r} 비정상"
        assert isinstance(c.matches, list), f"[{label}] matches가 list가 아님"


def _assert_ranking_policy(candidates: List[CandidateEquipment], chosen: Optional[CandidateEquipment], label: str) -> None:
    """요청서 4-2/12/15절 — Top Candidate 이름이 아니라 정책 준수 여부를 검증한다."""
    assert candidates, f"[{label}] 후보가 전혀 없습니다"
    assert chosen is not None, f"[{label}] 최종 Top Candidate가 없습니다"

    # 선택된 후보가 실제로 이번 실행의 candidate pool에 존재하는지.
    pool_ids = {c.candidate_id for c in candidates}
    assert chosen.candidate_id in pool_ids, f"[{label}] Top Candidate가 candidate pool에 없습니다"

    statuses = {c.status for c in candidates}
    if "PASS" in statuses:
        assert chosen.status == "PASS", f"[{label}] PASS 후보가 있는데 Top Candidate가 PASS가 아닙니다: {chosen.status}"
    elif "PARTIAL" in statuses:
        assert chosen.status == "PARTIAL", f"[{label}] PARTIAL 후보만 있는데 Top Candidate가 PARTIAL이 아닙니다: {chosen.status}"
    else:
        assert chosen.status == "FAIL", f"[{label}] FAIL 후보만 있는데 Top Candidate가 FAIL이 아닙니다: {chosen.status}"


@pytest.mark.real_rag
@pytest.mark.parametrize("label,query", _QUERIES, ids=[q[0] for q in _QUERIES])
def test_real_rag_repeated_runs_satisfy_ranking_policy(real_db, label, query):
    """동일 질의를 3회 반복 실행한다. Top Candidate '이름'의 완전한 동일성은
    요구하지 않는다(실제 임베딩은 순위가 흔들릴 수 있음, 요청서 4-2절) — 대신
    매 회차마다 Ranking Policy가 지켜지는지, 그리고 회차 간 이름이 같았는지를
    관찰 결과로 기록한다."""
    run_summaries = []
    for run_idx in range(1, _REPEAT_COUNT + 1):
        result = rag.run_real_case(query, real_db.db_path)
        _assert_candidate_pool_integrity(result.candidates, f"{label} run{run_idx}")
        _assert_ranking_policy(result.candidates, result.chosen, f"{label} run{run_idx}")
        run_summaries.append(
            {
                "run": run_idx,
                "top_candidate": rag.candidate_name(result.chosen),
                "source_document": result.chosen.source_document,
                "status": result.chosen.status,
                "candidate_count": len(result.candidates),
            }
        )

    print(f"\n[{label}] query={query!r}")
    for s in run_summaries:
        print(f"  Run {s['run']}: top={s['top_candidate']!r} ({s['source_document']}) status={s['status']} candidates={s['candidate_count']}")

    names = {s["top_candidate"] for s in run_summaries}
    docs = {s["source_document"] for s in run_summaries}
    statuses = {s["status"] for s in run_summaries}
    if len(names) == 1:
        print(f"  -> Top Candidate 이름이 3회 모두 동일했습니다: {names.pop()!r}")
    else:
        print(f"  -> Top Candidate 이름이 회차마다 달랐습니다(정책 위반 아님, 관찰 결과): {names}")
    if len(statuses) > 1:
        print(f"  -> [참고] status 자체도 회차마다 달랐습니다: {statuses} (그래도 각 회차의 Ranking Policy는 위에서 개별 검증됨)")
    # source_document 집합은 참고용으로만 출력 — 검증(assert)은 하지 않는다(요청서 12-C절:
    # 반복 실행 결과를 강제로 동일하게 만들기 위해 production code를 수정하지 않는다).
    _ = docs


@pytest.mark.real_rag
def test_real_rag_recommendation_reason_has_no_hallucinated_evidence(real_db):
    """요청서 13절을 실제 Ollama 환경에서도 재확인한다 — fake embedding
    파이프라인(tests/test_recommendation_stability.py)과 동일한 불변식을 실제
    임베딩+실제 LLM 파싱 경로에서도 검증한다."""
    for label, query in _QUERIES:
        result = rag.run_real_case(query, real_db.db_path)
        if result.chosen is None:
            continue
        chosen = result.chosen

        pass_items = {m.item for m in chosen.matches if m.result == "PASS"}
        for reason in chosen.recommendation_reasons:
            assert reason.startswith("✓"), f"[{label}] PASS 표시가 아닌 추천 이유: {reason!r}"
            assert any(reason.startswith(f"✓ {item}") for item in pass_items), (
                f"[{label}] 추천 이유가 실제 PASS 항목과 일치하지 않습니다: {reason!r}"
            )

        for m in chosen.matches:
            if m.result == "PASS":
                assert m.source is not None or m.evidence_text is not None, (
                    f"[{label}] '{m.item}'이 PASS인데 근거 문서/텍스트가 없습니다(환각 의심)"
                )
            if m.result == "UNKNOWN":
                assert not any(r.startswith(f"✓ {m.item}") for r in chosen.recommendation_reasons), (
                    f"[{label}] UNKNOWN 항목 '{m.item}'이 PASS로 표현되었습니다"
                )
