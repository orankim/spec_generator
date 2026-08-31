"""
Retrieval Recall 회귀 테스트.

배경: 실제 Ollama bge-m3 임베딩 + 실제 ChromaDB(sample_specs/ 전체 52 SPEC, 383
chunk)로 5개 대표 질의를 k_per_query=[3,5,10,20,30,50,100]로 스윕한 결과, k<=5에서는
"폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 검사할
수 있는 장비를 찾아줘. 정확도는 지정하지 않을게." 같은(측정 범위/원리 조건이 전혀
없어 range_boost/inspection_item_boost 어느 쪽도 적용되지 않는) 질의에서 정답 후보
(SPEC-051.md, MultiInspect MI-800)가 최초 top-k 검색에서 완전히 누락되어 candidate
pool 자체에 들지 못하는 사례가 실측되었다. k=10부터는 5개 질의 전부 정답 후보가
검색되었다 — agent/pipeline.py::retrieve_and_generate()의 docstring 및
agent/spec_retriever.py::retrieve_for_requirement()의 k_per_query 기본값을 5->10으로
올린 근거가 이 실험이다.

이 파일은 그 실험 결과를 두 층으로 회귀 방지한다.

1. test_default_k_per_query_is_at_least_10 (Ollama 불필요, 항상 실행):
   기본값 자체가 다시 낮아지지 않는지 결정론적으로 확인한다. tests/
   test_source_verification.py::test_default_k_per_query_is_10_not_3_or_5와
   같은 대상을 검증하지만, 이 파일은 "정확히 10"이 아니라 "10 이상"만 요구한다
   (향후 코퍼스가 커져 k를 더 올려야 할 수도 있다는 점을 감안 — 정확한 값 자체를
   지키는 것은 test_source_verification.py의 몫으로 남긴다. 이 테스트는 그
   결정이 다시 5 이하로 조용히 되돌아가는 회귀만 잡는다).

2. test_r5_style_query_retrieves_expected_candidate_at_production_default
   (real_rag 마커, 실제 Ollama 필요 — 없으면 자동 SKIP): fake-hash 임베딩은
   의미 유사도를 반영하지 않으므로(사실상 무작위 hash 거리) 이번에 실측된
   "특정 질의 유형에서 정답 후보가 top-k 밖으로 밀려난다"는 현상 자체를 fake
   임베딩으로는 재현하거나 검증할 수 없다 — 그래서 이 테스트는 real_rag
   마커로 분리하고, k_per_query를 명시적으로 넘기지 않아 실제 production
   기본값(agent/spec_retriever.retrieve_for_requirement의 기본값)을 그대로
   물려받는다. 즉 "지금 이 기본값으로 실제 서비스가 이 질의를 받으면 실제로
   정답 후보를 찾아내는가"를 직접 검증한다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent import spec_retriever
from agent.pipeline import retrieve_and_generate
from agent.requirement_parser import parse_requirement_text

# main.py는 기동 시 load_dotenv()를 호출해 .env의 OLLAMA_MODEL(예: qwen2.5:3b)을
# 읽지만, pytest로 이 파일만 단독 실행하면 그 경로를 거치지 않아 agent.ollama_client의
# 하드코딩 fallback("qwen2.5:14b", 이 dev PC에는 설치되어 있지 않음)으로 실제 LLM
# 호출이 떨어져 404로 실패한다 — 이 파일이 실제 parse_requirement_text()(실제 LLM
# 호출)를 쓰는 이 저장소의 첫 테스트라 처음 드러난 문제다. 이 파일 안에서만 .env를
# 로드해 해결한다(다른 기존 테스트는 전부 LLM을 mock/stub하므로 영향 없음).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def test_default_k_per_query_is_at_least_10():
    sig = inspect.signature(spec_retriever.retrieve_for_requirement)
    assert sig.parameters["k_per_query"].default >= 10, (
        "k_per_query 기본값이 10 미만으로 되돌아갔습니다 — 실제 bge-m3 임베딩 실험(R5 유형 질의에서 "
        "k<=5일 때 정답 후보가 검색에서 완전히 누락됨)으로 5->10으로 올린 결정이 조용히 되돌려졌을 "
        "가능성이 있습니다. agent/pipeline.py::retrieve_and_generate() docstring 참고."
    )

    sig2 = inspect.signature(retrieve_and_generate)
    assert sig2.parameters["k_per_query"].default >= 10


@pytest.mark.real_rag
def test_r5_style_query_retrieves_expected_candidate_at_production_default():
    """
    tests/real_rag_lib.py의 환경 점검/실제 DB 빌드 헬퍼를 재사용해, R5와 동일한
    질의를 "k_per_query를 아예 넘기지 않고"(=production 기본값 그대로) 실행한다.
    fake embedding으로는 검증 불가능한, 실제 의미 벡터 공간에서의 recall만
    확인하는 목적이므로 real_rag 마커로 분리한다(Ollama/bge-m3 없으면 자동 skip).
    """
    from tests import real_rag_lib as rag

    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        pytest.skip(f"embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")

    import shutil
    from pathlib import Path

    db_path = str(Path(__file__).resolve().parent.parent / "_test_chroma_db_retrieval_recall")
    try:
        stats = rag.build_real_vector_db(db_path)
        assert stats.indexed_chunk_count > 0

        query = (
            "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 "
            "검사할 수 있는 장비를 찾아줘. 정확도는 지정하지 않을게."
        )
        requirement = parse_requirement_text(query)
        # k_per_query를 명시하지 않는다 — production 기본값을 그대로 검증하는 것이 이 테스트의 목적.
        docs = spec_retriever.retrieve_for_requirement(requirement, db_path=stats.db_path)
        sources = {spec_retriever.source_label(d) for d in docs}

        assert "SPEC-051.md" in sources, (
            f"R5 유형 질의('두께+표면결함, 정확도 미지정')에서 production 기본값 k_per_query="
            f"{inspect.signature(spec_retriever.retrieve_for_requirement).parameters['k_per_query'].default}"
            f"로도 정답 후보 SPEC-051.md가 검색되지 않았습니다(Retrieval Recall 회귀). 실제 검색된 "
            f"문서: {sorted(sources)}"
        )
    finally:
        shutil.rmtree(db_path, ignore_errors=True)
