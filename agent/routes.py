"""
전극 검사기 Agent용 JSON API 라우트 (APIRouter).
페이지(HTML) 라우트는 main.py에 있는 render_page()를 그대로 재사용하기 위해
main.py 쪽에 두고, 여기에는 /api/agent/* 만 둔다 (순환 import 방지).
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from renderers.markdown_renderer import render_markdown

from . import ollama_client, spec_retriever
from .paths import DEFAULT_CHROMA_DB_PATH
from .pipeline import analyze_requirement, retrieve_and_generate
from .requirement_parser import apply_deterministic_extraction
from .requirement_validator import validate_requirement
from .schemas import RequirementSchema, SpecificationSchema
from .spec_validator import build_hard_requirement_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["electrode-agent"])

# 저장소 루트 기준 절대경로가 기본값이다 — cwd에 따라 build_rag_ollama.py와
# 서로 다른 디렉터리를 가리키는 문제를 방지한다 (agent/paths.py 참고).
DB_PATH = os.environ.get("CHROMA_DB_PATH", DEFAULT_CHROMA_DB_PATH)
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)


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


class GenerateSpecRequest(BaseModel):
    requirement: Dict[str, Any]


@router.post("/generate-spec")
async def generate_spec_api(req: GenerateSpecRequest):
    try:
        requirement = RequirementSchema(**req.requirement)
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=DB_PATH)
        hard_requirement_report = build_hard_requirement_report(specification, requirement)
        return {
            "specification": specification.model_dump(),
            "validation": validation.model_dump(),
            "retrieved_sources": [
                {"source": spec_retriever.source_label(d), "excerpt": d.page_content[:200]}
                for d in retrieved_docs
            ],
            "hard_requirement_report": [r.model_dump() for r in hard_requirement_report],
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
