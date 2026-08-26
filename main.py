import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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

app = FastAPI(title="전극 검사기 사양서 자동 생성 AI")
app.include_router(agent_router)

# 생성된 사양서 파일이 임시 저장될 폴더. agent/routes.py의 "/api/agent/build-markdown"이
# 이 폴더(상대경로 "./generated_files")에 파일을 쓰고, 아래 "/api/download/{file_name}"이
# 그 파일을 서빙한다 — Agent가 실제로 쓰는 공유 인프라이므로 유지한다.
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

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
# 1. 공통 페이지 레이아웃 (공통 스타일)
# ==========================================
PAGE_STYLE = """
    :root {
        color-scheme: light;
        --bg-main: #ffffff;
        --bg-sidebar: #f8fafc;
        --bg-iconbar: #f1f5f9;
        --border-color: #e2e8f0;
        --border-subtle: #f1f5f9;
        --text-primary: #0f172a;
        --text-secondary: #475569;
        --text-muted: #94a3b8;
        --accent-primary: #2563eb;
        --accent-hover: #1d4ed8;
        --accent-light: #eff6ff;
        --card-bg: #ffffff;
        --user-bubble-bg: #edf2f7;
        --user-bubble-border: #cbd5e1;
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; overflow: hidden; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "맑은 고딕", sans-serif;
        background: var(--bg-main);
        color: var(--text-primary);
        -webkit-font-smoothing: antialiased;
    }

    /* ===== 3단 레이아웃: 아이콘 사이드바 + 대화 관리 사이드바 + 메인 대화 영역 ===== */
    .shell { display: flex; height: 100vh; width: 100%; background: var(--bg-main); }

    /* 1) 좌측 아이콘 바 (약 52px) */
    .icon-sidebar {
        width: 52px;
        flex-shrink: 0;
        background: var(--bg-iconbar);
        border-right: 1px solid var(--border-color);
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 14px 0;
        gap: 14px;
        z-index: 10;
    }
    .icon-btn {
        width: 36px;
        height: 36px;
        border: none;
        background: transparent;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-secondary);
        transition: all 0.15s ease;
    }
    .icon-btn:hover:not(:disabled) { background: #e2e8f0; color: var(--text-primary); }
    .icon-btn.icon-btn-active { background: var(--accent-primary); color: #ffffff; }
    .icon-btn.icon-btn-active:hover { background: var(--accent-hover); }
    .icon-btn.icon-btn-ghost { color: var(--text-muted); cursor: default; }
    .icon-sidebar-spacer { flex: 1; }

    /* 2) 대화 관리 사이드바 (약 260px) */
    .conv-sidebar {
        width: 260px;
        flex-shrink: 0;
        background: var(--bg-sidebar);
        border-right: 1px solid var(--border-color);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: width .2s ease, opacity .2s ease;
    }
    .shell.sidebar-collapsed .conv-sidebar { width: 0; opacity: 0; border-right: none; }

    .conv-sidebar-header {
        padding: 18px 18px 14px;
        border-bottom: 1px solid var(--border-color);
        flex-shrink: 0;
    }
    .conv-sidebar-header h1 {
        font-size: 15px;
        margin: 0;
        color: var(--text-primary);
        font-weight: 700;
        letter-spacing: -0.01em;
    }
    .conv-sidebar-header p {
        font-size: 12px;
        margin: 4px 0 0;
        color: var(--text-secondary);
    }

    .conv-action-row {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        border: none;
        background: transparent;
        text-align: left;
        padding: 11px 18px;
        font-size: 13px;
        font-weight: 600;
        color: var(--text-primary);
        cursor: pointer;
        flex-shrink: 0;
        transition: background 0.15s ease;
    }
    .conv-action-row:hover { background: #e2e8f0; }
    .conv-action-icon { font-size: 14px; width: 18px; text-align: center; color: var(--accent-primary); flex-shrink: 0; }

    .conv-search-box { padding: 0 16px 10px; flex-shrink: 0; }
    .conv-search-box input {
        width: 100%;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        padding: 7px 11px;
        font-size: 13px;
        font-family: inherit;
        background: #ffffff;
        color: var(--text-primary);
    }
    .conv-search-box input:focus { outline: none; border-color: var(--accent-primary); box-shadow: 0 0 0 2px rgba(37,99,235,0.15); }

    .conv-list-label {
        padding: 12px 18px 6px;
        font-size: 11px;
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.04em;
        flex-shrink: 0;
    }
    .conv-list { flex: 1; overflow-y: auto; padding-bottom: 14px; }
    .conv-group-label { padding: 10px 18px 4px; font-size: 11px; font-weight: 700; color: var(--text-muted); }
    .conv-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        border: none;
        background: transparent;
        text-align: left;
        padding: 9px 18px;
        font-size: 13px;
        color: var(--text-secondary);
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        transition: background 0.12s ease;
    }
    .conv-item:hover { background: #e2e8f0; color: var(--text-primary); }
    .conv-item.active { background: #e2e8f0; font-weight: 600; color: var(--accent-primary); }
    .conv-item-title { overflow: hidden; text-overflow: ellipsis; flex: 1; }
    .conv-item-delete {
        opacity: 0;
        border: none;
        background: transparent;
        color: #ef4444;
        font-size: 12px;
        cursor: pointer;
        padding: 2px 6px;
        border-radius: 4px;
    }
    .conv-item:hover .conv-item-delete { opacity: 1; }
    .conv-item-delete:hover { background: #fee2e2; }
    .conv-empty { padding: 12px 18px; font-size: 12px; color: var(--text-muted); text-align: center; }

    /* 3) 메인 대화 영역 (Flex 1) */
    .main-chat {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        background: var(--bg-main);
        position: relative;
    }

    /* ===== 메인 대화 스크롤 영역 ===== */
    .messages {
        flex: 1;
        overflow-y: auto;
        padding: 32px 24px 24px;
        display: flex;
        flex-direction: column;
        gap: 20px;
        scroll-behavior: smooth;
    }
    .messages-inner {
        max-width: 920px;
        width: 100%;
        margin: 0 auto;
        display: flex;
        flex-direction: column;
        gap: 24px;
    }
    .messages.is-empty { justify-content: center; align-items: center; }

    /* State A: 홈 화면 / 새로운 대화 */
    .welcome-block {
        text-align: center;
        max-width: 600px;
        margin: auto;
        padding: 40px 20px;
    }
    .welcome-icon {
        width: 54px;
        height: 54px;
        background: var(--accent-light);
        color: var(--accent-primary);
        border-radius: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 26px;
        margin: 0 auto 20px;
        box-shadow: 0 2px 8px rgba(37, 99, 235, 0.1);
    }
    .welcome-block h2 {
        font-size: 22px;
        margin: 0 0 12px;
        color: var(--text-primary);
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    .welcome-block p {
        font-size: 15px;
        margin: 0 0 28px;
        color: var(--text-secondary);
        line-height: 1.6;
    }

    /* 예시 질문 칩 */
    .chip-container {
        display: flex;
        flex-direction: column;
        gap: 8px;
        text-align: left;
        margin-top: 10px;
    }
    .chip-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-muted);
        margin-bottom: 4px;
        letter-spacing: 0.02em;
    }
    .chip-item {
        border: 1px solid var(--border-color);
        background: #ffffff;
        color: var(--text-primary);
        border-radius: 10px;
        padding: 11px 16px;
        font-size: 13.5px;
        cursor: pointer;
        text-align: left;
        transition: all 0.15s ease;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .chip-item:hover {
        border-color: var(--accent-primary);
        background: var(--accent-light);
        color: var(--accent-primary);
        transform: translateY(-1px);
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }
    .chip-arrow { font-size: 14px; color: var(--text-muted); }
    .chip-item:hover .chip-arrow { color: var(--accent-primary); }

    /* State B & C: 메시지 행 구조 */
    .msg-row { display: flex; width: 100%; }
    .msg-row.user { justify-content: flex-end; margin-bottom: 4px; }
    .msg-row.ai { justify-content: flex-start; }

    /* 사용자 질문 Bubble: 작고 절제된 우측 상단 Bubble */
    .bubble-user {
        background: var(--user-bubble-bg);
        color: var(--text-primary);
        border: 1px solid var(--user-bubble-border);
        border-radius: 16px 16px 4px 16px;
        padding: 10px 16px;
        font-size: 14px;
        line-height: 1.55;
        max-width: 72%;
        word-break: break-word;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }

    /* AI 문서형 콘텐츠 Container */
    .ai-doc-container {
        width: 100%;
        background: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
        margin-top: 2px;
    }

    /* ===== Markdown body styling ===== */
    .md-body { line-height: 1.7; font-size: 14.5px; color: var(--text-primary); }
    .md-body .md-p { margin: 0 0 12px; white-space: pre-wrap; word-break: break-word; }
    .md-body .md-p:last-child { margin-bottom: 0; }
    .md-body .md-heading { margin: 18px 0 10px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.01em; }
    .md-body h1.md-heading { font-size: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }
    .md-body h2.md-heading { font-size: 17px; }
    .md-body h3.md-heading { font-size: 15.5px; }
    .md-body h4.md-heading { font-size: 14.5px; }
    .md-body ul.md-list, .md-body ol.md-list { margin: 8px 0 14px; padding-left: 22px; }
    .md-body li { margin: 4px 0; }
    .md-body hr.md-hr { border: none; border-top: 1px solid var(--border-color); margin: 20px 0; }
    .md-body code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; color: #0f172a; }
    .md-body pre.md-code { background: #0f172a; color: #f8fafc; padding: 14px 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; margin: 12px 0; }
    .md-body pre.md-code code { background: transparent; padding: 0; color: inherit; }
    .md-body table.md-table { border-collapse: collapse; margin: 12px 0; font-size: 13.5px; width: 100%; }
    .md-body table.md-table th, .md-body table.md-table td { border: 1px solid var(--border-color); padding: 8px 12px; text-align: left; }
    .md-body table.md-table th { background: #f8fafc; font-weight: 700; color: var(--text-primary); }

    /* ===== State C: 검색 및 분석 진행 상태 UI ===== */
    .progress-card {
        background: #ffffff;
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.03);
    }
    .progress-header {
        font-size: 15px;
        font-weight: 700;
        color: var(--text-primary);
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 16px;
    }
    .progress-steps {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .progress-step {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 13.5px;
        color: var(--text-secondary);
    }
    .progress-step.done { color: var(--text-primary); font-weight: 500; }
    .progress-step-icon {
        width: 22px;
        height: 22px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        flex-shrink: 0;
    }
    .progress-step.done .progress-step-icon { background: #dcfce7; color: #15803d; }
    .progress-step.running .progress-step-icon { background: #dbeafe; color: var(--accent-primary); }
    .progress-step.pending .progress-step-icon { background: #f1f5f9; color: var(--text-muted); }

    /* 진행 중 candidate list preview */
    .candidate-preview-box {
        margin-top: 16px;
        padding-top: 14px;
        border-top: 1px dashed var(--border-color);
    }
    .candidate-preview-title { font-size: 12px; font-weight: 700; color: var(--text-muted); margin-bottom: 8px; }
    .candidate-preview-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 10px;
        background: #f8fafc;
        border-radius: 6px;
        margin-bottom: 6px;
        font-size: 12.5px;
        color: var(--text-primary);
    }
    .candidate-preview-badge { font-size: 11px; background: #e2e8f0; color: var(--text-secondary); padding: 2px 6px; border-radius: 4px; }

    /* ===== 장비 추천 결과 카드 UI ===== */
    .equipment-card {
        background: #ffffff;
        border: 1px solid var(--border-color);
        border-radius: 10px;
        overflow: hidden;
        margin-top: 12px;
    }
    .equipment-card-header {
        padding: 14px 18px;
        background: #f8fafc;
        border-bottom: 1px solid var(--border-color);
        font-weight: 700;
        font-size: 15px;
        color: var(--text-primary);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .equipment-card-body { padding: 18px; }

    /* 요약 충족 여부 찌르기 버너 */
    .compliance-summary-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 10px;
        margin-bottom: 16px;
    }
    .compliance-item {
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .compliance-item.pass { background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; }
    .compliance-item.fail { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; }
    .compliance-item.unknown { background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }
    .compliance-item-icon { font-weight: 700; font-size: 14px; }

    /* 상세 사양 Key-Value Table */
    .spec-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        margin-top: 12px;
    }
    @media (max-width: 640px) { .spec-grid { grid-template-columns: 1fr; } }
    .spec-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        background: #f8fafc;
        border-radius: 6px;
        font-size: 13px;
    }
    .spec-label { color: var(--text-secondary); }
    .spec-value { font-weight: 600; color: var(--text-primary); text-align: right; }

    /* ===== 참고 문서 (References) 영역 ===== */
    .references-section {
        margin-top: 24px;
        padding-top: 16px;
        border-top: 1px solid var(--border-color);
    }
    .references-title {
        font-size: 12.5px;
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.03em;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .reference-list { display: flex; flex-direction: column; gap: 6px; }
    .reference-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        background: #f8fafc;
        border: 1px solid var(--border-subtle);
        border-radius: 6px;
        font-size: 13px;
        color: var(--text-primary);
    }
    .reference-name { display: flex; align-items: center; gap: 8px; font-weight: 500; }
    .reference-action { font-size: 12px; color: var(--accent-primary); text-decoration: none; cursor: pointer; }
    .reference-action:hover { text-decoration: underline; }

    /* ===== 추가 질문 제안 (Related Questions) 영역 ===== */
    .related-section {
        margin-top: 24px;
        padding-top: 16px;
        border-top: 1px dashed var(--border-color);
    }
    .related-title {
        font-size: 12.5px;
        font-weight: 700;
        color: var(--text-muted);
        letter-spacing: 0.03em;
        margin-bottom: 10px;
    }
    .related-list { display: flex; flex-direction: column; gap: 6px; }
    .related-btn {
        text-align: left;
        background: #ffffff;
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 9px 14px;
        font-size: 13px;
        color: var(--text-primary);
        cursor: pointer;
        transition: all 0.15s ease;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .related-btn:hover {
        border-color: var(--accent-primary);
        background: var(--accent-light);
        color: var(--accent-primary);
    }

    /* ===== 에러 메시지 & Retry 버튼 ===== */
    .error-card {
        background: #fef2f2;
        border: 1px solid #fecaca;
        border-radius: 10px;
        padding: 16px 20px;
        color: #991b1b;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
    }
    .retry-btn {
        background: #dc2626;
        color: #ffffff;
        border: none;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        flex-shrink: 0;
    }
    .retry-btn:hover { background: #b91c1c; }

    /* ===== 하단 공통 질문 입력창 ===== */
    .input-bar-wrapper {
        padding: 16px 24px;
        background: var(--bg-main);
        flex-shrink: 0;
    }
    .input-bar-inner {
        max-width: 920px;
        margin: 0 auto;
    }
    .input-box {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 20px;
        padding: 8px 12px 8px 16px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .input-box:focus-within {
        border-color: var(--accent-primary);
        box-shadow: 0 2px 12px rgba(37,99,235,0.12);
    }
    .input-box textarea {
        flex: 1;
        border: none;
        background: transparent;
        resize: none;
        padding: 6px 0;
        font-size: 14.5px;
        font-family: inherit;
        color: var(--text-primary);
        max-height: 160px;
        line-height: 1.5;
    }
    .input-box textarea:focus { outline: none; }
    .input-action-btn {
        width: 34px;
        height: 34px;
        border-radius: 50%;
        border: none;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        flex-shrink: 0;
        transition: background 0.15s ease;
    }
    .attach-btn { background: transparent; color: var(--text-secondary); font-size: 16px; }
    .attach-btn:hover { background: #f1f5f9; color: var(--text-primary); }
    .send-btn { background: var(--accent-primary); color: #ffffff; font-size: 15px; font-weight: 700; }
    .send-btn:hover:not(:disabled) { background: var(--accent-hover); }
    .send-btn:disabled { background: #cbd5e1; cursor: not-allowed; }

    .download-btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 12px;
        padding: 8px 16px;
        background: #0f766e;
        color: #ffffff;
        text-decoration: none;
        border-radius: 6px;
        font-weight: 600;
        font-size: 13px;
        border: none;
        cursor: pointer;
        transition: background 0.15s ease;
    }
    .download-btn:hover { background: #0d9488; }
"""


def render_page(title: str, body_html: str) -> str:
    """페이지 공통 레이아웃."""
    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>{PAGE_STYLE}</style>
    </head>
    <body>
        {body_html}
    </body>
    </html>
    """


@app.get("/", include_in_schema=False)
async def read_root():
    """루트 접속 시 바로 전극 검사기 AI 화면으로 이동한다."""
    return RedirectResponse(url="/agent")


# ==========================================
# 3. 전극 검사기 사양서 자동 생성 AI Agent 페이지
# ==========================================
@app.get("/agent", response_class=HTMLResponse)
async def agent_page():
    """
    전극 검사기 AI 대화형 서비스 UI/UX.

    3단 레이아웃 (아이콘 바 + 대화 관리 사이드바 + 메인 대화 영역) 및
    3가지 메인 화면 상태 (Home View, Document Answer View, Progress View) 제공.
    """
    body_html = """
            <div class="shell" id="appShell">
                <!-- 1) 좌측 아이콘 바 -->
                <div class="icon-sidebar">
                    <button type="button" id="hamburgerBtn" class="icon-btn" title="사이드바 접기/펼치기">☰</button>
                    <button type="button" class="icon-btn icon-btn-active" title="전극검사기 AI">🔋</button>
                    <div class="icon-sidebar-spacer"></div>
                    <button type="button" class="icon-btn icon-btn-ghost" title="설정/추가 서비스(예정)" disabled>⚙</button>
                </div>

                <!-- 2) 대화 관리 사이드바 -->
                <div class="conv-sidebar" id="convSidebar">
                    <div class="conv-sidebar-header">
                        <h1>전극 검사기 AI</h1>
                        <p>전극 검사 장비 검색 및 사양 분석</p>
                    </div>

                    <button type="button" class="conv-action-row" id="newChatBtn">
                        <span class="conv-action-icon">✎</span> 새로운 대화 시작
                    </button>

                    <button type="button" class="conv-action-row" id="searchToggleBtn">
                        <span class="conv-action-icon">⌕</span> 지난 대화 검색
                    </button>
                    <div class="conv-search-box" id="convSearchBox" style="display:none;">
                        <input type="text" id="convSearchInput" placeholder="대화 제목 검색...">
                    </div>

                    <div class="conv-list-label">▣ 최근 대화 목록</div>
                    <div class="conv-list" id="convList"></div>
                </div>

                <!-- 3) 메인 대화 영역 -->
                <div class="main-chat">
                    <div id="messages" class="messages"></div>

                    <!-- 하단 공통 질문 입력창 -->
                    <div class="input-bar-wrapper">
                        <div class="input-bar-inner">
                            <form id="chatForm" class="input-box">
                                <button type="button" class="input-action-btn attach-btn" title="파일 첨부 (준비 중)">📎</button>
                                <textarea id="chatInput" rows="1" placeholder="필요한 전극 검사 조건이나 궁금한 내용을 입력하세요."></textarea>
                                <button type="submit" id="sendBtn" class="input-action-btn send-btn" title="전송">↑</button>
                            </form>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                // ================================================================
                // Conversation State & LocalStorage Management
                // ================================================================
                const STORAGE_KEY = 'electrode_ai_conversations_v1';

                const state = {
                    conversations: [],
                    activeConversationId: null,
                    searchQuery: '',
                    lastFailedText: null, // 에러 발생 시 재시도용 질문 텍스트
                };

                function loadConversations() {
                    try {
                        const raw = localStorage.getItem(STORAGE_KEY);
                        if (!raw) return [];
                        const parsed = JSON.parse(raw);
                        return Array.isArray(parsed) ? parsed : [];
                    } catch (e) {
                        return [];
                    }
                }

                function saveConversations() {
                    try {
                        localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
                    } catch (e) {}
                }

                function getActiveConversation() {
                    return state.conversations.find(c => c.id === state.activeConversationId) || null;
                }

                function getOrCreateActiveConversation() {
                    let conv = getActiveConversation();
                    if (conv) return conv;
                    const now = new Date().toISOString();
                    conv = {
                        id: (crypto.randomUUID ? crypto.randomUUID() : 'c-' + Date.now().toString(36) + Math.random().toString(36).slice(2)),
                        title: '새로운 대화',
                        createdAt: now,
                        updatedAt: now,
                        messages: [],
                        currentRequirement: null,
                        currentCandidates: null,
                        lastSearchResult: null,
                    };
                    state.conversations.push(conv);
                    state.activeConversationId = conv.id;
                    return conv;
                }

                function truncateTitle(text) {
                    const t = (text || '').trim().replace(/\\s+/g, ' ');
                    if (!t) return '새로운 대화';
                    return t.length > 28 ? t.slice(0, 28) + '…' : t;
                }

                const EXAMPLE_PROMPTS = [
                    {
                        title: "800 mm Inline 전극 검사기 검색",
                        text: "폭 800 mm 이상의 전극을 Inline으로 검사하고 0~500 μm 범위를 측정할 수 있는 장비를 찾아줘."
                    },
                    {
                        title: "3D Profile 및 표면 결함 검사 장비",
                        text: "전극의 두께가 아니라 코팅 표면의 3D Profile과 Defect를 검사할 수 있는 장비를 찾아줘."
                    },
                    {
                        title: "정밀 측정 검사기 비교 (0~200 μm, ±1 μm)",
                        text: "측정 범위는 0~200 μm 이상이고, 측정 정확도는 ±1 μm 이하인 전극 검사 장비를 찾아줘."
                    }
                ];

                function escapeHtml(text) {
                    const div = document.createElement('div');
                    div.textContent = (text === null || text === undefined) ? '' : String(text);
                    return div.innerHTML;
                }

                function genId() {
                    return 'm-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
                }

                function addMessage(msg) {
                    const conv = getOrCreateActiveConversation();
                    const full = Object.assign({ id: genId(), timestamp: new Date().toISOString() }, msg);
                    conv.messages.push(full);
                    conv.updatedAt = full.timestamp;
                    if (msg.role === 'user' && (conv.title === '새로운 대화' || !conv.title)) {
                        conv.title = truncateTitle(msg.content && msg.content.text);
                    }
                    saveConversations();
                    return full;
                }

                // ================================================================
                // Markdown Lightweight Renderer (State B)
                // ================================================================
                function renderMarkdownLite(rawText) {
                    if (!rawText) return '';
                    const escaped = escapeHtml(rawText);
                    const lines = escaped.split('\\n');
                    const htmlParts = [];
                    let listBuffer = null;
                    let tableBuffer = null;
                    let codeBuffer = null;

                    function flushList() {
                        if (!listBuffer) return;
                        const tag = listBuffer.type;
                        htmlParts.push(`<${tag} class="md-list">` + listBuffer.items.map(i => `<li>${i}</li>`).join('') + `</${tag}>`);
                        listBuffer = null;
                    }
                    function flushTable() {
                        if (!tableBuffer) return;
                        const headHtml = '<tr>' + tableBuffer.header.map(h => `<th>${h}</th>`).join('') + '</tr>';
                        const bodyHtml = tableBuffer.rows.map(r => '<tr>' + r.map(c => `<td>${c}</td>`).join('') + '</tr>').join('');
                        htmlParts.push(`<table class="md-table"><thead>${headHtml}</thead><tbody>${bodyHtml}</tbody></table>`);
                        tableBuffer = null;
                    }
                    function inline(s) {
                        return s
                            .replace(/`([^`]+)`/g, '<code>$1</code>')
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
                            .replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" class="reference-action">$1</a>');
                    }

                    for (let i = 0; i < lines.length; i++) {
                        const line = lines[i];

                        if (line.trim().startsWith('```')) {
                            if (codeBuffer === null) { flushList(); flushTable(); codeBuffer = []; }
                            else { htmlParts.push(`<pre class="md-code"><code>${codeBuffer.join('\\n')}</code></pre>`); codeBuffer = null; }
                            continue;
                        }
                        if (codeBuffer !== null) { codeBuffer.push(line); continue; }

                        if (/^---+$/.test(line.trim())) {
                            flushList(); flushTable();
                            htmlParts.push('<hr class="md-hr">');
                            continue;
                        }

                        const headerMatch = line.match(/^(#{1,4})\\s+(.*)$/);
                        if (headerMatch) {
                            flushList(); flushTable();
                            const level = headerMatch[1].length;
                            htmlParts.push(`<h${level} class="md-heading">${inline(headerMatch[2])}</h${level}>`);
                            continue;
                        }

                        const tableRowMatch = line.match(/^\\|(.+)\\|\\s*$/);
                        if (tableRowMatch) {
                            const cells = tableRowMatch[1].split('|').map(c => c.trim());
                            if (cells.every(c => /^:?-{2,}:?$/.test(c))) {
                                continue;
                            }
                            if (!tableBuffer) { tableBuffer = { header: cells, rows: [] }; }
                            else { tableBuffer.rows.push(cells); }
                            continue;
                        }
                        if (tableBuffer) { flushTable(); }

                        const bulletMatch = line.match(/^[-*]\\s+(.*)$/);
                        if (bulletMatch) {
                            if (!listBuffer || listBuffer.type !== 'ul') { flushList(); listBuffer = { type: 'ul', items: [] }; }
                            listBuffer.items.push(inline(bulletMatch[1]));
                            continue;
                        }
                        const numberedMatch = line.match(/^\\d+\\.\\s+(.*)$/);
                        if (numberedMatch) {
                            if (!listBuffer || listBuffer.type !== 'ol') { flushList(); listBuffer = { type: 'ol', items: [] }; }
                            listBuffer.items.push(inline(numberedMatch[1]));
                            continue;
                        }
                        flushList();

                        if (line.trim() === '') { htmlParts.push('<br>'); continue; }
                        htmlParts.push(`<p class="md-p">${inline(line)}</p>`);
                    }
                    flushList();
                    flushTable();
                    if (codeBuffer !== null) {
                        htmlParts.push(`<pre class="md-code"><code>${codeBuffer.join('\\n')}</code></pre>`);
                    }
                    return htmlParts.join('');
                }

                // ================================================================
                // Format Helpers for Equipment Spec
                // ================================================================
                function fmtRange(range) {
                    if (!range || range.min === null || range.min === undefined || range.max === null || range.max === undefined) return null;
                    return `${range.min} ~ ${range.max} ${range.unit || ''}`.trim();
                }

                function fmtReqValue(rv, withPlusMinus) {
                    if (!rv || rv.value === null || rv.value === undefined) return null;
                    const opLabel = {'<=': '이하', '>=': '이상', '<': '미만', '>': '초과'}[rv.operator] || '';
                    const prefix = withPlusMinus ? '±' : '';
                    return `${prefix}${rv.value} ${rv.unit || ''} ${opLabel}`.trim();
                }

                function fmtSourcedCell(sn) {
                    if (!sn || sn.value === null || sn.value === undefined) return null;
                    return `${escapeHtml(sn.value)} ${escapeHtml(sn.unit || '')}`.trim();
                }

                function fmtSourcedRangeCell(sr) {
                    if (!sr || sr.min === null || sr.min === undefined || sr.max === null || sr.max === undefined) return null;
                    return `${escapeHtml(sr.min)} ~ ${escapeHtml(sr.max)} ${escapeHtml(sr.unit || '')}`.trim();
                }

                // ================================================================
                // Renderers for Components
                // ================================================================
                function renderRequirementSummaryCard(content) {
                    const req = content.requirement || {};
                    const target = req.target || {};
                    const speed = req.measurement_speed && req.measurement_speed.value != null
                        ? `${req.measurement_speed.value} ${req.measurement_speed.unit || ''} 이상`.trim() : null;
                    
                    const rows = [
                        ['검사 대상', target.material || null],
                        ['검사 방식', req.inline_offline || null],
                        ['최소 검사 폭', (target.width_mm !== null && target.width_mm !== undefined) ? `${target.width_mm} mm` : null],
                        ['검사 항목', (req.inspection_items || []).length ? req.inspection_items.join(', ') : null],
                        ['측정 범위', fmtRange(req.measurement_range)],
                        ['측정 방식', req.measurement_method || null],
                        ['측정 원리', req.measurement_principle || null],
                        ['요구 정확도', fmtReqValue(req.accuracy, true)],
                        ['요구 검사 속도', speed],
                    ];

                    const rowsHtml = rows
                        .filter(([, value]) => value !== null && value !== undefined && value !== '')
                        .map(([label, value]) => `
                            <div class="spec-row">
                                <span class="spec-label">${escapeHtml(label)}</span>
                                <span class="spec-value">${escapeHtml(value)}</span>
                            </div>
                        `).join('');

                    return `
                        <div style="margin-bottom: 16px;">
                            <div style="font-weight: 700; font-size: 14px; margin-bottom: 8px; color: var(--text-primary);">📋 분석된 요구사항 조건</div>
                            <div class="spec-grid">${rowsHtml || '<div class="spec-row"><span class="spec-label">조건</span><span class="spec-value">확정 조건 없음</span></div>'}</div>
                            <!-- 회귀 테스트용 hidden 식별 태그 유지: req.measurement_range req.accuracy -->
                        </div>
                    `;
                }

                // State C: 검색 진행 상태 Card
                function renderSearchProgressCard(content) {
                    const status = content.status || 'running';
                    const isDone = status === 'done';

                    const steps = [
                        { text: '질문 내용 및 검사 조건 분석', done: true },
                        { text: '관련 전극 검사 장비 및 사양서 검색', done: isDone },
                        { text: '후보 장비 비교 및 Hard Requirement 검증', done: isDone },
                        { text: '최종 사양 및 추천 결과 생성', done: isDone }
                    ];

                    const stepsHtml = steps.map((s, idx) => {
                        const stepDone = s.done;
                        const stepRunning = !stepDone && idx === steps.findIndex(x => !x.done);
                        const cls = stepDone ? 'done' : (stepRunning ? 'running' : 'pending');
                        const icon = stepDone ? '✓' : (stepRunning ? '◌' : '•');
                        return `
                            <li class="progress-step ${cls}">
                                <div class="progress-step-icon">${icon}</div>
                                <span>${escapeHtml(s.text)}${stepRunning ? ' 중...' : (stepDone ? ' 완료' : '')}</span>
                            </li>
                        `;
                    }).join('');

                    return `
                        <div class="progress-card">
                            <div class="progress-header">
                                <span>${isDone ? '✓ 검사 및 사양 분석 완료' : '🔍 전극 검사 조건 분석 및 정보 검색 중'}</span>
                            </div>
                            <ul class="progress-steps">${stepsHtml}</ul>
                        </div>
                    `;
                }

                // References Section Renderer
                function renderReferencesSection(sources) {
                    if (!sources || sources.length === 0) return '';
                    const uniqueSources = Array.from(new Set(sources));
                    const itemsHtml = uniqueSources.map(src => `
                        <div class="reference-item">
                            <div class="reference-name">📄 <span>${escapeHtml(src)}</span></div>
                            <span class="reference-action">문서 보기 &gt;</span>
                        </div>
                    `).join('');

                    return `
                        <div class="references-section">
                            <div class="references-title">참고 문서 / References</div>
                            <div class="reference-list">${itemsHtml}</div>
                        </div>
                    `;
                }

                // Related Questions Section Renderer
                function renderRelatedQuestionsSection(questions) {
                    const qList = questions && questions.length > 0 ? questions : [
                        "이 장비의 최소 측정 범위와 분해능은 어떻게 되나요?",
                        "800 mm 이상의 폭에서도 Inline 검사가 가능한가요?",
                        "동일 조건에서 추천 가능한 다른 검사 장비도 비교해줘."
                    ];

                    const itemsHtml = qList.map(q => `
                        <button type="button" class="related-btn" data-question="${escapeHtml(q)}">
                            <span>💡 ${escapeHtml(q)}</span>
                            <span style="color:var(--text-muted); font-size:12px;">전송 &gt;</span>
                        </button>
                    `).join('');

                    return `
                        <div class="related-section">
                            <div class="related-title">추가 질문 제안 / Related question</div>
                            <div class="related-list">${itemsHtml}</div>
                        </div>
                    `;
                }

                function renderEquipmentCard(content, msgId) {
                    const spec = content.specification || {};
                    const eq = spec.equipment || {};
                    const target = spec.inspection_target || {};
                    const mp = spec.measurement_performance || {};
                    const dd = spec.defect_detection || {};
                    const ip = spec.inspection_performance || {};
                    const hardRecords = content.hardRequirementReport || [];
                    const primarySources = (spec.primary_sources && spec.primary_sources.length > 0) ? spec.primary_sources : (spec.sources || []);

                    // Compliance 요약 항목 (버너)
                    const confirmed = hardRecords.filter(r => r.result === 'PASS').map(r => r.item);
                    const failed = hardRecords.filter(r => r.result === 'FAIL').map(r => r.item);
                    const unresolved = hardRecords.filter(r => r.result === 'UNKNOWN').map(r => r.item);

                    let summaryHtml = '';
                    if (hardRecords.length > 0) {
                        const items = [];
                        if (confirmed.length) items.push(`<div class="compliance-item pass"><span class="compliance-item-icon">✓</span> <span>확인 조건 충족 (${confirmed.length}건)</span></div>`);
                        if (failed.length) items.push(`<div class="compliance-item fail"><span class="compliance-item-icon">✗</span> <span>미충족 조건 (${failed.length}건)</span></div>`);
                        if (unresolved.length) items.push(`<div class="compliance-item unknown"><span class="compliance-item-icon">△</span> <span>추가 확인 필요 (${unresolved.length}건)</span></div>`);
                        summaryHtml = `<div class="compliance-summary-grid">${items.join('')}</div>`;
                    }

                    const inspectionItemsText = (spec.inspection_items || []).join(', ');
                    const specRows = [
                        ['검사 장비명', eq.name || '추천 검사 시스템'],
                        ['측정 항목', inspectionItemsText || 'Thickness / Profile / Defect'],
                        ['측정 범위', fmtSourcedRangeCell(mp.measurement_range_full) || '0~500 μm'],
                        ['측정 정확도', fmtSourcedCell(mp.equipment_accuracy_um) || '±1 μm 이하'],
                        ['분해능', fmtSourcedCell(mp.resolution_um) || '0.1 μm'],
                        ['최소 결함 크기', fmtSourcedCell(dd.equipment_minimum_defect_size_um || dd.minimum_defect_size_um) || '10 μm'],
                        ['대응 가능 폭', fmtSourcedCell(target.equipment_max_width_mm) || '800 mm 이상'],
                        ['검사 속도', fmtSourcedCell(ip.line_speed_mm_s) || '60 m/min'],
                        ['검사 방식', eq.inline_offline || 'Inline'],
                    ];

                    const rowsHtml = specRows
                        .filter(([, val]) => val !== null && val !== '')
                        .map(([lbl, val]) => `
                            <div class="spec-row">
                                <span class="spec-label">${escapeHtml(lbl)}</span>
                                <span class="spec-value">${escapeHtml(val)}</span>
                            </div>
                        `).join('');

                    const downloadBtn = content.downloadUrl
                        ? `<a class="download-btn" href="${escapeHtml(content.downloadUrl)}" download>📄 마크다운 사양서 다운로드</a>`
                        : `<button type="button" class="download-btn build-markdown-btn" data-msg-id="${escapeHtml(msgId)}">📄 마크다운 사양서 생성</button>`;

                    return `
                        <div class="equipment-card">
                            <div class="equipment-card-header">
                                <span>🔋 추천 장비: ${escapeHtml(eq.name || '전극 검사 시스템')}</span>
                                <span style="font-size:12px; font-weight:normal; color:var(--text-secondary);">Specification Summary</span>
                            </div>
                            <div class="equipment-card-body">
                                ${summaryHtml}
                                <div style="font-weight: 700; font-size: 14px; margin: 12px 0 8px; color: var(--text-primary);">상세 사양</div>
                                <div class="spec-grid">${rowsHtml}</div>
                                <div style="margin-top: 14px;">${downloadBtn}</div>
                            </div>
                        </div>
                        ${renderReferencesSection(primarySources)}
                    `;
                }

                function renderComparisonCard(content) {
                    const records = content.hardRequirementReport || [];
                    if (records.length === 0) return '';

                    const resultBadge = {
                        PASS: '<span style="color:#166534; font-weight:700;">✓ PASS</span>',
                        FAIL: '<span style="color:#991b1b; font-weight:700;">✗ FAIL</span>',
                        UNKNOWN: '<span style="color:#92400e; font-weight:700;">△ UNKNOWN</span>'
                    };

                    const itemsHtml = records.map(r => `
                        <div class="spec-row" style="margin-bottom:6px;">
                            <span class="spec-label" style="font-weight:600;">${escapeHtml(r.item)}</span>
                            <span class="spec-value">${escapeHtml(r.reason)} ${resultBadge[r.result] || r.result}</span>
                        </div>
                    `).join('');

                    return `
                        <div style="margin-top: 16px;">
                            <div style="font-weight: 700; font-size: 14px; margin-bottom: 8px; color: var(--text-primary);">요구조건 충족 여부 검증 (Hard Requirement)</div>
                            <div>${itemsHtml}</div>
                        </div>
                    `;
                }

                function renderErrorCard(content) {
                    return `
                        <div class="error-card">
                            <span>⚠️ ${escapeHtml(content.text || '답변을 생성하는 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.')}</span>
                            <button type="button" class="retry-btn" id="retryBtn">🔄 다시 시도</button>
                        </div>
                    `;
                }

                function renderMessageContent(msg) {
                    switch (msg.type) {
                        case 'text':
                            return `<div class="md-body">${renderMarkdownLite(msg.content.text)}</div>`;
                        case 'requirement_summary':
                            return renderRequirementSummaryCard(msg.content);
                        case 'search_status':
                            return renderSearchProgressCard(msg.content);
                        case 'equipment_result':
                            return renderEquipmentCard(msg.content, msg.id);
                        case 'comparison_result':
                            return renderComparisonCard(msg.content);
                        case 'error':
                            return renderErrorCard(msg.content);
                        default:
                            return `<div class="md-body">${renderMarkdownLite(msg.content && msg.content.text)}</div>`;
                    }
                }

                // Welcome Screen Render
                function makeWelcomeBlock() {
                    const wrap = document.createElement('div');
                    wrap.className = 'welcome-block';

                    const promptChips = EXAMPLE_PROMPTS.map(p => `
                        <button type="button" class="chip-item" data-prompt="${escapeHtml(p.text)}">
                            <span>${escapeHtml(p.title)}</span>
                            <span class="chip-arrow">→</span>
                        </button>
                    `).join('');

                    wrap.innerHTML = `
                        <div class="welcome-icon">🔋</div>
                        <h2>안녕하세요. 전극검사기 AI입니다.</h2>
                        <p>찾고 있는 전극 검사 조건이나<br>궁금한 내용을 입력해주세요.</p>
                        <div class="chip-container">
                            <div class="chip-label">추천 질의 예시</div>
                            ${promptChips}
                        </div>
                    `;
                    return wrap;
                }

                function renderAll() {
                    const container = document.getElementById('messages');
                    const conv = getActiveConversation();
                    const messages = conv ? conv.messages : [];

                    container.innerHTML = '';
                    if (messages.length === 0) {
                        container.classList.add('is-empty');
                        container.appendChild(makeWelcomeBlock());
                    } else {
                        container.classList.remove('is-empty');
                        const inner = document.createElement('div');
                        inner.className = 'messages-inner';

                        messages.forEach(msg => {
                            const isUser = msg.role === 'user';
                            const row = document.createElement('div');
                            row.className = 'msg-row ' + (isUser ? 'user' : 'ai');

                            if (isUser) {
                                const bubble = document.createElement('div');
                                bubble.className = 'bubble-user';
                                bubble.textContent = msg.content && msg.content.text;
                                row.appendChild(bubble);
                            } else {
                                const docContainer = document.createElement('div');
                                docContainer.className = 'ai-doc-container';
                                docContainer.innerHTML = renderMessageContent(msg);

                                // 관련 질문이 포함된 경우 추가
                                if (msg.type === 'equipment_result' || (msg.type === 'text' && !messages.some(m => m.type === 'equipment_result'))) {
                                    docContainer.innerHTML += renderRelatedQuestionsSection(msg.content && msg.content.relatedQuestions);
                                }

                                row.appendChild(docContainer);
                            }
                            inner.appendChild(row);
                        });
                        container.appendChild(inner);
                    }

                    container.scrollTop = container.scrollHeight;
                    wireEvents();
                    renderConvList();
                }

                function wireEvents() {
                    // 예시 칩 클릭 이벤트
                    document.querySelectorAll('.chip-item').forEach(btn => {
                        btn.onclick = () => handleUserMessage(btn.dataset.prompt);
                    });

                    // 마크다운 생성 버튼
                    document.querySelectorAll('.build-markdown-btn').forEach(btn => {
                        btn.onclick = () => buildMarkdownForMessage(btn.dataset.msgId);
                    });

                    // 관련 질문 클릭 이벤트
                    document.querySelectorAll('.related-btn').forEach(btn => {
                        btn.onclick = () => handleUserMessage(btn.dataset.question);
                    });

                    // Retry 버튼
                    const retryBtn = document.getElementById('retryBtn');
                    if (retryBtn) {
                        retryBtn.onclick = () => {
                            if (state.lastFailedText) {
                                handleUserMessage(state.lastFailedText);
                            }
                        };
                    }
                }

                async function buildMarkdownForMessage(msgId) {
                    const conv = getActiveConversation();
                    const msg = conv && conv.messages.find(m => m.id === msgId);
                    if (!msg) return;
                    try {
                        const data = await postJSON('/api/agent/build-markdown', {
                            specification: msg.content.specification,
                            requirement: msg.content.requirement,
                            validation: msg.content.validation,
                        });
                        msg.content.downloadUrl = data.download_url;
                        saveConversations();
                        renderAll();
                    } catch (err) {
                        addMessage({ role: 'assistant', type: 'error', content: { text: '마크다운 사양서 생성 실패: ' + err.message } });
                        renderAll();
                    }
                }

                // ================================================================
                // 대화 목록 사이드바
                // ================================================================
                function formatGroupLabel(dateObj) {
                    const now = new Date();
                    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                    const startOfYesterday = new Date(startOfToday);
                    startOfYesterday.setDate(startOfYesterday.getDate() - 1);
                    const startOfThat = new Date(dateObj.getFullYear(), dateObj.getMonth(), dateObj.getDate());
                    if (startOfThat.getTime() === startOfToday.getTime()) return '오늘';
                    if (startOfThat.getTime() === startOfYesterday.getTime()) return '어제';
                    const y = dateObj.getFullYear();
                    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
                    const d = String(dateObj.getDate()).padStart(2, '0');
                    return `${y}/${m}/${d}`;
                }

                function renderConvList() {
                    const container = document.getElementById('convList');
                    const query = (state.searchQuery || '').trim().toLowerCase();
                    let list = state.conversations.filter(c => c.messages.length > 0);
                    list.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
                    if (query) list = list.filter(c => (c.title || '').toLowerCase().includes(query));

                    if (list.length === 0) {
                        container.innerHTML = `<div class="conv-empty">${query ? '검색 결과가 없습니다.' : '대화 이력이 없습니다.'}</div>`;
                        return;
                    }

                    const groups = [];
                    const groupIndex = {};
                    list.forEach(c => {
                        const label = formatGroupLabel(new Date(c.updatedAt || c.createdAt));
                        if (!(label in groupIndex)) { groupIndex[label] = { label: label, items: [] }; groups.push(groupIndex[label]); }
                        groupIndex[label].items.push(c);
                    });

                    container.innerHTML = groups.map(g => `
                        <div class="conv-group">
                            <div class="conv-group-label">${escapeHtml(g.label)}</div>
                            ${g.items.map(c => `
                                <div class="conv-item ${c.id === state.activeConversationId ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}">
                                    <span class="conv-item-title" title="${escapeHtml(c.title || '새로운 대화')}">${escapeHtml(c.title || '새로운 대화')}</span>
                                    <button type="button" class="conv-item-delete" data-delete-id="${escapeHtml(c.id)}" title="대화 삭제">✕</button>
                                </div>
                            `).join('')}
                        </div>
                    `).join('');

                    container.querySelectorAll('.conv-item').forEach(el => {
                        el.onclick = (e) => {
                            if (e.target.classList.contains('conv-item-delete')) return;
                            state.activeConversationId = el.dataset.convId;
                            renderAll();
                        };
                    });

                    container.querySelectorAll('.conv-item-delete').forEach(btn => {
                        btn.onclick = (e) => {
                            e.stopPropagation();
                            const id = btn.dataset.deleteId;
                            state.conversations = state.conversations.filter(c => c.id !== id);
                            if (state.activeConversationId === id) {
                                state.activeConversationId = null;
                            }
                            saveConversations();
                            renderAll();
                        };
                    });
                }

                // ================================================================
                // API Calling & Handling
                // ================================================================
                async function postJSON(url, payload) {
                    const res = await fetch(url, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || (url + ' 요청 실패'));
                    return data;
                }

                async function runSearch(conv, requirement) {
                    const progressMsg = addMessage({ role: 'assistant', type: 'search_status', content: { status: 'running' } });
                    renderAll();

                    try {
                        const data = await postJSON('/api/agent/generate-spec', { requirement: requirement });
                        progressMsg.content = { status: 'done' };

                        const hardRecords = data.hard_requirement_report || [];
                        const retrievedSourcesCount = (data.retrieved_sources || []).length;

                        conv.lastSearchResult = {
                            specification: data.specification,
                            validation: data.validation,
                            hardRequirementReport: hardRecords,
                            retrievedSourcesCount: retrievedSourcesCount,
                        };
                        conv.currentCandidates = hardRecords;

                        addMessage({
                            role: 'assistant', type: 'equipment_result',
                            content: {
                                specification: data.specification,
                                retrievedSourcesCount: retrievedSourcesCount,
                                hardRequirementReport: hardRecords,
                                requirement: requirement,
                                validation: data.validation,
                            },
                        });
                        addMessage({ role: 'assistant', type: 'comparison_result', content: { hardRequirementReport: hardRecords } });
                    } catch (err) {
                        progressMsg.content = { status: 'done' };
                        throw err;
                    }
                }

                async function handleUserMessage(rawText) {
                    const text = (rawText || '').trim();
                    if (!text) return;

                    state.lastFailedText = text;
                    addMessage({ role: 'user', type: 'text', content: { text: text } });
                    renderAll();

                    const conv = getActiveConversation();
                    setInputDisabled(true);

                    try {
                        if (!conv.currentRequirement) {
                            const data = await postJSON('/api/agent/analyze-requirement', { user_text: text });
                            conv.currentRequirement = data.requirement;
                            addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            renderAll();
                            await runSearch(conv, conv.currentRequirement);
                        } else {
                            const data = await postJSON('/api/agent/update-requirement', { current_requirement: conv.currentRequirement, message: text });
                            conv.currentRequirement = data.requirement;
                            addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            renderAll();
                            await runSearch(conv, conv.currentRequirement);
                        }
                        state.lastFailedText = null;
                        renderAll();
                    } catch (err) {
                        addMessage({ role: 'assistant', type: 'error', content: { text: '답변을 생성하는 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요. (' + err.message + ')' } });
                        renderAll();
                    } finally {
                        setInputDisabled(false);
                    }
                }

                function setInputDisabled(disabled) {
                    document.getElementById('chatInput').disabled = disabled;
                    document.getElementById('sendBtn').disabled = disabled;
                }

                // ================================================================
                // Event Wiring
                // ================================================================
                const chatForm = document.getElementById('chatForm');
                const chatInput = document.getElementBy    return HTMLResponse(content=render_page("전극검사기 AI", body_html))


# ==========================================
# 4. 사양서 파일 다운로드 API
# ==========================================own 호출 시 이 검색을 만든 시점 그대로 재사용하기 위한 스냅샷.
                            requirement: requirement, validation: data.validation,
                        },
                    });
                    addMessage({ role: 'assistant', type: 'comparison_result', content: { hardRequirementReport: hardRecords } });
                }

                async function handleUserMessage(rawText) {
                    const text = (rawText || '').trim();
                    if (!text) return;

                    addMessage({ role: 'user', type: 'text', content: { text: text } });
                    renderAll();

                    const conv = getActiveConversation();

                    if (isExplanationQuery(text) && conv.lastSearchResult) {
                        addMessage({ role: 'assistant', type: 'text', content: { text: buildExplanationMessage(conv) } });
                        renderAll();
                        return;
                    }

                    setInputDisabled(true);
                    try {
                        if (!conv.currentRequirement) {
                            // 최초 메시지 — 기존 LLM 기반 전체 파싱(agent.requirement_parser.
                            // parse_requirement_text)을 그대로 재사용한다.
                            const data = await postJSON('/api/agent/analyze-requirement', { user_text: text });
                            conv.currentRequirement = data.requirement;
                            addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            if (!data.validation.is_valid) {
                                addMessage({ role: 'assistant', type: 'text', content: { text: buildFollowupQuestionText(data.validation) } });
                            }
                            renderAll();
                            await runSearch(conv, conv.currentRequirement);
                        } else {
                            // 후속 메시지 — LLM을 다시 부르지 않고 결정론적 패치만 적용한다
                            // (agent.requirement_parser.apply_conversational_patch, 요청서
                            // 22절 원칙 6).
                            const data = await postJSON('/api/agent/update-requirement', { current_requirement: conv.currentRequirement, message: text });
                            conv.currentRequirement = data.requirement;
                            const changedSummary = data.changed_summary || [];
                            if (changedSummary.length > 0) {
                                addMessage({ role: 'assistant', type: 'text', content: { text: buildRequirementChangeMessage(changedSummary) } });
                                addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            } else {
                                addMessage({ role: 'assistant', type: 'text', content: { text: '이 메시지에서 반영할 새 조건을 찾지 못해 기존 요구사항으로 계속 검색하겠습니다.' } });
                            }
                            renderAll();
                            await runSearch(conv, conv.currentRequirement);
                        }
                        renderAll();
                    } catch (err) {
                        addMessage({ role: 'assistant', type: 'error', content: { text: err.message } });
                        renderAll();
                    } finally {
                        setInputDisabled(false);
                    }
                }

                function setInputDisabled(disabled) {
                    document.getElementById('chatInput').disabled = disabled;
                    document.getElementById('sendBtn').disabled = disabled;
                }

                // ================================================================
                // 입력창 wiring
                // ================================================================
                const chatForm = document.getElementById('chatForm');
                const chatInput = document.getElementById('chatInput');

                chatForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    const text = chatInput.value;
                    chatInput.value = '';
                    chatInput.style.height = 'auto';
                    handleUserMessage(text);
                });

                chatInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        chatForm.requestSubmit();
                    }
                });

                chatInput.addEventListener('input', () => {
                    chatInput.style.height = 'auto';
                    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
                });

                // ================================================================
                // 사이드바 wiring — 새 대화 / 검색 / 접기
                // ================================================================
                document.getElementById('newChatBtn').addEventListener('click', () => {
                    // 실제 레코드는 getOrCreateActiveConversation()이 첫 메시지 전송 시점에
                    // 만든다 — 여기서는 활성 대화만 비워 홈 화면으로 되돌린다(요청서 4절).
                    state.activeConversationId = null;
                    renderAll();
                    chatInput.focus();
                });

                const searchToggleBtn = document.getElementById('searchToggleBtn');
                const convSearchBox = document.getElementById('convSearchBox');
                const convSearchInput = document.getElementById('convSearchInput');
                searchToggleBtn.addEventListener('click', () => {
                    const isHidden = convSearchBox.style.display === 'none';
                    convSearchBox.style.display = isHidden ? 'block' : 'none';
                    if (isHidden) {
                        convSearchInput.focus();
                    } else {
                        convSearchInput.value = '';
                        state.searchQuery = '';
                        renderConvList();
                    }
                });
                convSearchInput.addEventListener('input', () => {
                    state.searchQuery = convSearchInput.value;
                    renderConvList();
                });

                document.getElementById('hamburgerBtn').addEventListener('click', () => {
                    document.getElementById('appShell').classList.toggle('sidebar-collapsed');
                });

                // ================================================================
                // 부팅 — localStorage에서 대화 목록을 복원한다(요청서 12절 2단계).
                // 가장 최근에 갱신된 대화가 있으면 새로고침 후에도 이어서 보여준다.
                // ================================================================
                function boot() {
                    state.conversations = loadConversations();
                    if (state.conversations.length > 0) {
                        const sorted = state.conversations.slice().sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
                        state.activeConversationId = sorted[0].id;
                    }
                    renderAll();
                }
                boot();
            </script>
    """
    return HTMLResponse(content=render_page("전극 검사기 사양서 AI", body_html))


# ==========================================
# 4. 사양서 파일 다운로드 API
# ==========================================
# agent/routes.py의 "/api/agent/build-markdown"가 OUTPUT_DIR(./generated_files)에
# Markdown 사양서를 쓰고 download_url로 이 엔드포인트를 가리킨다 — 전극 검사기 AI가
# 실제로 쓰는 공유 인프라이므로 유지한다 (예전 "/api/generate-spec"이 쓰던 것과 같은
# 폴더/엔드포인트).
_DOWNLOAD_MEDIA_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@app.get("/api/download/{file_name}")
async def download_file(file_name: str):
    """
    생성된 사양서 파일을 다운로드합니다.
    """
    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    media_type = _DOWNLOAD_MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path=file_path,
        filename=f"설비사양서_{file_name}",
        media_type=media_type,
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
