"""
RAG(ChromaDB) 색인 Coverage 회귀 테스트 (요청서 3절).

sample_specs/에 실제로 존재하는 모든 SPEC-*.md 파일이 빠짐없이 벡터 DB에
색인되어 검색 가능한지 검증한다. 다음 원칙을 지킨다.

1. "SPEC 파일 개수"를 코드에 하드코딩하지 않는다 — `Path.glob("SPEC-*.md")`로
   매 실행 시점에 실제 파일 목록을 다시 계산한다. 앞으로 SPEC-053.md 등이
   추가되어도 이 테스트는 수정 없이 그 파일까지 자동으로 검증 대상에 포함한다.
2. "SPEC 파일 개수 == chunk(문서) 개수"로 비교하지 않는다 — 파일 하나가 여러
   chunk로 쪼개질 수 있으므로, chunk metadata의 filename을 모아 만든
   *unique* source 집합과 실제 파일 목록을 비교한다.
3. 특정 회귀 방지: 가장 최근에 추가된 SPEC-051/SPEC-052가 실수로 색인에서
   빠지지 않았는지 명시적으로 확인한다(다만 이 두 파일 번호 자체를 전체
   corpus 범위의 기준으로 쓰지는 않는다 — 어디까지나 "현재 corpus에 실제로
   존재하는 파일 중 최근 것들"이라는 부수 확인일 뿐이다).
"""
from __future__ import annotations

import hashlib
import shutil
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings

from build_rag_ollama import build_vector_db

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"
_TEST_DB = "./_test_chroma_db_rag_coverage"


def _current_spec_files() -> list[Path]:
    """corpus 개수를 하드코딩하지 않고 매 실행 시점에 실제 파일을 다시 센다."""
    return sorted(_SAMPLE_SPECS_DIR.glob("SPEC-*.md"))


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
def indexed_db(fake_embeddings):
    shutil.rmtree(_TEST_DB, ignore_errors=True)
    store = build_vector_db(str(_SAMPLE_SPECS_DIR), _TEST_DB, rebuild=True)
    yield store
    shutil.rmtree(_TEST_DB, ignore_errors=True)


def _indexed_unique_sources(store) -> set[str]:
    raw = store.get(include=["metadatas"])
    metadatas = raw.get("metadatas") or []
    sources = set()
    for m in metadatas:
        name = (m or {}).get("filename") or (m or {}).get("source")
        if name:
            sources.add(name)
    return sources


def test_at_least_one_spec_file_exists():
    """전제 확인 — corpus 자체가 비어 있으면 이 파일의 나머지 테스트가 무의미하게
    통과(vacuous pass)해버리는 것을 막는다."""
    assert len(_current_spec_files()) > 0, "sample_specs/에 SPEC-*.md 파일이 하나도 없습니다"


def test_rag_index_contains_every_current_spec_file(indexed_db):
    """
    현재 실제로 존재하는 모든 SPEC-*.md 파일명이, 색인된 chunk의 metadata에
    unique source로 최소 한 번씩은 등장해야 한다. 파일 개수를 52 같은 숫자로
    하드코딩하지 않고 glob 결과와 직접 집합 비교한다.
    """
    expected_filenames = {p.name for p in _current_spec_files()}
    indexed_filenames = _indexed_unique_sources(indexed_db)

    missing = expected_filenames - indexed_filenames
    assert not missing, f"다음 SPEC 파일이 RAG 색인에서 누락되었습니다: {sorted(missing)}"


def test_rag_index_has_no_stale_or_unexpected_sources(indexed_db):
    """색인에는 실제 sample_specs/ 파일이 아닌 출처가 섞여 있으면 안 된다(예: 삭제된
    파일이 재빌드 없이 남아있는 stale 색인)."""
    expected_filenames = {p.name for p in _current_spec_files()}
    indexed_filenames = _indexed_unique_sources(indexed_db)

    unexpected = indexed_filenames - expected_filenames
    assert not unexpected, f"sample_specs/에 없는 출처가 RAG 색인에 남아있습니다: {sorted(unexpected)}"


@pytest.mark.parametrize("recent_spec_id", ["SPEC-051.md", "SPEC-052.md"])
def test_recently_added_specs_are_not_missing_from_index(indexed_db, recent_spec_id):
    """가장 최근에 추가된 SPEC-051/052가 실수로 빌드 스크립트나 파일 필터에서
    누락되지 않았는지 명시적으로 확인한다(회귀 방지용 구체적 사례)."""
    if not (_SAMPLE_SPECS_DIR / recent_spec_id).exists():
        pytest.skip(f"{recent_spec_id}가 현재 corpus에 존재하지 않습니다(전제 불충족)")
    assert recent_spec_id in _indexed_unique_sources(indexed_db)


def test_every_current_spec_file_is_individually_retrievable(indexed_db):
    """
    'chunk 개수'가 아니라 '검색으로 실제 도달 가능한가'를 파일 단위로 확인한다.
    각 SPEC 파일에 실제로 저장된 chunk 하나의 원문을 "그대로" 질의로 사용해
    similarity_search를 돌리고, 그 chunk 자신이 top-1로 나오는지 검사한다.

    주의: fake-hash 임베딩(_fake_vector)은 텍스트의 SHA-256을 그대로 벡터로
    쓰는 결정론적 함수일 뿐, 실제 임베딩처럼 "의미/부분 문자열이 비슷하면
    벡터도 가깝다"는 성질이 없다 — 문서 중간의 임의 스니펫으로 질의하면 해당
    문서의 실제 chunk 텍스트와 정확히 일치하지 않는 한 무작위에 가까운 벡터가
    나온다. 그래서 반드시 색인에 저장된 chunk의 "정확히 그 문자열"을 질의로
    써야 한다(정확히 같은 텍스트 → 정확히 같은 벡터 → 거리 0으로 자기 자신이
    최상위에 오는 것이 보장된다).
    """
    for path in _current_spec_files():
        stored = indexed_db.get(where={"filename": path.name}, include=["documents"])
        chunk_texts = stored.get("documents") or []
        assert chunk_texts, f"{path.name}: 색인에 저장된 chunk를 하나도 찾지 못했습니다"

        query_text = chunk_texts[0]
        results = indexed_db.similarity_search(query_text, k=1)
        assert results, f"{path.name}: 자기 자신의 chunk 텍스트로 질의했는데 결과가 없습니다"
        top_source = results[0].metadata.get("filename") or results[0].metadata.get("source")
        assert top_source == path.name, (
            f"{path.name}: 자기 자신의 chunk 텍스트로 질의했는데 top-1 결과가 {top_source!r}입니다"
        )
