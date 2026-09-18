import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# .env 파일이 있으면 로드 (없어도 조용히 무시됨 - 환경변수를 직접 export해도 동일하게 동작)
load_dotenv()

# 폐쇄망 보안 정책: 외부(HuggingFace Hub 등) 네트워크 통신 원천 차단
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# 앞서 작성한 파이프라인 모듈 임포트
from agent.routes import router as agent_router
from agent.ollama_client import check_ollama_available
from agent.paths import DEFAULT_SAMPLE_SPECS_DIR
from web.ui_routes import router as ui_router
from web.download_routes import router as download_router

app = FastAPI(title="전극 검사기 사양서 자동 생성 AI")
app.include_router(agent_router)
app.include_router(ui_router)
app.include_router(download_router)

# Typography System(요청서): 서비스 기본 서체 Spoqa Han Sans Neo. 이 앱은 "폐쇄망
# 보안 정책"(위 HF_HUB_OFFLINE 설정 참고)으로 운영되는 사내 도구라 외부 CDN에 접속할
# 수 없는 네트워크 환경에서도 동작해야 한다 — 그래서 웹폰트를 외부 CDN 링크로
# 불러오지 않고, 파일 자체(static/fonts/spoqa-han-sans-neo/, SIL OFL 1.1 라이선스로
# 재배포가 허용된 오픈소스 폰트)를 이 저장소에 포함해 직접 서빙한다. 같은 "/static"
# 마운트가 web/ui_routes.py가 링크하는 static/css/app.css, static/js/app.js도 함께
# 서빙한다(과거에는 main.py 안에 Python 문자열로 박혀 있던 것을 분리했다).
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# RAG 원본 사양서(Markdown/PPTX)가 저장되는 폴더. build_rag_ollama.py의 기본
# 입력 폴더와 항상 같은 절대경로를 가리키도록 agent/paths.py 기준값을 그대로 쓴다.
SAMPLE_SPECS_DIR = Path(DEFAULT_SAMPLE_SPECS_DIR)
SAMPLE_SPECS_DIR.mkdir(exist_ok=True)

# Ollama 서버 주소 (환경변수로 오버라이드 가능)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

if not check_ollama_available(OLLAMA_HOST):
    logger.warning(
        "Ollama 서버(%s)에 연결할 수 없습니다. 서버는 계속 기동하지만, "
        "전극 검사기 Agent 기능은 Ollama가 켜져 있어야 동작합니다.",
        OLLAMA_HOST,
    )


# ==========================================
# 실행부 (서버 개방)
# ==========================================
if __name__ == "__main__":
    import sys

    from cli_commands import run_cli

    # `python main.py render-md ...` 같은 서브커맨드면 CLI로 처리하고 종료한다.
    # 인자가 없거나 알려진 서브커맨드가 아니면(기존 `python main.py` 그대로)
    # 아래로 내려가 기존과 동일하게 웹 서버를 띄운다.
    if run_cli(sys.argv):
        sys.exit(0)

    import uvicorn
    # host="0.0.0.0" 으로 지정해야 사내망 다른 PC에서 IP로 접속 가능
    # 포트는 AGENT_PORT 환경변수로 오버라이드 가능 (기본값 8000은 기존 동작과 동일)
    port = int(os.environ.get("AGENT_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
