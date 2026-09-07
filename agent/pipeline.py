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

from . import candidate_matcher, quote_parser, spec_retriever
from .equipment_lookup import find_specs_by_mentioned_names
from .paths import DEFAULT_SAMPLE_SPECS_DIR
from .quote_schemas import QuoteAnalysis
from .requirement_parser import parse_requirement_text, requirement_from_selection
from .requirement_validator import validate_requirement
from .schemas import CandidateEquipment, RequirementSchema, SpecificationSchema, ValidationResult
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
    k_per_query: int = 20,
) -> Tuple[SpecificationSchema, ValidationResult, List[Document]]:
    """
    SpecRetriever -> SpecificationGenerator -> SpecificationValidator.

    k_per_query 기본값 20(이전 15): 5->10, 10->15로 올린 이력에 이어, sample_specs가
    52개(383 chunk)에서 100개(823 chunk)로 늘어난 뒤(Phase 1) 옛 k=15를 그대로
    실측 재검증했다(scripts/full_retrieval_recall_benchmark.py, 실제 bge-m3 임베딩 +
    실제 100-spec corpus, evaluable 42케이스). k=15에서 Recall이 88.1%(37/42)로,
    52개 corpus 시절 97.7%(당시 기준)에서 유의미하게 하락함을 확인했다 — corpus가
    커진 만큼 같은 k 예산으로는 더 많은 문서와 경쟁해야 하므로 당연한 결과다.
    k=20에서 Recall 97.6%(41/42)로 옛 97.7% 수준을 회복했고, k=25는 100%(42/42)를
    주지만 candidate pool이 더 늘어나는 트레이드오프가 있어(이전에도 k=20이 100%를
    주던 52-corpus 시절 "candidate pool 증가폭이 크다"는 이유로 k=15를 택한 것과
    동일한 원칙), 옛 정책과 동일하게 "high-90%대면 충분, 100%를 반드시 좇지 않는다"는
    기준으로 k=20을 선택했다. No-Match 안전성(False PASS 0건)은 k=20에서도 유지됨을
    tests/test_regression.py(56/56 PASS)로 확인했다.
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


# ==========================================
# Phase 6 — 사양 분석 + 견적 분석 통합
#
#   질문 -> Requirement Parsing -> SPEC Retrieval -> Candidate Matching
#   -> Hard Requirement -> PASS/PARTIAL/FAIL -> 후보 장비 선정 -> QUOTE 연결
#   -> 견적 분석 -> 사양 + 견적 종합 -> 근거자료 기반 답변
#
# 기존 analyze_requirement/retrieve_and_generate는 전혀 수정하지 않는다 — 아래
# 함수들은 그 위에 QUOTE 연결/분석 단계만 얇게 이어붙인 새 함수다(요청서: 기존
# Production AI Logic의 불필요한 변경 금지).
# ==========================================
def attach_quote_analyses(
    candidates: List[CandidateEquipment], quotes_dir: Optional[str] = None
) -> Dict[str, List[QuoteAnalysis]]:
    """각 후보의 source_document(예: 'SPEC-051.md')로 연결된 QUOTE를 찾아 분석한다.
    견적이 없는 후보는 결과 dict에 키 자체가 없다(빈 리스트로 채우지 않음 —
    "확인했지만 없음"과 "아직 안 봄"을 구분하지 않는 실수를 피하되, 호출부가
    `quote_analyses.get(source_document, [])`로 안전하게 다루면 된다)."""
    quote_analyses: Dict[str, List[QuoteAnalysis]] = {}
    for candidate in candidates:
        quotations = quote_parser.load_quotations_for_spec(candidate.source_document, quotes_dir=quotes_dir)
        if quotations:
            quote_analyses[candidate.source_document] = [quote_parser.analyze_quotation(q) for q in quotations]
    return quote_analyses


def analyze_with_quotes(
    requirement: RequirementSchema,
    db_path: Optional[str] = None,
    ollama_host: Optional[str] = None,
    model: Optional[str] = None,
    k_per_query: int = 20,
    quotes_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    요구조건 기반 질문("폭 800mm 이상 Inline 검사 가능한 두께+표면결함 검사기 중
    견적 비교해줘")을 위한 진입점. 기존 retrieve_and_generate + candidate_matcher
    흐름을 그대로 실행한 뒤, 도출된 모든 후보(PASS/PARTIAL/FAIL 무관 — 비교 목적에는
    FAIL 후보의 견적도 참고 가치가 있을 수 있음)에 QUOTE 분석을 이어붙인다.
    """
    specification, validation, retrieved_docs = retrieve_and_generate(
        requirement, db_path=db_path, ollama_host=ollama_host, model=model, k_per_query=k_per_query
    )
    candidates = candidate_matcher.build_candidates(requirement, retrieved_docs)
    chosen_candidate = candidate_matcher.select_best_candidate(candidates)
    quote_analyses = attach_quote_analyses(candidates, quotes_dir=quotes_dir)

    return {
        "requirement": requirement,
        "specification": specification,
        "specification_validation": validation,
        "candidates": candidates,
        "chosen_candidate": chosen_candidate,
        "quote_analyses": quote_analyses,
    }


def analyze_named_equipment(
    spec_ids: List[str],
    specs_dir: Optional[str] = None,
    quotes_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    이름/모델로 콕 집은 질문("ES-200의 사양과 견적을 같이 알려줘", "ES-200과
    MI-800을 비교해줘")을 위한 진입점. RAG 검색을 거치지 않는다 — spec_id가 이미
    확정돼 있으므로 해당 SPEC 파일 전체를 그대로 읽어(요청값과 무관하게 항상 전체
    사실을 보여줘야 하는 화면이므로 RequirementSchema()는 빈 채로 candidate_matcher
    에 넘긴다 — Hard Requirement 판정(matches)은 비어 있고 equipment_fact만 채워짐).

    각 spec_id에 대해 (candidate, quote_analyses) 쌍의 리스트를 반환한다 — SPEC은
    있지만 QUOTE가 없는 장비는 quote_analyses가 빈 리스트다(요청서 10단계 테스트
    13: "견적 없는 장비 처리").
    """
    base = specs_dir or DEFAULT_SAMPLE_SPECS_DIR
    results: List[Dict[str, Any]] = []
    for spec_id in spec_ids:
        clean_id = spec_id if spec_id.upper().startswith("SPEC-") else f"SPEC-{spec_id}"
        clean_id = os.path.splitext(clean_id)[0]
        path = os.path.join(base, f"{clean_id}.md")
        if not os.path.exists(path):
            results.append({"spec_id": clean_id, "found": False, "candidate": None, "quote_analyses": []})
            continue
        text = open(path, "r", encoding="utf-8").read()
        doc = Document(page_content=text, metadata={"filename": f"{clean_id}.md", "source": f"{clean_id}.md"})
        candidates = candidate_matcher.build_candidates(RequirementSchema(), [doc])
        candidate = candidates[0] if candidates else None
        quotations = quote_parser.load_quotations_for_spec(clean_id, quotes_dir=quotes_dir)
        analyses = [quote_parser.analyze_quotation(q) for q in quotations]
        results.append({"spec_id": clean_id, "found": candidate is not None, "candidate": candidate, "quote_analyses": analyses})
    return {"equipment": results}
