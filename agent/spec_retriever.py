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

from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document
from pptx import Presentation

from .schemas import RequirementSchema

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
    db_path: str = "./chroma_db_specs",
    ollama_host: Optional[str] = None,
    k_per_query: int = 3,
) -> List[Document]:
    """
    요구사항 기반 다중 질의 검색을 수행하고, (source, content) 기준으로
    중복 제거한 Document 목록을 반환한다.
    """
    host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    embeddings = _default_embeddings(host)
    vector_store = Chroma(persist_directory=db_path, embedding_function=embeddings)

    queries = _build_queries(requirement)
    seen = set()
    results: List[Document] = []
    for query in queries:
        for doc in vector_store.similarity_search(query, k=k_per_query):
            key = (doc.metadata.get("source"), doc.page_content[:80])
            if key in seen:
                continue
            seen.add(key)
            results.append(doc)

    return results


def format_context(docs: List[Document]) -> str:
    """검색 결과를 프롬프트에 넣을 수 있는 텍스트로 변환한다."""
    parts = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "Unknown")
        slide = doc.metadata.get("slide_number", "?")
        parts.append(f"\n[참고 자료 {i} (출처: {source} Slide {slide})]\n{doc.page_content}\n")
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
    db_path: str = "./chroma_db_specs",
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

    vector_store = Chroma(persist_directory=db_path, embedding_function=embeddings)
    vector_store.add_documents(all_rows)
    return len(all_rows)
