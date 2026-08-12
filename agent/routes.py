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

from . import ollama_client, spec_retriever
from .paths import DEFAULT_CHROMA_DB_PATH
from .pipeline import analyze_requirement, retrieve_and_generate
from .pptx_electrode_builder import ElectrodeSpecPPTXBuilder
from .requirement_parser import apply_deterministic_extraction
from .requirement_validator import validate_requirement
from .schemas import RequirementSchema, SpecificationSchema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["electrode-agent"])

# 저장소 루트 기준 절대경로가 기본값이다 — cwd에 따라 build_rag_ollama.py와
# 서로 다른 디렉터리를 가리키는 문제를 방지한다 (agent/paths.py 참고).
DB_PATH = os.environ.get("CHROMA_DB_PATH", DEFAULT_CHROMA_DB_PATH)
TEMPLATE_PATH = os.environ.get("ELECTRODE_TEMPLATE_PATH", "./template_electrode.pptx")
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

_builder: Optional[ElectrodeSpecPPTXBuilder] = None


def _get_builder() -> ElectrodeSpecPPTXBuilder:
    global _builder
    if _builder is None:
        _builder = ElectrodeSpecPPTXBuilder(template_path=TEMPLATE_PATH)
    return _builder


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
        return {
            "specification": specification.model_dump(),
            "validation": validation.model_dump(),
            "retrieved_sources": [
                {"source": spec_retriever.source_label(d), "excerpt": d.page_content[:200]}
                for d in retrieved_docs
            ],
        }
    except ollama_client.OllamaError as e:
        logger.exception("사양서 생성 중 Ollama 오류")
        raise HTTPException(status_code=502, detail=f"Ollama 호출 실패: {e}")
    except Exception as e:
        logger.exception("사양서 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))


class BuildPptxRequest(BaseModel):
    specification: Dict[str, Any]


@router.post("/build-pptx")
async def build_pptx_api(req: BuildPptxRequest):
    try:
        specification = SpecificationSchema(**req.specification)
        file_id = str(uuid.uuid4())[:8]
        output_filename = f"electrode_inspection_spec_{file_id}.pptx"
        output_path = OUTPUT_DIR / output_filename
        builder = _get_builder()
        builder.build(specification, output_path=str(output_path))
        return {
            "status": "success",
            "file_name": output_filename,
            "download_url": f"/api/download/{output_filename}",
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("PPTX 생성 실패")
        raise HTTPException(status_code=500, detail=str(e))
