"""
langchain_chroma.Chroma를 대체하는 얇은 wrapper — chromadb를 직접 사용한다.

배경: `langchain_chroma`를 import하면 langchain_core.outputs.run_info ->
langchain_core.runnables.schema -> langchain_core.tracers.context -> langsmith ->
xxhash 순으로 전부 로드된다. LangSmith는 LangChain 팀의 별도 트레이싱/관측 SaaS
클라이언트로, 이 프로젝트 어디에서도 사용하지 않는다(LANGCHAIN_TRACING_V2나
langsmith.Client를 쓰는 코드가 없음, 직접 확인함) — 그런데도 langchain_chroma를
import하는 순간 langsmith가 통째로 로드되고, langsmith가 UUID7 생성에 xxhash의
네이티브 확장(_xxhash)을 쓴다. 사내 Windows PC의 애플리케이션 제어 정책이 이
DLL을 차단하면 RAG 코드 전체가 뜨지 못한다.

이 wrapper는 chromadb(순수 파이썬 클라이언트 라이브러리, xxhash/langsmith에
의존하지 않음을 확인함)를 직접 써서 우리가 실제로 쓰는 기능만 제공한다:
add_documents / similarity_search / similarity_search_with_score, 그리고
디버그 스크립트들이 이미 쓰고 있는 `._collection`(raw chromadb Collection,
.count()/.name/.get() 그대로 지원)도 동일한 이름으로 노출해 호출부를 바꾸지
않아도 되게 한다.

langchain_core.documents.Document는 계속 쓴다 — langchain_core만 단독으로
import해서는 langsmith/xxhash가 전혀 로드되지 않는 것을 확인했고(langchain_chroma를
거칠 때만 문제가 된다), 이미 agent/spec_retriever.py 등 다른 코드 전체가 Document
타입을 전제하고 있어 굳이 우리만의 타입으로 바꾸지 않는다.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from langchain_core.documents import Document


class SimpleChromaStore:
    """langchain_chroma.Chroma가 제공하던 기능 중 이 프로젝트가 실제로 쓰는 부분만 재구현."""

    def __init__(self, persist_directory: str, embedding_function, collection_name: str = "langchain"):
        self._embedding_function = embedding_function
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(name=collection_name)

    def add_documents(self, documents: List[Document]) -> List[str]:
        if not documents:
            return []
        texts = [d.page_content for d in documents]
        metadatas = [dict(d.metadata) if d.metadata else {} for d in documents]
        ids = [str(uuid.uuid4()) for _ in documents]
        embeddings = self._embedding_function.embed_documents(texts)
        self._collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        return ids

    def similarity_search(self, query: str, k: int = 3) -> List[Document]:
        return [doc for doc, _ in self.similarity_search_with_score(query, k=k)]

    def similarity_search_with_score(self, query: str, k: int = 3) -> List[Tuple[Document, float]]:
        count = self._collection.count()
        if count == 0 or k <= 0:
            return []
        query_embedding = self._embedding_function.embed_query(query)
        result = self._collection.query(query_embeddings=[query_embedding], n_results=min(k, count))
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        docs_and_scores: List[Tuple[Document, float]] = []
        for text, meta, dist in zip(documents, metadatas, distances):
            docs_and_scores.append((Document(page_content=text, metadata=meta or {}), dist))
        return docs_and_scores

    def get(
        self,
        limit: Optional[int] = None,
        include: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """raw chromadb Collection.get()에 그대로 위임 (디버그 스크립트용/메타데이터 필터 조회용)."""
        kwargs: Dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        if include is not None:
            kwargs["include"] = include
        if where is not None:
            kwargs["where"] = where
        return self._collection.get(**kwargs)
