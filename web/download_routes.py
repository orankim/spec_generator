"""
사양서/견적서 파일 다운로드 API — main.py에서 분리.

agent/routes.py의 "/api/agent/build-markdown"이 OUTPUT_DIR(./generated_files)에
Markdown 사양서를 쓰고 download_url로 이 엔드포인트를 가리킨다 — 전극 검사기 AI가
실제로 쓰는 공유 인프라이므로 유지한다. OUTPUT_DIR을 main.py에서 import하지 않고
agent/routes.py와 동일하게 이 파일에서도 독립적으로 "./generated_files"를 가리키게
한 것은 새로운 패턴이 아니다 — agent/routes.py가 이미 그렇게 하고 있다(같은 프로세스
안에서 항상 같은 상대경로를 가리키므로 동작은 동일하다).
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

_DOWNLOAD_MEDIA_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/api/download/{file_name}")
async def download_file(file_name: str):
    """
    생성된 사양서/견적서 파일을 다운로드합니다.
    """
    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    media_type = _DOWNLOAD_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    # 파일명 접두어는 agent/routes.py가 만든 stem 접미사("_quotation" vs
    # "_specification"/기타)로만 구분한다 — 별도 문서 타입 필드를 새로 만들지
    # 않고, 이미 파일명에 있는 정보를 그대로 재사용한다(_safe_quote_filename_stem/
    # _safe_filename_stem 참고).
    prefix = "견적서_" if "_quotation" in file_path.stem else "설비사양서_"
    return FileResponse(
        path=file_path,
        filename=f"{prefix}{file_name}",
        media_type=media_type,
    )
