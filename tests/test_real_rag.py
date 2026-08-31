"""
실제 Ollama(EMBEDDING_MODEL, 기본 bge-m3) 임베딩 + 실제 ChromaDB로 전체
파이프라인(Requirement Parsing -> Retrieval -> Candidate Extraction -> Hard
Requirement -> Ranking -> 최종 추천)이 안정적으로 동작하는지 검증한다.

기존 회귀 테스트(tests/test_regression.py, tests/test_rag_coverage.py 등)는
전부 fake-hash 임베딩(OllamaEmbeddings.embed_*를 모킹)으로 빠르고 결정론적으로
돌아간다 — 이 파일은 그 자리를 대신하지 않고, "실제 임베딩 벡터 공간에서도
검색/판정이 안정적인가"라는 별개의 질문에 답하기 위해 추가되었다.

이 파일의 테스트는 절대로 fake embedding을 모킹하지 않는다(agent.spec_
retriever.get_embeddings()가 그대로 실제 Ollama 서버를 호출하게 둔다) — 그래서
Ollama가 떠 있고 EMBEDDING_MODEL이 실제로 pull되어 있을 때만 의미가 있다.
그렇지 않은 환경(대부분의 개발/CI 환경)에서는 모듈 임포트 시점에 가용성을
확인해 전부 SKIPPED로 처리되므로, 기존 724개 테스트의 안정성에는 전혀 영향을
주지 않는다(요청서 1/8/13절).

실행:
    pytest -m real_rag -v          # Ollama가 없으면 전부 SKIPPED
    pytest -m real_rag -v -s       # 성능/비교 로그를 함께 보고 싶을 때
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Optional

import pytest
import requests

from agent.ollama_client import check_ollama_available
from agent.spec_retriever import get_embeddings, retrieve_for_requirement, source_label
from agent.candidate_matcher import build_candidates, select_best_candidate
from build_rag_ollama import build_vector_db
from tests.regression_lib import candidate_name, parse_with_empty_llm
from tests.test_rag_coverage import _current_spec_files, _indexed_unique_sources

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"
_TEST_DB = str(_REPO_ROOT / "_test_chroma_db_real_ollama")


def _configured_host() -> str:
    # main.py/agent 코드 전체와 동일한 규칙 — 임의로 다른 값을 쓰지 않는다.
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _configured_embedding_model() -> str:
    # 프로젝트 기본값과 동일 — agent/spec_retriever.py:_default_embeddings() 참고.
    return os.environ.get("EMBEDDING_MODEL", "bge-m3")


def _embedding_model_is_pulled(host: str, model: str) -> bool:
    """서버는 떠 있어도 모델이 pull되어 있지 않으면 embed 호출 자체가 실패하므로
    미리 /api/tags로 확인한다. Ollama는 태그를 붙여 보여준다(예: "bge-m3:latest")."""
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return False
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    return any(n == model or n.startswith(f"{model}:") for n in names)


def _real_rag_availability() -> tuple[bool, str]:
    host = _configured_host()
    model = _configured_embedding_model()
    if not check_ollama_available(host):
        return False, f"Ollama 서버({host})에 연결할 수 없습니다."
    if not _embedding_model_is_pulled(host, model):
        return False, f"Ollama에 embedding model '{model}'이 준비되어 있지 않습니다(ollama pull {model})."
    return True, ""


_AVAILABLE, _SKIP_REASON = _real_rag_availability()

pytestmark = [
    pytest.mark.real_rag,
    pytest.mark.skipif(not _AVAILABLE, reason=_SKIP_REASON or "실제 Ollama 환경이 아닙니다."),
]


# 요청서 4절의 5개 질문. 괄호 안은 fake-embedding Ground Truth(tests/ground_truth/
# regression_cases.json)에서 동일하거나 가장 가까운 케이스 — 완전히 동일한 문장인
# 경우에만 "expected_hint"로 참고용 비교에 쓴다(강제 일치 조건이 아니다: 실제
# 임베딩은 검색 순서가 달라질 수 있고, 그 자체는 버그가 아니다 — 요청서 5/6절).
_REAL_QUERIES = [
    {
        "id": "R1",
        "query": (
            "폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, "
            "0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘."
        ),
        "expected_hint": "ThicknessPro TP-800 또는 MultiInspect MI-800 (T001과 동일 질의)",
        "expected_source_hint": "SPEC-013.md",
    },
    {
        "id": "R2",
        "query": (
            "폭 600 mm 이상의 전극을 Inline으로 검사하면서 두께와 표면 결함을 동시에 "
            "검사할 수 있는 장비를 찾아줘. 측정 범위는 0~300 μm야."
        ),
        "expected_hint": "T002와 유사하나 정확도 조건이 없어 후보 폭이 더 넓을 수 있음(참고용)",
        "expected_source_hint": None,
    },
    {
        "id": "R3",
        "query": (
            "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 "
            "Inline 비전 검사기를 찾아줘."
        ),
        "expected_hint": "VisionInspect VI-1000 (T003과 동일 질의)",
        "expected_source_hint": "SPEC-021.md",
    },
    {
        "id": "R4",
        "query": "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘.",
        "expected_hint": "ProfileScan PS-1000 (T004와 동일 질의)",
        "expected_source_hint": "SPEC-039.md",
    },
    {
        "id": "R5",
        "query": (
            "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 "
            "검사할 수 있는 장비를 찾아줘. 정확도는 지정하지 않을게."
        ),
        "expected_hint": "MultiInspect MI-800/SPEC-051 (T005/T021/QA021과 동일 질의)",
        "expected_source_hint": "SPEC-051.md",
    },
]


@pytest.fixture(scope="module")
def timing_log():
    log: list[str] = []
    yield log
    if log:
        print("\n" + "=" * 70)
        print("실제 Ollama RAG 성능 로그 (요청서 9절)")
        print("=" * 70)
        for line in log:
            print(line)


@pytest.fixture(scope="module")
def real_embeddings():
    return get_embeddings(_configured_host())


@pytest.fixture(scope="module")
def real_indexed_db(timing_log):
    """sample_specs/ 전체를 실제 Ollama 임베딩으로 색인한다. 프로덕션
    chroma_db_specs/와 완전히 분리된 전용 디렉터리를 쓰고 종료 시 정리한다."""
    shutil.rmtree(_TEST_DB, ignore_errors=True)
    start = time.perf_counter()
    store = build_vector_db(str(_SAMPLE_SPECS_DIR), _TEST_DB, rebuild=True)
    elapsed = time.perf_counter() - start
    timing_log.append(f"전체 corpus({len(_current_spec_files())}개 파일) 실제 임베딩 색인 시간: {elapsed:.1f}초")
    yield store
    shutil.rmtree(_TEST_DB, ignore_errors=True)


# ---------------------------------------------------------------
# Test A — 실제 embedding 생성
# ---------------------------------------------------------------
def test_a_real_embedding_generation_succeeds(real_embeddings, timing_log):
    start = time.perf_counter()
    vector = real_embeddings.embed_query("전극 두께를 측정하는 비접촉식 검사 장비")
    elapsed = time.perf_counter() - start
    timing_log.append(f"embed_query() 단일 문장 임베딩 시간: {elapsed:.3f}초")

    assert vector, "embedding 생성 결과가 비어 있습니다"
    assert len(vector) > 0
    dim = len(vector)

    vector2 = real_embeddings.embed_query("Inline 방식으로 표면 결함을 검출하는 비전 검사기")
    assert len(vector2) == dim, f"embedding dimension이 일관되지 않습니다: {dim} vs {len(vector2)}"

    # bge-m3의 알려진 dimension은 1024다 — 다른 모델이 EMBEDDING_MODEL로 설정된
    # 경우도 있을 수 있으므로 정확한 값은 강제하지 않고, 최소한 상식적인 범위(4자리
    # 미만의 이상값이 아님)인지만 확인한다.
    assert dim >= 64, f"embedding dimension이 비정상적으로 작습니다: {dim}"


# ---------------------------------------------------------------
# Test B — 실제 ChromaDB 색인/검색 (요청서 4/7절)
# ---------------------------------------------------------------
def test_b_real_index_contains_full_corpus(real_indexed_db):
    """기존 tests/test_rag_coverage.py의 헬퍼를 재사용해 실제 임베딩 색인에서도
    동일한 corpus coverage 정책(하드코딩 없이 glob 기준 동적 비교)을 검증한다."""
    expected = {p.name for p in _current_spec_files()}
    indexed = _indexed_unique_sources(real_indexed_db)
    missing = expected - indexed
    assert not missing, f"실제 임베딩 색인에서 누락된 SPEC 파일: {sorted(missing)}"
    assert "SPEC-001.md" in indexed
    if (_SAMPLE_SPECS_DIR / "SPEC-052.md").exists():
        assert "SPEC-052.md" in indexed


@pytest.mark.parametrize("case", _REAL_QUERIES, ids=[c["id"] for c in _REAL_QUERIES])
def test_b_real_pipeline_end_to_end(real_indexed_db, timing_log, case):
    """
    실제 임베딩으로 retrieval -> candidate 생성 -> Hard Requirement 판정까지
    전체 경로를 실행한다. Requirement Parsing은 기존 회귀 테스트와 동일하게
    "LLM이 아무것도 못 채운 worst case"로 스텁해 deterministic 추출 계층만
    검증한다(tests/regression_lib.parse_with_empty_llm — 실제 서비스는 LLM이
    추가로 보강하므로 이보다 결과가 나쁠 수 없다). 임베딩만 실제 Ollama를 쓴다.
    """
    query = case["query"]
    t0 = time.perf_counter()
    requirement = parse_with_empty_llm(query)
    t1 = time.perf_counter()
    docs = retrieve_for_requirement(requirement, db_path=_TEST_DB, k_per_query=20)
    t2 = time.perf_counter()
    candidates = build_candidates(requirement, docs)
    chosen = select_best_candidate(candidates)
    t3 = time.perf_counter()

    timing_log.append(
        f"[{case['id']}] parse={t1 - t0:.3f}s retrieval={t2 - t1:.3f}s "
        f"candidate+rank={t3 - t2:.3f}s total={t3 - t0:.3f}s"
    )

    # --- 필수 불변식 (실제 임베딩이든 fake든 반드시 성립해야 하는 코드 정확성) ---
    assert docs, f"[{case['id']}] retrieval 결과가 비어 있습니다 — Retrieval 문제"
    assert candidates, f"[{case['id']}] candidate가 하나도 생성되지 않았습니다 — Candidate Extraction 문제"
    assert chosen is not None, f"[{case['id']}] 최종 추천 후보가 없습니다"
    assert chosen.unknown_count >= 0 and chosen.fail_count >= 0  # 음수 불가(내부 카운팅 정합성)
    if chosen.fail_count > 0:
        assert chosen.status == "FAIL", f"[{case['id']}] FAIL 항목이 있는데 status={chosen.status} — Hard Requirement Validation 문제"
    elif chosen.unknown_count > 0:
        assert chosen.status == "PARTIAL", f"[{case['id']}] UNKNOWN만 있는데 status={chosen.status} (PASS면 안 됨) — Hard Requirement Validation 문제"
    else:
        assert chosen.status == "PASS", f"[{case['id']}] FAIL/UNKNOWN이 없는데 status={chosen.status}"

    # UNKNOWN이 PASS로 둔갑하지 않았는지 — 이 프로젝트의 핵심 정책.
    for m in chosen.matches:
        assert m.result in ("PASS", "FAIL", "UNKNOWN", "N/A")
        if m.result == "UNKNOWN":
            assert m.evidence_text is None, f"[{case['id']}] {m.item}: UNKNOWN인데 evidence_text가 채워짐(허위 근거 의심)"

    # --- 참고용 비교 (강제 조건 아님 — 요청서 5/6절: 검색 순서 차이 자체는 버그가 아님) ---
    expected_source = case.get("expected_source_hint")
    retrieved_sources = {source_label(d) for d in docs}
    source_found = expected_source is None or expected_source in retrieved_sources
    print(
        f"\n[{case['id']}] query={query!r}\n"
        f"    retrieved={len(docs)}개 문서, chosen={candidate_name(chosen)} ({chosen.source_document}) "
        f"status={chosen.status} pass={chosen.pass_count} unknown={chosen.unknown_count} fail={chosen.fail_count}\n"
        f"    fake-embedding 참고값: {case['expected_hint']}\n"
        f"    참고 문서({expected_source}) 검색 포함 여부: {source_found}"
    )
    if expected_source is not None and not source_found:
        # 정책 위반은 아니지만(다른 corpus 문서가 대신 조건을 만족할 수 있음), 눈에
        # 띄지 않으면 Retrieval 품질 저하를 놓칠 수 있으므로 명시적으로 표시만 한다.
        print(
            f"    [참고] {expected_source}가 top-{len(docs)} 검색 결과에 없습니다 — "
            "버그 단정 금지, 실제 corpus 전체에서 이 조건에 더 적합한 문서가 있는지 별도 확인 필요"
        )
