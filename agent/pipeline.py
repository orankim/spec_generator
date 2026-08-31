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
    k_per_query: int = 10,
) -> Tuple[SpecificationSchema, ValidationResult, List[Document]]:
    """
    SpecRetriever -> SpecificationGenerator -> SpecificationValidator.

    k_per_query 기본값 10(이전 5): 실제 Ollama bge-m3 임베딩 + 실제 ChromaDB(52
    SPEC, 383 chunk)로 5개 대표 질의(R1~R5)를 k=[3,5,10,20,30,50,100]로 스윕한
    결과, k<=5에서는 정답 후보 문서가 최초 top-k 검색에서 아예 누락되어(예:
    "정확도 미지정 + 두께/표면결함 동시 검사" 질의에서 SPEC-051 누락) 최종
    candidate pool 자체에 들지 못하는 사례가 있었다. k=10부터는 5개 질의 전부
    기대 후보가 검색되었고, k>=20에서는 오히려 관련 없는 대형 후보(SPEC-052 등)가
    함께 유입되며 기존에 정답으로 확인된 후보(SPEC-013/SPEC-039 등)를 밀어내는
    부작용이 관찰되었다 — k=10이 "recall 확보"와 "불필요한 후보 유입 최소화"
    사이의 가장 작은 안전한 값이다. retrieval 소요 시간은 k=5→10에서 통계적으로
    유의미한 차이가 없었다(임베딩 호출 횟수는 k와 무관하게 확장 질의 개수에만
    비례하고, ChromaDB 유사도 검색 자체는 383개 규모에서 k 증가 비용이 미미함).
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
