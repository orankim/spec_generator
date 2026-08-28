"""
전극 검사기 Agent용 JSON API 라우트 (APIRouter).
페이지(HTML) 라우트는 main.py에 있는 render_page()를 그대로 재사용하기 위해
main.py 쪽에 두고, 여기에는 /api/agent/* 만 둔다 (순환 import 방지).
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from renderers.docx_renderer import render_candidate_docx
from renderers.markdown_renderer import render_candidate_markdown, render_markdown

from . import candidate_matcher, ollama_client, spec_retriever
from .paths import DEFAULT_CHROMA_DB_PATH
from .pipeline import analyze_requirement, retrieve_and_generate
from .requirement_parser import apply_conversational_patch, apply_deterministic_extraction
from .requirement_validator import validate_requirement
from .schemas import CandidateEquipment, ComplianceRecord, RequirementSchema, SpecificationSchema
from .spec_validator import build_hard_requirement_report, build_inspection_item_hard_requirement_records

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["electrode-agent"])

# 저장소 루트 기준 절대경로가 기본값이다 — cwd에 따라 build_rag_ollama.py와
# 서로 다른 디렉터리를 가리키는 문제를 방지한다 (agent/paths.py 참고).
DB_PATH = os.environ.get("CHROMA_DB_PATH", DEFAULT_CHROMA_DB_PATH)
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

# Windows에서 파일명으로 쓸 수 없는 문자(\ / : * ? " < > |)를 "_"로 치환한다.
# 다운로드 파일명이 추천 장비명을 그대로 담으므로, 장비명에 이런 문자가 섞여
# 있어도(현재 corpus에는 없지만 향후 임의의 Manufacturer/Model 문자열이 들어올
# 수 있음) 안전한 파일명이 되도록 방어한다.
_UNSAFE_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]')


def _safe_filename_stem(candidate: CandidateEquipment) -> str:
    name_parts = [p for p in (candidate.manufacturer, candidate.model) if p]
    if not name_parts:
        return "equipment_specification"
    raw = "_".join(name_parts)
    sanitized = _UNSAFE_FILENAME_CHARS_RE.sub("_", raw)
    sanitized = re.sub(r"\s+", "_", sanitized).strip("_")
    return f"{sanitized}_specification" if sanitized else "equipment_specification"


class AnalyzeRequest(BaseModel):
    user_text: Optional[str] = None
    selection: Optional[Dict[str, Any]] = None
    # 추가 질문에 대한 사용자 답변을 반영해 재검증할 때, 프론트엔드가 갱신한
    # requirement 전체를 그대로 돌려보낸다.
    existing_requirement: Optional[Dict[str, Any]] = None


@router.post("/analyze-requirement")
async def analyze_requirement_api(req: AnalyzeRequest):
    try:
        if req.existing_requirement is not None:
            requirement = RequirementSchema(**req.existing_requirement)
            apply_deterministic_extraction(requirement)
            validation = validate_requirement(requirement)
        else:
            if not req.user_text and not req.selection:
                raise HTTPException(status_code=400, detail="user_text 또는 selection 중 하나는 필요합니다.")
            requirement, validation = analyze_requirement(user_text=req.user_text, selection=req.selection)
        return {"requirement": requirement.model_dump(), "validation": validation.model_dump()}
    except ollama_client.OllamaError as e:
        logger.exception("요구사항 분석 중 Ollama 오류")
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("요구사항 분석 실패")
        raise HTTPException(status_code=500, detail=str(e))


def _diff_field_paths(before: Dict[str, Any], after: Dict[str, Any], prefix: str = "") -> List[str]:
    """before/after(model_dump() 결과) 사이에서 값이 달라진 필드의 dotted path 목록을
    만든다. RequirementSchema에 종속되지 않는 범용 dict 비교라, 프로그램적으로 어떤
    필드가 바뀌었는지 확인해야 하는 다른 용도에도 재사용할 수 있다(디버깅 등) — 단,
    사용자에게 보여줄 문구는 이 경로를 그대로 노출하지 않고 아래
    _summarize_requirement_changes()가 다시 사람이 읽을 문구로 변환한다."""
    changed: List[str] = []
    keys = set(before.keys()) | set(after.keys())
    for key in sorted(keys):
        path = f"{prefix}.{key}" if prefix else key
        before_value, after_value = before.get(key), after.get(key)
        if isinstance(before_value, dict) and isinstance(after_value, dict):
            changed.extend(_diff_field_paths(before_value, after_value, path))
        elif before_value != after_value:
            changed.append(path)
    return changed


def _get_by_path(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# 내부 필드 경로 -> (표시용 개념 키, 사람이 읽는 라벨). 구조화 필드(예: accuracy)와
# 그 값을 그대로 미러링하는 레거시 float 필드(예: required_accuracy_um)가 항상 함께
# 바뀌므로(RequirementSchema.sync_legacy_fields), 같은 개념 키로 묶어 한 번만
# 보여준다 — 그렇지 않으면 "accuracy, required_accuracy_um"처럼 내부 필드명이 그대로
# 사용자에게 노출된다(실사용자 보고 버그).
_CHANGE_CONCEPT_MAP: Dict[str, tuple] = {
    "target.material": ("material", "검사 대상"),
    "target.width_mm": ("width", "폭"),
    "measurement_range": ("measurement_range", "측정 범위"),
    "accuracy": ("accuracy", "정확도"),
    "required_accuracy_um": ("accuracy", "정확도"),
    "resolution": ("resolution", "분해능"),
    "required_resolution_um": ("resolution", "분해능"),
    "minimum_defect_size": ("minimum_defect_size", "최소 검출 결함 크기"),
    "minimum_defect_size_um": ("minimum_defect_size", "최소 검출 결함 크기"),
    "measurement_speed": ("speed", "검사 속도"),
    "scan_speed_requirement": ("speed", "검사 속도"),
    "inline_offline": ("inline_offline", "검사 모드"),
    "measurement_method": ("measurement_method", "측정 방식"),
    "measurement_principle": ("measurement_principle", "측정 원리"),
    "inspection_items": ("inspection_items", "검사 항목"),
}


def _summarize_requirement_changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    _diff_field_paths()의 원시 결과(raw_text 등 내부 필드명이 그대로 담긴 dotted
    path)를 사용자에게 보여줄 수 있는 요약으로 바꾼다 — "다음 조건을 반영했습니다:
    accuracy, raw_text, required_accuracy_um" 같은 내부 데이터 구조 노출을 막기
    위함이다(실사용자 보고 버그). _CHANGE_CONCEPT_MAP에 없는 경로(raw_text 등)는
    조용히 무시하고, 매핑된 개념은 (기존 값, 새 값)을 비교해 added/changed/removed
    중 하나로 분류한다.
    """
    raw_changed = _diff_field_paths(before, after)
    seen_concepts: Dict[str, Dict[str, str]] = {}
    for path in raw_changed:
        mapping = _CHANGE_CONCEPT_MAP.get(path)
        if mapping is None:
            continue
        concept_key, label = mapping
        if concept_key in seen_concepts:
            continue
        before_value = _get_by_path(before, path)
        after_value = _get_by_path(after, path)
        before_empty = before_value is None or before_value == [] or before_value == ""
        after_empty = after_value is None or after_value == [] or after_value == ""
        if after_empty and not before_empty:
            action = "removed"
        elif before_empty and not after_empty:
            action = "added"
        else:
            action = "changed"
        seen_concepts[concept_key] = {"label": label, "action": action}
    return list(seen_concepts.values())


class UpdateRequirementRequest(BaseModel):
    current_requirement: Dict[str, Any]
    message: str


@router.post("/update-requirement")
async def update_requirement_api(req: UpdateRequirementRequest):
    """
    대화형 UI의 후속 메시지 전용 엔드포인트. /analyze-requirement(최초 메시지,
    LLM 기반 전체 파싱)와 달리 LLM을 호출하지 않는다 — 이미 여러 턴에 걸쳐 쌓인
    current_requirement에 새 메시지(message)만 근거로 삼아 결정론적으로 패치를
    적용한다(agent.requirement_parser.apply_conversational_patch). 요청서 22절
    원칙 6(대화형이라고 모든 걸 LLM에 다시 판단시키지 않는다)을 지키기 위함이다.
    """
    try:
        requirement = RequirementSchema(**req.current_requirement)
        before = requirement.model_dump()
        apply_conversational_patch(requirement, req.message)
        after = requirement.model_dump()
        validation = validate_requirement(requirement)
        return {
            "requirement": requirement.model_dump(),
            "validation": validation.model_dump(),
            "changed_fields": _diff_field_paths(before, after),
            "changed_summary": _summarize_requirement_changes(before, after),
        }
    except Exception as e:
        logger.exception("요구사항 업데이트 실패")
        raise HTTPException(status_code=500, detail=str(e))


class GenerateSpecRequest(BaseModel):
    requirement: Dict[str, Any]


@router.post("/generate-spec")
async def generate_spec_api(req: GenerateSpecRequest):
    try:
        requirement = RequirementSchema(**req.requirement)
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=DB_PATH)
        hard_requirement_report = build_hard_requirement_report(specification, requirement)

        # candidate_matcher.build_candidates()가 검사 항목(예: surface_defect/edge_defect)
        # 지원 여부까지 판정하지만, 그 판정은 SpecificationSchema에 저장되는 값이 아니라
        # (build_hard_requirement_report가 다시 계산할 수 없다) generate_specification() 내부
        # 에서만 쓰이고 버려진다. retrieved_docs는 이미 계산됐으므로 여기서 동일한 결정론적
        # 함수(재추론/LLM 호출 없음)를 다시 호출해 그 후보의 판정 결과를 화면에도 노출한다.
        candidates = candidate_matcher.build_candidates(requirement, retrieved_docs)
        chosen_candidate = candidate_matcher.select_best_candidate(candidates)
        hard_requirement_report += build_inspection_item_hard_requirement_records(chosen_candidate)

        return {
            "specification": specification.model_dump(),
            "validation": validation.model_dump(),
            "retrieved_sources": [
                {"source": spec_retriever.source_label(d), "excerpt": d.page_content[:200]}
                for d in retrieved_docs
            ],
            "hard_requirement_report": [r.model_dump() for r in hard_requirement_report],
            "chosen_candidate": chosen_candidate.model_dump() if chosen_candidate else None,
            "recommendation_reasons": chosen_candidate.recommendation_reasons if chosen_candidate else [],
            "unconfirmed_items": chosen_candidate.unconfirmed_items if chosen_candidate else [],
            "comparison_table": [
                {
                    "requirement": m.item,
                    "user_requirement": m.user_requirement_display or (f"{m.operator or ''} {m.requirement_value} {m.requirement_unit or ''}".strip() if m.requirement_value is not None else (m.requirement_text or "None")),
                    "equipment_spec": m.equipment_spec_display or (f"{m.found_value} {m.found_unit or ''}".strip() if m.found_value is not None else (m.found_text or "UNKNOWN")),
                    "status": m.result,
                    "source": m.source.document if m.source else None,
                    "section": m.source.section if m.source else None,
                    "evidence": m.evidence_text or None,
                    "margin": m.margin_display or None,
                }
                for m in (chosen_candidate.matches if chosen_candidate else [])
            ],
        }
    except ollama_client.OllamaError as e:
        logger.exception("사양서 생성 중 Ollama 오류")
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")
    except Exception as e:
        logger.exception("사양서 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))


class BuildMarkdownRequest(BaseModel):
    specification: Dict[str, Any]
    # 있으면 Markdown에 Hard Requirement/Compliance 비교 표까지 함께 채운다
    # (renderers.markdown_renderer.render_markdown의 선택적 requirement 인자).
    requirement: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None


@router.post("/build-markdown")
async def build_markdown_api(req: BuildMarkdownRequest):
    try:
        specification = SpecificationSchema(**req.specification)
        requirement = RequirementSchema(**req.requirement) if req.requirement else None
        from .schemas import ValidationResult

        validation = ValidationResult(**req.validation) if req.validation else None

        title = specification.equipment.name or f"{specification.inspection_target.material or '전극'} 검사기 사양서"
        markdown_text = render_markdown(specification, requirement=requirement, validation=validation, title=title)

        file_id = str(uuid.uuid4())[:8]
        output_filename = f"electrode_inspection_spec_{file_id}.md"
        output_path = OUTPUT_DIR / output_filename
        output_path.write_text(markdown_text, encoding="utf-8")
        return {
            "status": "success",
            "file_name": output_filename,
            "download_url": f"/api/download/{output_filename}",
        }
    except Exception as e:
        logger.exception("Markdown 사양서 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))


class BuildCandidateMarkdownRequest(BaseModel):
    candidate: Dict[str, Any]
    # 있으면 "Inspection Items" 절에 사용자가 실제로 요청한 검사 항목 목록을 채운다.
    requirement: Optional[Dict[str, Any]] = None
    # 있으면 "Requirement Compliance" 절에 Hard Requirement PASS/FAIL/UNKNOWN
    # 비교 결과를 포함한다 — /generate-spec이 이미 계산해 돌려준 값을 그대로
    # 재사용한다(재계산/재해석하지 않음, 요청서 4/11절).
    hard_requirement_report: Optional[List[Dict[str, Any]]] = None


def _build_candidate_document_inputs(req_candidate: Dict[str, Any], req_requirement: Optional[Dict[str, Any]], req_hard_requirement_report: Optional[List[Dict[str, Any]]]):
    candidate = CandidateEquipment(**req_candidate)
    requirement = RequirementSchema(**req_requirement) if req_requirement else None
    hard_requirement_report = (
        [ComplianceRecord(**r) for r in req_hard_requirement_report] if req_hard_requirement_report else None
    )
    return candidate, requirement, hard_requirement_report


@router.post("/build-candidate-markdown")
async def build_candidate_markdown_api(req: BuildCandidateMarkdownRequest):
    """
    추천 화면의 "Markdown 다운로드" 버튼용 — /generate-spec이 이미 계산해 돌려준
    chosen_candidate(CandidateEquipment, LLM을 거치지 않고 사양서 원문에서 결정론적
    으로 추출된 값)를 그대로 받아 Markdown으로 저장한다. build-markdown(LLM이 채운
    SpecificationSchema 기반)과는 별도 경로다. build-candidate-docx와 정확히 같은
    renderers.candidate_specification 데이터를 사용하므로 두 포맷의 내용이 어긋나지
    않는다.
    """
    try:
        candidate, requirement, hard_requirement_report = _build_candidate_document_inputs(
            req.candidate, req.requirement, req.hard_requirement_report
        )
        markdown_text = render_candidate_markdown(candidate, requirement=requirement, hard_requirement_report=hard_requirement_report)

        output_filename = f"{_safe_filename_stem(candidate)}.md"
        output_path = OUTPUT_DIR / output_filename
        output_path.write_text(markdown_text, encoding="utf-8")
        return {
            "status": "success",
            "file_name": output_filename,
            "download_url": f"/api/download/{output_filename}",
        }
    except Exception as e:
        logger.exception("후보 장비 Markdown 사양서 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))


class BuildCandidateDocxRequest(BaseModel):
    candidate: Dict[str, Any]
    requirement: Optional[Dict[str, Any]] = None
    hard_requirement_report: Optional[List[Dict[str, Any]]] = None


@router.post("/build-candidate-docx")
async def build_candidate_docx_api(req: BuildCandidateDocxRequest):
    """
    추천 화면의 "Word 다운로드" 버튼용 — build-candidate-markdown과 완전히 동일한
    입력(candidate/requirement/hard_requirement_report)을 받아, 같은 Structured
    Data(renderers.candidate_specification.build_candidate_specification_data)로
    Word(.docx) 문서를 만든다.
    """
    try:
        candidate, requirement, hard_requirement_report = _build_candidate_document_inputs(
            req.candidate, req.requirement, req.hard_requirement_report
        )
        docx_bytes = render_candidate_docx(candidate, requirement=requirement, hard_requirement_report=hard_requirement_report)

        output_filename = f"{_safe_filename_stem(candidate)}.docx"
        output_path = OUTPUT_DIR / output_filename
        output_path.write_bytes(docx_bytes)
        return {
            "status": "success",
            "file_name": output_filename,
            "download_url": f"/api/download/{output_filename}",
        }
    except Exception as e:
        logger.exception("후보 장비 Word 사양서 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))
