"""
실제 Ollama(bge-m3 임베딩 + qwen2.5:3b/.env OLLAMA_MODEL LLM 파싱) + 실제 ChromaDB로
RAG 파이프라인을 검증하기 위한 공유 헬퍼.

tests/regression_lib.py와 같은 자리에 있지만 정반대 목적이다: regression_lib.py는
Ollama가 "없는" 환경에서도 항상 돌아가도록 fake-hash 임베딩 + LLM 빈 응답으로
스텁하는 반면(worst-case 결정론적 추출 검증), 이 모듈은 fake/mock을 전혀 쓰지 않고
개발 PC에 실제로 떠 있는 Ollama 서버(agent/ollama_client.py, agent/spec_retriever.py가
쓰는 것과 동일한 REST API)를 그대로 호출한다.

production code(agent/*, build_rag_ollama.py)는 전혀 수정하지 않는다 — 이 모듈은
그 함수들을 있는 그대로(mock 없이) 호출만 한다.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from langchain_core.documents import Document

from agent import spec_retriever
from agent.candidate_matcher import CandidateEquipment, build_candidates, select_best_candidate
from agent.requirement_parser import parse_requirement_text
from agent.schemas import RequirementSchema

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ==========================================
# 1. 환경 점검 (요청서 2절)
# ==========================================
@dataclass
class OllamaEnvironment:
    ollama_host: str
    embedding_model: str
    llm_model: str
    server_reachable: bool
    installed_models: List[str] = field(default_factory=list)
    embedding_model_installed: bool = False
    error: Optional[str] = None


def check_ollama_environment() -> OllamaEnvironment:
    """개발 PC의 실제 Ollama 서버 연결 여부와 bge-m3 설치 여부를 확인한다.
    ollama_client.check_ollama_available()과 같은 host 규칙(OLLAMA_HOST 환경변수)을
    따르되, `ollama list`에 해당하는 /api/tags 응답에서 모델 목록까지 뽑아온다."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    llm_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    env = OllamaEnvironment(
        ollama_host=host,
        embedding_model=embedding_model,
        llm_model=llm_model,
        server_reachable=False,
    )
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        env.server_reachable = True
        env.installed_models = [m.get("name", "") for m in data.get("models", [])]
        # "bge-m3"와 "bge-m3:latest" 둘 다 매치되도록 접두어 비교.
        env.embedding_model_installed = any(
            name == embedding_model or name.split(":")[0] == embedding_model
            for name in env.installed_models
        )
    except requests.exceptions.RequestException as e:
        env.error = str(e)
    return env


# ==========================================
# 2. 실제 임베딩으로 ChromaDB 재생성 (요청서 4절)
# ==========================================
@dataclass
class RealVectorDbStats:
    db_path: str
    embedding_model: str
    embedding_dimension: Optional[int]
    indexed_spec_count: int
    indexed_chunk_count: int
    build_seconds: float


def build_real_vector_db(db_path: str, input_dir: Optional[str] = None) -> RealVectorDbStats:
    """
    sample_specs/(전체 SPEC-001~052) 를 실제 Ollama bge-m3 임베딩으로 별도
    테스트 전용 디렉터리(db_path)에 새로 인덱싱한다. 기존 chroma_db_specs/는
    전혀 건드리지 않는다. build_rag_ollama.build_vector_db()를 그대로 호출하며
    (production RAG 구축 경로), 어떤 mock/fake도 쓰지 않는다.
    """
    import shutil

    from build_rag_ollama import build_vector_db

    resolved_input_dir = input_dir or str(_REPO_ROOT / "sample_specs")
    spec_count = len(list(Path(resolved_input_dir).glob("SPEC-*.md")))

    shutil.rmtree(db_path, ignore_errors=True)
    start = time.monotonic()
    vector_store = build_vector_db(resolved_input_dir, db_path, rebuild=True)
    elapsed = time.monotonic() - start
    if vector_store is None:
        raise RuntimeError(f"build_vector_db가 None을 반환했습니다 (input_dir={resolved_input_dir}에 .md/.pptx 없음)")

    chunk_count = vector_store._collection.count()
    peek = vector_store._collection.peek(limit=1)
    dim: Optional[int] = None
    embeddings = peek.get("embeddings")
    if embeddings is not None and len(embeddings) > 0:
        dim = len(embeddings[0])

    return RealVectorDbStats(
        db_path=db_path,
        embedding_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
        embedding_dimension=dim,
        indexed_spec_count=spec_count,
        indexed_chunk_count=chunk_count,
        build_seconds=elapsed,
    )


# ==========================================
# 3. 실제 파이프라인 실행 + 타이밍 측정 (요청서 6~9절)
# ==========================================
@dataclass
class RetrievedDocInfo:
    spec_id: str
    similarity_score: Optional[float]
    location: str
    snippet: str


@dataclass
class HardRequirementRow:
    item: str
    field_key: str
    result: str
    requirement_display: Optional[str]
    equipment_display: Optional[str]
    evidence_text: Optional[str]
    source_document: Optional[str]


@dataclass
class RealRagRunResult:
    query: str
    requirement: RequirementSchema
    retrieved_docs: List[Document]
    candidates: List[CandidateEquipment]
    chosen: Optional[CandidateEquipment]
    timing: Dict[str, float]

    def top_retrieved(self, limit: int = 8) -> List[RetrievedDocInfo]:
        scored = [d for d in self.retrieved_docs if d.metadata.get("score") is not None]
        scored.sort(key=lambda d: d.metadata["score"], reverse=True)
        out = []
        for d in scored[:limit]:
            out.append(
                RetrievedDocInfo(
                    spec_id=spec_retriever.source_label(d),
                    similarity_score=d.metadata.get("score"),
                    location=f"{d.metadata.get('category') or ''} > {d.metadata.get('item') or ''}".strip(" >"),
                    snippet=d.page_content[:100].replace("\n", " "),
                )
            )
        return out

    def hard_requirement_rows(self) -> List[HardRequirementRow]:
        if self.chosen is None:
            return []
        rows = []
        for m in self.chosen.matches:
            rows.append(
                HardRequirementRow(
                    item=m.item,
                    field_key=m.field_key,
                    result=m.result,
                    requirement_display=m.user_requirement_display,
                    equipment_display=m.equipment_spec_display or m.found_text,
                    evidence_text=m.evidence_text,
                    source_document=(m.source.document if m.source else None),
                )
            )
        return rows


def run_real_case(query: str, db_path: str, k_per_query: Optional[int] = None) -> RealRagRunResult:
    """
    실제 파이프라인(agent.pipeline.run_full_pipeline과 동일한 단계 구성)을
    Ollama/ChromaDB 어느 것도 mock하지 않고 그대로 실행한다:

      parse_requirement_text (실제 LLM) -> retrieve_for_requirement (실제 bge-m3
      임베딩 + 실제 ChromaDB) -> build_candidates (LLM 없음, 결정론적) ->
      select_best_candidate (LLM 없음, 결정론적)

    k_per_query=None(기본)이면 agent/spec_retriever.retrieve_for_requirement()의
    실제 프로덕션 기본값을 그대로 물려받는다 — 이 값을 여기 다시 하드코딩하면
    나중에 프로덕션 기본값이 바뀔 때 이 헬퍼가 조용히 낡은 값을 검증하게 되므로
    (실제로 k_per_query=5->10 변경 때 한 번 이 문제가 있었다), 값을 절대 복제하지
    않고 호출을 그대로 위임한다(회귀 테스트 하네스가 쓰는 k=100이 아니라 "실제
    서비스가 쓰는 값"을 그대로 검증하기 위함).
    """
    timing: Dict[str, float] = {}

    t0 = time.monotonic()
    requirement = parse_requirement_text(query)
    timing["requirement_parsing_s"] = time.monotonic() - t0

    # "임베딩 생성 시간"의 단독 참고치 — 파이프라인이 실제로 만드는 여러 개의 확장
    # 질의(_build_queries) 중 하나를 그대로 재사용해 embed_query 1회 호출 시간만
    # 별도로 잰다. retrieve_for_requirement 내부는 이런 호출을 여러 번(질의 개수만큼)
    # 수행하므로, 이 값은 "1회 임베딩 호출"의 참고 시간이고 retrieval_s가 실제 총
    # 임베딩+검색 시간이다.
    embeddings = spec_retriever.get_embeddings()
    t1 = time.monotonic()
    _ = embeddings.embed_query(query)
    timing["single_embedding_call_s"] = time.monotonic() - t1

    t2 = time.monotonic()
    retrieve_kwargs = {"db_path": db_path}
    if k_per_query is not None:
        retrieve_kwargs["k_per_query"] = k_per_query
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, **retrieve_kwargs)
    timing["retrieval_s"] = time.monotonic() - t2

    t3 = time.monotonic()
    candidates = build_candidates(requirement, retrieved_docs)
    chosen = select_best_candidate(candidates)
    timing["candidate_extraction_s"] = time.monotonic() - t3

    timing["total_pipeline_s"] = (
        timing["requirement_parsing_s"] + timing["retrieval_s"] + timing["candidate_extraction_s"]
    )

    return RealRagRunResult(
        query=query,
        requirement=requirement,
        retrieved_docs=retrieved_docs,
        candidates=candidates,
        chosen=chosen,
        timing=timing,
    )


def candidate_name(c: Optional[CandidateEquipment]) -> str:
    if c is None:
        return "(없음)"
    return f"{c.manufacturer or '?'} {c.model or '?'}"
