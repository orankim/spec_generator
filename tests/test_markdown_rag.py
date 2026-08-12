"""
RAG 원본 데이터를 PPTX에서 Markdown으로 전환한 것에 대한 테스트.

Ollama가 없는 환경이므로 임베딩만 결정론적 fake vector로 스텁하고(기존
tests/test_agent_pipeline.py와 동일한 패턴), 나머지(Markdown 파싱/heading
기반 chunking/Chroma 색인/검색/파이프라인 결합)는 실제 코드 경로를 그대로
실행해서 검증한다.
"""
import hashlib
import shutil
import tempfile
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings

from agent import spec_retriever
from agent.pipeline import retrieve_and_generate
from agent.schemas import RequirementSchema, RequirementTarget
from build_rag_ollama import build_vector_db, parse_markdown_file

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"
_MD_TEST_DB = "./_test_chroma_db_markdown"


def _fake_vector(text: str, dim: int = 32):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    arr = np.frombuffer((h * (dim // len(h) + 1))[: dim * 4], dtype=np.uint32).astype(np.float64)
    return (arr / arr.max()).tolist()


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with mock.patch.object(OllamaEmbeddings, "embed_documents", lambda self, texts: [_fake_vector(t) for t in texts]), \
         mock.patch.object(OllamaEmbeddings, "embed_query", lambda self, text: _fake_vector(text)):
        yield


@pytest.fixture(scope="module")
def md_only_dir():
    """
    sample_specs/*.md만 복사한 임시 폴더. .pptx가 전혀 없는 사용자 환경(요청서의
    "test.pptx는 삭제했다")을 재현해, 검색 결과에 pptx 출처가 섞이지 않는지
    확인하기 위함이다.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for md_file in _SAMPLE_SPECS_DIR.glob("*.md"):
            shutil.copy(md_file, Path(tmp) / md_file.name)
        yield tmp


@pytest.fixture(scope="module")
def markdown_db(fake_embeddings, md_only_dir):
    shutil.rmtree(_MD_TEST_DB, ignore_errors=True)
    store = build_vector_db(md_only_dir, _MD_TEST_DB, rebuild=True)
    assert store is not None
    yield _MD_TEST_DB
    shutil.rmtree(_MD_TEST_DB, ignore_errors=True)


# ---------------------------------------------------------------
# Test 1: sample_specs/*.md 파일들을 정상적으로 읽는다
# ---------------------------------------------------------------
def test_all_markdown_sample_specs_readable():
    md_files = sorted(_SAMPLE_SPECS_DIR.glob("*.md"))
    assert len(md_files) > 0, "sample_specs/*.md 파일이 하나도 없습니다"
    for md_file in md_files:
        docs = parse_markdown_file(str(md_file))
        assert len(docs) > 0, f"{md_file.name}에서 chunk가 하나도 만들어지지 않았습니다"


# ---------------------------------------------------------------
# Test 2: Markdown이 chunk로 정상 분할된다 (heading 구조 보존)
#
# sample_specs/*.md의 실제 파일명/헤딩 언어(한국어 "기본 정보" 계열이든, 영어
# "General" 계열이든)는 저장소마다 다를 수 있으므로, 특정 파일명이나 특정 헤딩
# 문자열에 의존하지 않고 "heading이 있으면 여러 chunk로 나뉜다"는 구조적 성질만
# 검증한다 (요청서 14절 Test 2와 동일한 취지, 특정 콘텐츠에 결합하지 않음).
# ---------------------------------------------------------------
def test_markdown_chunking_preserves_heading_structure():
    md_files = sorted(_SAMPLE_SPECS_DIR.glob("*.md"))
    assert md_files, "sample_specs/*.md가 비어 있습니다"

    for md_file in md_files:
        docs = parse_markdown_file(str(md_file))
        text = md_file.read_text(encoding="utf-8")
        h2_count = text.count("\n## ") + (1 if text.startswith("## ") else 0)
        if h2_count > 1:
            assert len(docs) > 1, f"{md_file.name}: H2 heading이 여러 개인데 chunk가 1개뿐입니다"

        for d in docs:
            # category/item 메타데이터 키 자체는 항상 존재해야 한다(값은 헤딩 유무에 따라 None일 수 있음).
            assert "category" in d.metadata
            assert "item" in d.metadata


# ---------------------------------------------------------------
# Test 3: ChromaDB에 document와 metadata가 저장된다
# ---------------------------------------------------------------
def test_chunk_metadata_has_required_keys():
    md_files = sorted(_SAMPLE_SPECS_DIR.glob("*.md"))
    md_file = md_files[0]
    docs = parse_markdown_file(str(md_file))
    assert docs, f"{md_file.name}에서 chunk가 생성되지 않았습니다"
    for d in docs:
        assert d.metadata["source"].endswith(md_file.name)
        assert d.metadata["source_type"] == "markdown"
        assert d.metadata["filename"] == md_file.name
        assert isinstance(d.metadata["chunk_id"], int)
    chunk_ids = [d.metadata["chunk_id"] for d in docs]
    assert chunk_ids == sorted(chunk_ids)
    assert chunk_ids[0] == 0


def test_build_vector_db_indexes_all_markdown_files(markdown_db):
    from agent.chroma_store import SimpleChromaStore

    embeddings = spec_retriever.get_embeddings()
    store = SimpleChromaStore(persist_directory=markdown_db, embedding_function=embeddings)
    all_docs = store.get()
    assert len(all_docs["ids"]) > 10, "10개 파일에서 chunk가 10개 초과로 나와야 함(파일당 여러 chunk)"
    assert Path(markdown_db).is_dir()


# ---------------------------------------------------------------
# Test 4 & 5: RAG 검색 결과의 source가 .md이고, pptx가 섞이지 않는다
# ---------------------------------------------------------------
def test_search_results_are_markdown_only_no_pptx(markdown_db):
    from agent.chroma_store import SimpleChromaStore

    embeddings = spec_retriever.get_embeddings()
    store = SimpleChromaStore(persist_directory=markdown_db, embedding_function=embeddings)
    results = store.similarity_search("두께 측정 정밀도", k=5)
    assert len(results) > 0
    for doc in results:
        assert doc.metadata["source"].endswith(".md")
        assert "test.pptx" not in doc.metadata["source"]
        assert doc.metadata.get("source_type") == "markdown"


# ---------------------------------------------------------------
# Test 6: 항목 단위 요구사항 검색이 Markdown 인덱스에 대해 정상 동작한다
# ---------------------------------------------------------------
def test_item_level_requirement_search_runs_against_markdown_index(markdown_db):
    requirement = RequirementSchema(
        raw_text="0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=markdown_db, k_per_query=5)
    assert len(docs) > 0
    for doc in docs:
        assert doc.metadata["source"].endswith(".md")
        assert spec_retriever.source_label(doc).endswith(".md")


def test_reported_query_returns_at_least_one_chunk_rag_only(markdown_db):
    """
    요청서 G절: "RAG만 독립적으로 검증"하는 단일 테스트. 사용자가 실제로 보고한
    질문 그대로를 RequirementParser를 거치지 않고 곧바로 RequirementSchema로
    구성해(파싱 자체는 관심사가 아니므로) retrieve_for_requirement()에 넣고,
    결과가 0개가 아님을 확인한다. 이 테스트가 실패하면 Agent 전체 파이프라인
    테스트로 넘어가기 전에 RAG 자체(build_rag_ollama.py/agent/spec_retriever.py/
    agent/paths.py)부터 다시 봐야 한다 (요청서 H절 순서).
    """
    requirement = RequirementSchema(
        raw_text="0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=markdown_db, k_per_query=5)
    assert len(docs) >= 1, (
        "RAG 검색이 0개를 반환했습니다. scripts/rag_diagnostics.py를 실제 Ollama가 켜진 "
        "환경에서 실행해 collection 개수/db_path 일치 여부를 확인하세요."
    )


# ---------------------------------------------------------------
# Test 7: 검색된 사양값이 Specification 생성 단계(프롬프트 컨텍스트)에 전달된다
# ---------------------------------------------------------------
def test_retrieved_markdown_values_flow_into_generation_context(markdown_db):
    requirement = RequirementSchema(
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=markdown_db, k_per_query=5)
    context = spec_retriever.format_context(docs)

    # context에 실제 Markdown 원문(수치/단위)이 그대로 포함돼야 SpecGenerator가
    # 근거로 삼을 수 있다 — 참고 문서 "목록"만 만들고 내용은 버리는 회귀를 잡는다.
    assert any(src.endswith(".md") for src in (spec_retriever.source_label(d) for d in docs))
    assert "μm" in context or "mm" in context or "Ω" in context or "ppm" in context


def test_generate_specification_uses_markdown_sources(markdown_db):
    """retrieve_and_generate()가 만든 Specification.sources에 .md 파일명이 들어가야 한다."""
    from agent.schemas import SpecificationSchema

    requirement = RequirementSchema(
        target=RequirementTarget(material="전극", width_mm=500),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )

    fake_llm_response = SpecificationSchema()
    fake_llm_response.equipment.name = "전극 두께 검사기 (LLM 생성)"

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(
            requirement, db_path=markdown_db, model="test-model"
        )

    assert len(retrieved_docs) > 0
    assert specification.sources, "검색된 .md 출처가 Specification.sources에 반영되어야 함"
    assert all(s.endswith(".md") for s in specification.sources)
    assert "test.pptx" not in specification.sources


# ---------------------------------------------------------------
# Test 8: 검색 결과에 없는 값은 AI(를 모킹한 LLM 응답)가 채우지 않는 이상
# Specification에 임의로 나타나지 않는다 — 즉 UNKNOWN이 조용히 VERIFIED로
# 둔갑하지 않는다.
# ---------------------------------------------------------------
def test_no_hallucination_when_llm_returns_unknown(markdown_db):
    from agent.schemas import SpecificationSchema

    requirement = RequirementSchema(
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
    )

    # 검색 결과에 실제로 없는 값(reproducibility)에 대해 LLM 모킹이 UNKNOWN을 반환했다고 가정.
    fake_llm_response = SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, _ = retrieve_and_generate(requirement, db_path=markdown_db, model="test-model")

    assert specification.measurement_performance.reproducibility_um is None
    assert specification.measurement_performance.accuracy_um is None  # 사용자도 요구 안 했고 문서에도 안 나옴(모킹) -> None 유지
