"""
agent 패키지의 각 모듈을 순서대로 호출하는 오케스트레이션 함수.
LangChain/LangGraph 같은 Agent Framework 없이, 평범한 Python 함수 파이프라인으로
구성한다 (기획안의 가장 중요한 개발 원칙).

    RequirementParser
          v
    RequirementValidator
          v
    SpecRetriever
          v
    SpecificationGenerator
          v
    SpecificationValidator
          v
    ElectrodeSpecPPTXBuilder

향후 각 단계를 독립된 Agent/Tool로 승격하기 쉽도록, 이 파일은 각 단계를
얇게 호출만 하고 로직 자체는 각 모듈에 둔다.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from . import spec_retriever
from .requirement_parser import parse_requirement_text, requirement_from_selection
from .requirement_validator import validate_requirement
from .schemas import RequirementSchema, SpecificationSchema, ValidationResult
from .spec_generator import generate_specification
from .spec_validator import validate_specification

logger = logging.getLogger(__name__)


def analyze_requirement(
    user_text: Optional[str] = None,
    selection: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> Tuple[RequirementSchema, ValidationResult]:
    """
    자연어 또는 조건 선택 입력을 RequirementSchema로 변환하고 즉시 검증한다.
    user_text와 selection 중 하나는 반드시 있어야 한다.
    """
    if user_text:
        requirement = parse_requirement_text(user_text, model=model, host=host)
    elif selection:
        requirement = requirement_from_selection(selection)
    else:
        raise ValueError("user_text 또는 selection 중 하나는 반드시 제공해야 합니다.")

    validation = validate_requirement(requirement)
    return requirement, validation


def retrieve_and_generate(
    requirement: RequirementSchema,
    db_path: Optional[str] = None,
    ollama_host: Optional[str] = None,
    model: Optional[str] = None,
    k_per_query: int = 15,
) -> Tuple[SpecificationSchema, ValidationResult, List[Document]]:
    """
    SpecRetriever -> SpecificationGenerator -> SpecificationValidator.

    k_per_query 기본값 15(이전 10): 5개 대표 질의(R1~R5) 스윕으로 5->10을 결정한
    이력에 이어, 이번에는 Ground Truth 전체 56케이스(T001~T027, QA001~QA029,
    evaluable 43케이스)를 실제 Ollama bge-m3 임베딩 + 실제 ChromaDB(52 SPEC,
    383 chunk)로 k=[5,10,15,20] 전부 재현했다. k=10에서 Retrieval Recall
    86.0%(37/43), MISS 6건이 지속됐고, MISS 6건 전부를 k=50까지 넓혀 재검색한
    결과 전부 "정답 문서가 실제로는 순위 11~19위로 이미 검색되고 있었으나
    production top-10 컷오프 바로 밖으로 밀린" 순위 경쟁 문제로 확인됐다(어휘
    불일치/질의 확장 부족/corpus 표현 문제 등 다른 원인은 0건). k=15로 올리면
    Recall이 97.7%(42/43, MISS 6건 중 5건 해소)로 개선되고, No-Match 13개 중
    설계상 PASS 의도인 QA026을 제외한 12개 전부에서 False PASS가 0건으로
    유지됨을 실측으로 확인했다 — k=20(Recall 100%)은 Candidate Pool 증가폭이
    더 커(avg 31.4 vs k=15의 27.0) 이번에는 채택하지 않았다.
    """
    host = ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    retrieved_docs = spec_retriever.retrieve_for_requirement(
        requirement, db_path=db_path, ollama_host=host, k_per_query=k_per_query
    )
    context_text = spec_retriever.format_context(retrieved_docs)

    specification = generate_specification(
        requirement, retrieved_docs, context_text, model=model, host=host
    )
    if not retrieved_docs:
        # 검색 결과가 0개면 LLM에게 넘길 근거 자체가 없다는 뜻이다 — 이 사실을
        # 조용히 넘기지 않고 사용자가 바로 알아챌 수 있게 notes에 명시한다
        # (검색 결과 없음을 "그냥 UNKNOWN 필드들"로만 남기면 원인 파악이 어렵다).
        specification.notes.append("조건에 맞는 참고 사양서를 찾지 못했습니다 (검색된 chunk 0개). sample_specs/ 데이터와 RAG 인덱스를 확인하세요.")
    validation = validate_specification(specification, requirement=requirement)

    return specification, validation, retrieved_docs


def run_full_pipeline(
    user_text: Optional[str] = None,
    selection: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
    ollama_host: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    테스트/CLI용 편의 함수: Requirement 검증까지 통과했다는 전제 하에
    한 번에 끝까지(요구사항 -> 검색 -> 생성 -> 검증) 실행한다.
    실제 웹 UI는 requirement 확인 단계에서 사용자 입력을 한 번 더 받아야
    하므로 analyze_requirement / retrieve_and_generate를 각각 호출한다.
    """
    requirement, req_validation = analyze_requirement(
        user_text=user_text, selection=selection, model=model, host=ollama_host
    )
    if not req_validation.is_valid:
        return {
            "stage": "requirement_incomplete",
            "requirement": requirement,
            "requirement_validation": req_validation,
        }

    specification, spec_validation, retrieved_docs = retrieve_and_generate(
        requirement, db_path=db_path, ollama_host=ollama_host, model=model
    )
    return {
        "stage": "specification_ready",
        "requirement": requirement,
        "requirement_validation": req_validation,
        "specification": specification,
        "specification_validation": spec_validation,
        "retrieved_docs": retrieved_docs,
    }
