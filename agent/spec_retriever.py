"""
SpecRetriever — 요구사항(Requirement)을 바탕으로 사내 기존 사양서에서
관련 정보를 검색한다.

기존 generator.py의 `_retrieve_context`는 사용자 문장 전체로 1회
similarity_search만 수행해 슬라이드 단위 chunk를 가져온다. 이 모듈은
같은 Chroma DB(embedding 모델도 동일하게 재사용)를 쓰되:

1. 요구사항의 대상/검사항목/측정원리별로 여러 개의 타겟 질의를 만들어
   각각 검색한 뒤 병합한다 (완전한 슬라이드 대신 항목에 더 가까운 결과를
   모을 수 있다) — retrieve_for_requirement().
2. 선택적으로, PPTX 표의 각 "행"(구분/항목/사양값/비고)을 슬라이드
   전체가 아닌 개별 chunk로도 인덱싱해 진짜 항목 단위 검색이 가능하게
   하는 인덱서를 제공한다 — index_spec_rows_from_folder().
   (기존 build_rag_ollama.py의 슬라이드 단위 인덱싱은 그대로 두고,
   같은 컬렉션에 행 단위 chunk를 "추가"하는 방식이라 기존 기능을
   깨뜨리지 않는다.)
"""
from __future__ import annotations

import os
from glob import glob
from typing import Dict, List, Optional

from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document
from pptx import Presentation

from .chroma_store import SimpleChromaStore
from .paths import DEFAULT_CHROMA_DB_PATH, resolve_db_path
from .schemas import RequirementSchema

_RAG_DEBUG = os.environ.get("RAG_DEBUG", "").lower() in ("1", "true", "yes")

_ITEM_QUERY_HINTS = {
    "thickness": "두께 측정 두께 정확도 두께 분해능",
    "surface_defect": "표면 결함 검출 이물 크랙 핀홀",
    "profile_3d": "3D 형상 프로파일 높이 측정",
    "coating": "코팅 두께 도포량 loading weight",
    "edge_defect": "엣지 결함 가장자리 버 burr",
}


def _default_embeddings(host: str) -> OllamaEmbeddings:
    model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    return OllamaEmbeddings(model=model, base_url=host)


def get_embeddings(host: Optional[str] = None) -> OllamaEmbeddings:
    """
    RAG 구축(build_rag_ollama.py)과 검색(retrieve_for_requirement) 양쪽에서 반드시
    같은 임베딩 모델/서버를 쓰도록 하는 단일 소스. 두 곳이 각자 하드코딩한 값을
    쓰면 벡터 공간이 어긋나 검색이 조용히 실패하므로, 이 함수 하나만 공유한다.
    OLLAMA_HOST/EMBEDDING_MODEL 환경변수를 따른다(.env로 설정 가능).
    """
    resolved_host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    return _default_embeddings(resolved_host)


def _build_queries(requirement: RequirementSchema) -> List[str]:
    """요구사항에서 여러 개의 타겟 검색 질의를 만든다 (항목 단위 검색)."""
    queries: List[str] = []

    base_terms = []
    if requirement.target.material:
        base_terms.append(requirement.target.material)
    if requirement.measurement_principle:
        base_terms.append(requirement.measurement_principle)
    if requirement.measurement_method:
        base_terms.append(requirement.measurement_method)

    if base_terms:
        queries.append(" ".join(base_terms) + " 검사 설비")

    for item in requirement.inspection_items:
        hint = _ITEM_QUERY_HINTS.get(item, item)
        queries.append(f"{' '.join(base_terms)} {hint}".strip())

    if not queries:
        # 정보가 거의 없으면 raw_text라도 사용
        queries.append(requirement.raw_text or "전극 검사 설비 사양")

    return queries


class RetrievedChunk(Document):
    """langchain Document와 동일 — 타입 힌트 가독성을 위한 별칭."""


def retrieve_for_requirement(
    requirement: RequirementSchema,
    db_path: Optional[str] = None,
    ollama_host: Optional[str] = None,
    k_per_query: int = 3,
) -> List[Document]:
    """
    요구사항 기반 다중 질의 검색을 수행하고, (source, content) 기준으로
    중복 제거한 Document 목록을 반환한다.

    db_path를 명시하지 않으면 CHROMA_DB_PATH 환경변수 -> 저장소 루트 기준 기본값
    (agent/paths.DEFAULT_CHROMA_DB_PATH) 순으로 정해진다 — build_rag_ollama.py도
    동일한 규칙을 쓰므로, 두 프로세스를 서로 다른 작업 디렉터리에서 실행해도
    (예: 빌드는 프로젝트 루트에서, 서버는 다른 cwd에서) 항상 같은 디스크 경로를
    가리킨다. 예전에는 둘 다 "./chroma_db_specs"라는 *상대경로* 기본값을 썼는데,
    이는 각자의 cwd 기준으로 따로 해석되어 서로 다른(한쪽은 비어있는) 디렉터리를
    가리킬 수 있었다 — 예외 없이 조용히 검색 결과 0개로 이어지는 원인이었다.
    """
    resolved_db_path = resolve_db_path(db_path)
    host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    embeddings = _default_embeddings(host)
    vector_store = SimpleChromaStore(persist_directory=resolved_db_path, embedding_function=embeddings)

    queries = _build_queries(requirement)
    seen = set()
    results: List[Document] = []
    for query in queries:
        hits = vector_store.similarity_search(query, k=k_per_query)
        for doc in hits:
            key = (doc.metadata.get("source"), doc.page_content[:80])
            if key in seen:
                continue
            seen.add(key)
            results.append(doc)
        if _RAG_DEBUG:
            print(f"[RAG DEBUG] query: {query!r} -> {len(hits)}개 hit (db_path={resolved_db_path})")

    if _RAG_DEBUG:
        try:
            collection_count = vector_store._collection.count()
        except Exception:
            collection_count = "?"
        print(
            f"[RAG DEBUG] collection: {vector_store._collection.name} | "
            f"document_count: {collection_count} | queries: {len(queries)} | "
            f"retrieved_chunks(중복제거 후): {len(results)}"
        )
        for i, doc in enumerate(results, start=1):
            print(f"[RAG DEBUG]   [{i}] source: {source_label(doc)}")
            print(f"[RAG DEBUG]       content: {doc.page_content[:120]!r}")

    return results


def source_label(doc: Document) -> str:
    """
    참고 자료 출처를 사람이 읽을 짧은 형태로 만든다. 항상 짧은 파일명(filename)을
    우선하고, 없으면 source(과거 PPTX 문서는 filename 없이 source만 있을 수 있음)로
    폴백한다 — "sample_specs/spec_01.md" 같은 전체 경로가 아니라 "spec_01.md"만
    사용자/LLM에게 노출한다 (요청서 11절).
    """
    return doc.metadata.get("filename") or doc.metadata.get("source", "Unknown")


def format_context(docs: List[Document]) -> str:
    """검색 결과를 프롬프트에 넣을 수 있는 텍스트로 변환한다. Markdown(category/item)과
    PPTX(slide_number) 두 출처 형식을 모두 지원한다."""
    parts = []
    for i, doc in enumerate(docs, start=1):
        source = source_label(doc)
        if doc.metadata.get("source_type") == "markdown":
            location = doc.metadata.get("category") or doc.metadata.get("item") or ""
            if doc.metadata.get("item"):
                location = f"{doc.metadata.get('category', '')} > {doc.metadata['item']}"
            header = f"{source} ({location})" if location else source
        else:
            slide = doc.metadata.get("slide_number", "?")
            header = f"{source} Slide {slide}"
        parts.append(f"\n[참고 자료 {i} (출처: {header})]\n{doc.page_content}\n")
    return "".join(parts)


# ==========================================
# 항목(행) 단위 인덱싱 — 선택적 보강
# ==========================================
def parse_pptx_rows(file_path: str) -> List[Document]:
    """
    PPTX 표의 각 행(구분/항목/사양값/비고)을 개별 Document로 만든다.
    슬라이드 전체를 chunk로 삼는 build_rag_ollama.parse_pptx_file과 달리,
    "정확도가 얼마인가" 같은 항목 단위 질의에 더 가깝게 매칭되는 chunk를 만든다.
    """
    prs = Presentation(file_path)
    file_name = os.path.basename(file_path)
    documents: List[Document] = []

    for slide_idx, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if not shape.has_table:
                continue
            table = shape.table
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            for row in list(table.rows)[1:]:
                cells = [cell.text.strip() for cell in row.cells]
                if not any(cells):
                    continue
                row_dict = dict(zip(headers, cells))
                category = row_dict.get("구분", "")
                item = row_dict.get("항목", "")
                value = row_dict.get("사양값", "")
                note = row_dict.get("비고", "")
                content = f"[{category}] {item}: {value}" + (f" ({note})" if note else "")
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": file_name,
                            "slide_number": slide_idx,
                            "category": category,
                            "item": item,
                            "chunk_type": "spec_row",
                        },
                    )
                )
    return documents


def index_spec_rows_from_folder(
    pptx_folder: str,
    db_path: Optional[str] = None,
    ollama_host: Optional[str] = None,
) -> int:
    """
    폴더 내 모든 PPTX의 표 행을 파싱해 기존 Chroma 컬렉션에 "추가"한다.
    (기존 슬라이드 단위 chunk는 그대로 두고 보강하는 방식.)
    반환값: 추가된 chunk 수.
    """
    host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    embeddings = _default_embeddings(host)

    pptx_files = glob(os.path.join(pptx_folder, "*.pptx"))
    all_rows: List[Document] = []
    for f in pptx_files:
        all_rows.extend(parse_pptx_rows(f))

    if not all_rows:
        return 0

    vector_store = SimpleChromaStore(persist_directory=resolve_db_path(db_path), embedding_function=embeddings)
    vector_store.add_documents(all_rows)
    return len(all_rows)
