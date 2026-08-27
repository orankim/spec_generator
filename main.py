import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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

app = FastAPI(title="전극 검사기 사양서 자동 생성 AI")
app.include_router(agent_router)

# Typography System(요청서): 서비스 기본 서체 Spoqa Han Sans Neo. 이 앱은 "폐쇄망
# 보안 정책"(위 HF_HUB_OFFLINE 설정 참고)으로 운영되는 사내 도구라 외부 CDN에 접속할
# 수 없는 네트워크 환경에서도 동작해야 한다 — 그래서 웹폰트를 외부 CDN 링크로
# 불러오지 않고, 파일 자체(static/fonts/spoqa-han-sans-neo/, SIL OFL 1.1 라이선스로
# 재배포가 허용된 오픈소스 폰트)를 이 저장소에 포함해 직접 서빙한다.
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
    /* Spoqa Han Sans Neo — 자체 호스팅(static/fonts/spoqa-han-sans-neo/, SIL OFL
       1.1 라이선스). 외부 CDN에 의존하면 폐쇄망(사내망) 배포 환경에서 폰트가 전혀
       로드되지 않아 시스템 기본 폰트로 조용히 대체돼 버리므로, 타이포그래피 스펙에
       필요한 3개 굵기(Regular 400 / Medium 500 / Bold 700)만 이 앱이 직접 서빙한다.
       woff2를 우선하고(최신 브라우저), woff를 폴백으로 둔다. */
    @font-face {
        font-family: "Spoqa Han Sans Neo";
        font-weight: 400;
        font-style: normal;
        font-display: swap;
        src: url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Regular.woff2") format("woff2"),
             url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Regular.woff") format("woff");
    }
    @font-face {
        font-family: "Spoqa Han Sans Neo";
        font-weight: 500;
        font-style: normal;
        font-display: swap;
        src: url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Medium.woff2") format("woff2"),
             url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Medium.woff") format("woff");
    }
    @font-face {
        font-family: "Spoqa Han Sans Neo";
        font-weight: 700;
        font-style: normal;
        font-display: swap;
        src: url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Bold.woff2") format("woff2"),
             url("/static/fonts/spoqa-han-sans-neo/SpoqaHanSansNeo-Bold.woff") format("woff");
    }
    :root {
        color-scheme: light;

        /* ===== Design Token: Color System ===== */
        --primary-600: #2D9BB2;
        --primary-500: #3EC2CF;
        --primary-100: #D9FCF4;
        --secondary-500: #554596;
        --grey-50: #F1F1F1;
        --grey-200: #EBEEED;
        --grey-300: #DDE0DF;
        --grey-900: #1F1F1F;

        /* ===== Design Token: Typography ===== */
        --font-family-base: "Spoqa Han Sans Neo", -apple-system, "Segoe UI", "맑은 고딕", sans-serif;

        --font-title-xl-size: 32px;  --font-title-xl-weight: 700;  /* 대표 타이틀 */
        --font-title-lg-size: 24px;  --font-title-lg-weight: 700;  /* 페이지 제목 */
        --font-heading-md-size: 18px; --font-heading-md-weight: 700; /* 섹션 헤더 */
        --font-heading-sm-size: 16px; --font-heading-sm-weight: 500; /* 보조 제목 */
        --font-body-md-size: 14px;   --font-body-md-weight: 400;   /* 본문 기본 */
        --font-body-sm-size: 13px;   --font-body-sm-weight: 400;   /* 본문 보조 */
        --font-label-size: 12px;     --font-label-weight: 500;     /* 라벨/캡션 */
        --font-support-size: 11px;   --font-support-weight: 400;   /* 보조 정보 */

        --line-height-title: 1.3;
        --line-height-heading: 1.4;
        --line-height-body: 1.6;
        --line-height-caption: 1.4;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; overflow: hidden; }
    html, body, button, input, textarea {
        font-family: var(--font-family-base);
    }
    body {
        font-size: var(--font-body-md-size);
        font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
        background: #ffffff;
        color: var(--grey-900);
    }

    /* ===== 3단 레이아웃: 아이콘 사이드바 + 대화 관리 사이드바 + 메인 대화 영역 ===== */
    .shell { display: flex; height: 100vh; width: 100%; }

    .icon-sidebar {
        width: 56px;
        flex-shrink: 0;
        background: var(--grey-200);
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 14px 0;
        gap: 16px;
    }
    .icon-btn {
        width: 36px;
        height: 36px;
        border: none;
        background: transparent;
        border-radius: 8px;
        font-size: 17px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--grey-900);
        opacity: .65;
    }
    .icon-btn:hover:not(:disabled) { background: rgba(0,0,0,.06); opacity: 1; }
    .icon-btn.icon-btn-active { background: transparent; color: var(--primary-600); opacity: 1; }
    .icon-btn.icon-btn-active:hover { background: rgba(45,155,178,.12); }
    .icon-btn.icon-btn-ghost { color: var(--grey-900); opacity: .3; cursor: default; }
    .icon-sidebar-spacer { flex: 1; }

    .conv-sidebar {
        width: 280px;
        flex-shrink: 0;
        background: var(--grey-50);
        border-right: 1px solid var(--grey-300);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: width .15s ease, opacity .15s ease;
    }
    .shell.sidebar-collapsed .conv-sidebar { width: 0; opacity: 0; border-right: none; }

    /* 좁은 화면(모바일)에서는 고정 280px 대화 사이드바 + 56px 아이콘 레일만으로
       336px가 소모돼, 375px 폭 기기에서는 본문(main-chat)에 39px밖에 남지 않아
       입력창/전송 버튼이 뷰포트 밖으로 밀려나는 문제가 있었다(요청서 13절 반응형
       테스트로 실측 확인). 640px 이하에서는 기본적으로 사이드바를 접어 본문 폭을
       확보하고, 기존 햄버거 토글(.shell.sidebar-collapsed를 서로 다른 화면 폭에서
       재사용)로 필요할 때만 펼쳐 보게 한다 — 별도 JS 변경 없이 이 media query
       안에서만 그 클래스의 의미를 "펼침"으로 뒤집는다.
    */
    @media (max-width: 640px) {
        .conv-sidebar { width: 0; opacity: 0; border-right: none; }
        .shell.sidebar-collapsed .conv-sidebar { width: 280px; opacity: 1; border-right: 1px solid var(--grey-300); }
    }

    .conv-sidebar-header { padding: 18px 18px 12px; border-bottom: 1px solid var(--grey-300); flex-shrink: 0; }
    .conv-sidebar-header h1 {
        font-size: var(--font-heading-sm-size); font-weight: var(--font-heading-sm-weight);
        line-height: var(--line-height-heading);
        margin: 0; color: var(--grey-900);
    }
    .conv-sidebar-header p {
        font-size: var(--font-body-sm-size); font-weight: var(--font-body-sm-weight);
        line-height: var(--line-height-caption);
        margin: 4px 0 0; color: var(--grey-900);
        /* 요청서 15절: axe-core가 실측한 명도 대비 부족(4.19:1, WCAG AA 기준 4.5:1
           미달)을 고치기 위해 opacity를 .6 -> .7로 올렸다(grey-50 배경 기준 5.74:1). */
        opacity: .7;
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
        font-size: var(--font-label-size);
        font-weight: var(--font-label-weight);
        line-height: var(--line-height-caption);
        color: var(--grey-900);
        cursor: pointer;
        flex-shrink: 0;
    }
    .conv-action-row:hover { background: rgba(0,0,0,.04); }
    .conv-action-icon { font-size: 14px; width: 16px; text-align: center; flex-shrink: 0; }

    .conv-search-box { padding: 0 18px 10px; flex-shrink: 0; }
    .conv-search-box input {
        width: 100%;
        border: 1px solid var(--grey-300);
        border-radius: 6px;
        padding: 7px 10px;
        font-size: var(--font-body-sm-size);
        font-family: inherit;
    }
    .conv-search-box input:focus { outline: none; border-color: var(--primary-600); }

    .conv-list-label {
        padding: 10px 18px 4px; font-size: var(--font-label-size); font-weight: var(--font-label-weight);
        color: var(--grey-900);
        /* 요청서 15절: axe-core 실측 2.72:1(WCAG AA 4.5:1 미달) 수정 — .45 -> .7. */
        opacity: .7;
        letter-spacing: .03em; flex-shrink: 0;
    }
    .conv-list { flex: 1; overflow-y: auto; padding-bottom: 10px; }
    .conv-group-label {
        padding: 10px 18px 4px; font-size: var(--font-support-size); font-weight: var(--font-support-weight);
        line-height: var(--line-height-caption);
        color: var(--grey-900);
        /* 요청서 15절: axe-core 실측 2.72:1(WCAG AA 4.5:1 미달) 수정 — .45 -> .7. */
        opacity: .7;
    }
    .conv-item {
        display: block;
        width: 100%;
        border: none;
        border-left: 3px solid transparent;
        background: transparent;
        text-align: left;
        padding: 8px 18px 8px 15px;
        font-size: var(--font-body-sm-size);
        font-weight: var(--font-body-sm-weight);
        color: var(--grey-900);
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .conv-item:hover { background: rgba(0,0,0,.04); }
    .conv-item.active { background: var(--primary-100); border-left-color: var(--primary-500); font-weight: 500; }
    /* 요청서 15절: axe-core 실측 2.72:1(WCAG AA 4.5:1 미달) 수정 — .45 -> .7. */
    .conv-empty { padding: 10px 18px; font-size: var(--font-label-size); color: var(--grey-900); opacity: .7; }

    .main-chat {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        background: #ffffff;
    }

    /* ===== Messages ===== */
    .messages {
        flex: 1;
        overflow-y: auto;
        padding: 24px max(24px, calc(50% - 460px));
        display: flex;
        flex-direction: column;
        gap: 14px;
    }
    .messages.is-empty { align-items: center; justify-content: center; }

    .welcome-block { text-align: center; max-width: 560px; margin: 0 auto; transform: translateY(-8%); }
    .welcome-icon { font-size: 30px; margin-bottom: 14px; }
    .welcome-block h2 {
        font-size: var(--font-title-xl-size); font-weight: var(--font-title-xl-weight);
        line-height: var(--line-height-title);
        margin: 0 0 10px; color: var(--grey-900);
    }
    .welcome-block p {
        font-size: var(--font-body-md-size); font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
        margin: 0; color: var(--grey-900);
    }
    .welcome-block .chip-row { justify-content: center; margin-top: 20px; }

    .msg-row { display: flex; }
    .msg-row.user { justify-content: flex-end; align-items: flex-start; gap: 8px; }
    .msg-row.ai { justify-content: flex-start; width: 100%; }
    .bubble {
        max-width: 82%;
        word-break: break-word;
    }
    /* 사용자 Avatar(문서 9절): Secondary-500 Purple */
    .user-avatar {
        flex-shrink: 0;
        width: 26px; height: 26px;
        border-radius: 50%;
        background: var(--secondary-500);
        color: #ffffff;
        display: flex; align-items: center; justify-content: center;
        font-size: var(--font-support-size);
        font-weight: 500;
    }
    .card, .card * { white-space: normal; }
    /* 사용자 질문 — 참고 디자인처럼 작고 절제된 Bubble(문서 10절 9항) */
    .bubble.user {
        background: var(--grey-200);
        color: var(--grey-900);
        border-radius: 14px;
        border-bottom-right-radius: 4px;
        padding: 10px 14px;
        font-size: var(--font-body-md-size);
        font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
    }
    /* AI 답변 — 챗봇 말풍선이 아니라 문서형 콘텐츠(문서 10절). 배경/테두리로
       "박스"처럼 감싸지 않고, 폭 전체를 문서처럼 흘려보낸다. */
    .bubble.ai {
        width: 100%;
        max-width: 100%;
        background: transparent;
        color: var(--grey-900);
        padding: 2px 0;
        font-size: var(--font-body-md-size);
        font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
    }
    .bubble.error {
        background: #fff5f5; border: 1px solid #feb2b2; color: #822727;
        border-radius: 10px; padding: 12px 14px;
        font-size: var(--font-body-md-size); line-height: var(--line-height-body);
    }

    /* ===== 경량 Markdown 렌더링(요청서 8절) — renderTextMessage/renderMarkdownLite =====
       Markdown Typography: H1(#)=24px/700, H2(##)=18px/700, H3(###)=16px/500 */
    .md-body .md-p {
        margin: 0 0 8px; white-space: pre-wrap;
        font-size: var(--font-body-md-size); font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
    }
    .md-body .md-p:last-child { margin-bottom: 0; }
    .md-body .md-heading { margin: 14px 0 6px; color: var(--grey-900); }
    .md-body .md-heading:first-child { margin-top: 0; }
    .md-body h3.md-heading { font-size: var(--font-title-lg-size); font-weight: 700; line-height: var(--line-height-title); }
    .md-body h4.md-heading { font-size: var(--font-heading-md-size); font-weight: 700; line-height: var(--line-height-heading); }
    .md-body h5.md-heading { font-size: var(--font-heading-sm-size); font-weight: 500; line-height: var(--line-height-heading); }
    .md-body ul.md-list, .md-body ol.md-list { margin: 4px 0 10px; padding-left: 20px; }
    .md-body li { margin: 2px 0; font-size: var(--font-body-md-size); line-height: var(--line-height-body); }
    .md-body code { background: var(--grey-200); padding: 1px 5px; border-radius: 4px; font-size: var(--font-body-sm-size); font-family: ui-monospace, monospace; }
    .md-body pre.md-code { background: var(--grey-900); color: var(--grey-50); padding: 10px 12px; border-radius: 8px; overflow-x: auto; font-size: var(--font-body-sm-size); margin: 6px 0; }
    .md-body pre.md-code code { background: transparent; padding: 0; color: inherit; }
    .md-body table.md-table { border-collapse: collapse; margin: 6px 0; font-size: var(--font-body-sm-size); width: 100%; }
    .md-body table.md-table th, .md-body table.md-table td { border: 1px solid var(--grey-300); padding: 5px 9px; text-align: left; }
    .md-body table.md-table th { background: var(--grey-50); font-weight: 700; }

    /* ===== typing indicator(요청서 11절) ===== */
    .typing-dots { display: inline-flex; gap: 3px; margin-left: 6px; vertical-align: middle; }
    .typing-dots span { width: 5px; height: 5px; border-radius: 50%; background: var(--grey-900); opacity: .35; animation: typing-blink 1.2s infinite ease-in-out; }
    .typing-dots span:nth-child(2) { animation-delay: .2s; }
    .typing-dots span:nth-child(3) { animation-delay: .4s; }
    @keyframes typing-blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }

    /* ===== 참고 문서 / References(문서 14절) ===== */
    .sources-block { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--grey-300); }
    .sources-title {
        font-size: var(--font-heading-md-size); font-weight: var(--font-heading-md-weight);
        line-height: var(--line-height-heading);
        color: var(--grey-900); margin-bottom: 8px;
    }
    .sources-list { display: flex; flex-direction: column; gap: 6px; }
    .source-row {
        display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
        font-size: var(--font-body-sm-size); font-weight: var(--font-body-sm-weight);
        color: var(--grey-900);
    }
    .source-row .source-meta { font-size: var(--font-support-size); font-weight: var(--font-support-weight); color: var(--grey-900); opacity: .5; }

    /* ===== 추가 질문 제안 / Related Questions ===== */
    .related-block { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--grey-300); }
    .related-title {
        font-size: var(--font-heading-md-size); font-weight: var(--font-heading-md-weight);
        line-height: var(--line-height-heading);
        color: var(--grey-900); margin-bottom: 8px;
    }
    .related-list { display: flex; flex-direction: column; gap: 4px; }
    .related-item {
        display: block; width: 100%; text-align: left;
        border: none; background: transparent; cursor: pointer;
        padding: 6px 8px; margin: 0 -8px; border-radius: 6px;
        font-size: var(--font-body-sm-size); font-weight: var(--font-body-sm-weight);
        line-height: var(--line-height-body);
        color: var(--grey-900);
    }
    .related-item:hover { background: var(--primary-100); }

    /* ===== Cards (used inside AI content) ===== */
    .card { background: #ffffff; border: 1px solid var(--grey-300); border-radius: 8px; overflow: hidden; }
    .bubble .card { margin-top: 4px; }
    .card + .card { margin-top: 10px; }
    .card-header {
        padding: 10px 14px;
        background: var(--grey-50);
        border-bottom: 1px solid var(--grey-300);
        font-size: var(--font-heading-sm-size);
        font-weight: var(--font-heading-sm-weight);
        line-height: var(--line-height-heading);
        color: var(--grey-900);
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .card-body { padding: 12px 14px; }
    .card-row {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 7px 0;
        border-bottom: 1px dashed var(--grey-300);
        font-size: var(--font-body-md-size);
        line-height: var(--line-height-body);
    }
    .card-row:last-child { border-bottom: none; }
    .card-row .label { color: var(--grey-900); opacity: .55; flex-shrink: 0; }
    .card-row .value {
        color: var(--grey-900);
        font-weight: 500;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .card-row .value.muted { color: var(--grey-900); opacity: .4; font-weight: 400; }

    /* ===== Status badges ===== */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: var(--font-support-size);
        font-weight: 700;
        letter-spacing: .02em;
        white-space: nowrap;
    }
    .badge-pass { background: var(--primary-100); color: #1c6e7d; border: 1px solid var(--primary-500); }
    .badge-fail { background: #fff5f5; color: #9b2c2c; border: 1px solid #feb2b2; }
    .badge-unknown { background: #fffaf0; color: #9c4221; border: 1px solid #fbd38d; }
    .badge-verified { background: var(--primary-100); color: var(--primary-600); border: 1px solid var(--primary-500); }
    .badge-inferred { background: #f4f2fa; color: var(--secondary-500); border: 1px solid #c9c0e6; }
    .badge-userdefined { background: var(--grey-200); color: var(--grey-900); border: 1px solid var(--grey-300); }
    .badge-unset { background: var(--grey-50); color: var(--grey-900); opacity: .5; border: 1px solid var(--grey-300); }

    .banner {
        padding: 9px 12px; border-radius: 6px; margin-bottom: 10px;
        font-size: var(--font-body-sm-size); font-weight: 500; line-height: var(--line-height-body);
    }
    .banner-pass { background: var(--primary-100); border: 1px solid var(--primary-500); color: #1c6e7d; }
    .banner-fail { background: #fff5f5; border: 1px solid #feb2b2; color: #822727; }
    .banner-unknown { background: #fffaf0; border: 1px solid #fbd38d; color: #7b341e; }

    /* ===== Hard requirement comparison list ===== */
    .hard-req-list { list-style: none; margin: 0; padding: 0; }
    .hard-req-list li {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 10px;
        padding: 8px 0;
        border-bottom: 1px dashed var(--grey-300);
        font-size: var(--font-body-md-size);
        line-height: var(--line-height-body);
    }
    .hard-req-list li:last-child { border-bottom: none; }
    .hard-req-list .item-name { color: var(--grey-900); font-weight: 500; flex-shrink: 0; }
    .hard-req-list .reason { color: var(--grey-900); opacity: .75; flex: 1; text-align: right; font-size: var(--font-body-sm-size); }

    /* ===== Ranking(추천 순위) vs Compliance(요구조건 충족) 요약 — EquipmentCard ===== */
    .confirm-block {
        font-size: var(--font-body-sm-size); line-height: var(--line-height-body);
        padding: 8px 10px; border-radius: 6px; margin-bottom: 8px;
    }
    .confirm-block strong { display: block; font-size: var(--font-label-size); font-weight: var(--font-label-weight); margin-bottom: 2px; }
    .confirm-pass { background: var(--primary-100); color: #1c6e7d; }
    .confirm-fail { background: #fff5f5; color: #9b2c2c; }
    .confirm-unknown { background: #fffaf0; color: #9c4221; }

    /* ===== Search progress ===== */
    .progress-list { list-style: none; margin: 0; padding: 0; }
    .progress-list li {
        padding: 4px 0; font-size: var(--font-body-sm-size); font-weight: var(--font-body-sm-weight);
        color: var(--grey-900); opacity: .7;
    }
    .progress-list li.done { opacity: 1; font-size: var(--font-label-size); font-weight: var(--font-label-weight); }
    .progress-list li.done::before { content: "✓ "; color: var(--primary-600); font-weight: 700; }
    .progress-list li.pending::before { content: "… "; color: var(--grey-900); opacity: .4; }

    /* ===== Source (VERIFIED evidence) ===== */
    details.source-detail { margin-top: 4px; font-size: var(--font-support-size); }
    details.source-detail summary { color: var(--primary-600); cursor: pointer; list-style: none; }
    details.source-detail summary::-webkit-details-marker { display: none; }
    details.source-detail summary::before { content: "📄 근거 보기"; }
    details.source-detail[open] summary::before { content: "📄 근거 숨기기"; }
    details.source-detail .source-body { color: var(--grey-900); opacity: .55; margin-top: 4px; padding-left: 4px; }

    /* ===== Quick Start Questions(문서 8절) — 홈 화면에서 자주 쓰는 질문 제안 ===== */
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; justify-content: center; }
    .chip {
        border: 1px solid transparent;
        background: var(--primary-100);
        color: var(--grey-900);
        border-radius: 10px;
        padding: 8px 14px;
        font-size: var(--font-body-sm-size);
        font-weight: var(--font-body-sm-weight);
        cursor: pointer;
    }
    .chip:hover { border-color: var(--primary-500); }

    /* ===== Input bar ===== */
    .input-bar {
        display: flex;
        gap: 10px;
        padding: 16px max(24px, calc(50% - 460px));
        border-top: 1px solid var(--grey-300);
        background: #ffffff;
        flex-shrink: 0;
    }
    .input-bar textarea {
        flex: 1;
        /* flex item의 기본 min-width는 auto(=콘텐츠 기준 intrinsic width)라, 좁은
           화면(예: 375px 모바일)에서는 textarea가 <textarea>의 기본 내재 너비보다
           줄어들지 못해 형제 요소인 전송 버튼을 뷰포트 밖으로 밀어내는 문제가
           있었다(요청서 13절: "전송 버튼이 사라지지 않는가" — Playwright로 실측
           결과 button의 x좌표가 뷰포트 폭을 넘어서는 것을 확인). 0으로 낮춰
           gap/padding이 남기는 공간만큼만 차지하게 한다.
        */
        min-width: 0;
        resize: none;
        border: 1px solid var(--grey-300);
        border-radius: 8px;
        padding: 10px 12px;
        font-size: var(--font-body-md-size);
        font-weight: var(--font-body-md-weight);
        line-height: var(--line-height-body);
        color: var(--grey-900);
        font-family: inherit;
        max-height: 140px;
    }
    .input-bar textarea::placeholder { font-size: var(--font-body-sm-size); color: var(--grey-900); opacity: .45; }
    .input-bar textarea:focus { outline: none; border-color: var(--primary-600); }
    .input-bar button {
        border: none;
        background: var(--primary-600);
        color: #ffffff;
        padding: 0 22px;
        border-radius: 8px;
        font-size: var(--font-body-md-size);
        font-weight: 700;
        cursor: pointer;
    }
    .input-bar button:hover:not(:disabled) { background: #257c8f; }
    .input-bar button:disabled { background: var(--grey-300); color: var(--grey-900); opacity: .5; cursor: not-allowed; }

    a.download-btn, button.download-btn {
        display: inline-block;
        margin-top: 8px;
        padding: 8px 16px;
        background: var(--primary-600);
        color: #ffffff;
        text-decoration: none;
        border-radius: 6px;
        font-weight: 700;
        font-size: var(--font-label-size);
    }
    button.download-btn:hover { background: #257c8f; }
"""


def render_page(title: str, body_html: str) -> str:
    """페이지 공통 레이아웃. 전극 검사기 AI(챗봇)가 유일한 기능이므로 body_html이
    전체 앱 셸(.app)을 직접 구성한다 — 예전 위저드 UI가 쓰던 카드형 컨테이너/탭
    네비게이션 wrapper는 채팅 인터페이스에 맞지 않아 제거했다."""
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
    """루트 접속 시 바로 전극 검사기 AI 화면으로 이동한다 (유일한 사용자 기능)."""
    return RedirectResponse(url="/agent")


# ==========================================
# 2. (제거됨) 사양서 제작하기 / 사양서 업로드하기
# ==========================================
# 기존에는 여기에 "/"(자연어 요구사항으로 PPTX 생성)와 "/upload"(RAG 학습용 PPTX
# 업로드) 페이지가 있었다. 전극 검사기 AI(/agent)만 사용자 기능으로 남기기로 하여
# UI/라우트를 제거했다. 이 기능들이 쓰던 generator.py(SpecGenerator)/pptx_builder.py
# (PPTXBuilder) 모듈 자체는 삭제하지 않았다 — preprocess_specs.py가 계속
# import하고, pptx_builder.py는 agent/pptx_electrode_builder.py(Agent의 PPTX 출력
# 기능)가 재사용하는 공통 모듈이기 때문이다.
# ==========================================
# 3. 전극 검사기 사양서 자동 생성 AI Agent 페이지
# ==========================================
@app.get("/agent", response_class=HTMLResponse)
async def agent_page():
    """
    전극 검사기 사양서 자동 생성 AI — 대화형(챗봇) 인터페이스.

    아이콘 사이드바 + 대화 관리 사이드바(새 대화/검색/날짜별 이력) + 메인 대화
    영역의 3단 레이아웃. Backend 파이프라인(RequirementParser/RequirementSchema/
    RAG 검색/CandidateMatcher/Hard Requirement 판정)은 전혀 바꾸지 않았다 —
    /api/agent/analyze-requirement · /api/agent/generate-spec · /api/agent/
    update-requirement · /api/agent/build-markdown을 기존과 동일하게 그대로
    호출한다. 이번 UI 개편에서 Backend에는 단 한 줄도 손대지 않았다.

    Conversation은 서버에 저장하지 않고 브라우저에만 둔다 — 여러 개의 대화를
    배열(state.conversations)로 관리하고 localStorage에 영속화한다(키:
    electrode_ai_conversations_v1). Agent의 RAG/ChromaDB와는 완전히 분리된
    Frontend 전용 상태이며, 매 API 호출은 활성 대화가 들고 있는 조각(current_
    requirement 등)을 그대로 요청 본문에 실어 보낸다 — 서버는 여전히 요청 단위로
    무상태다.
    """
    body_html = """
            <div class="shell" id="appShell">
                <div class="icon-sidebar">
                    <button type="button" id="hamburgerBtn" class="icon-btn" title="사이드바 접기/펼치기">☰</button>
                    <button type="button" class="icon-btn icon-btn-active" title="전극 검사기 AI">🔋</button>
                    <div class="icon-sidebar-spacer"></div>
                    <button type="button" class="icon-btn icon-btn-ghost" title="추가 AI 서비스(예정)" disabled>⚙</button>
                </div>

                <div class="conv-sidebar" id="convSidebar">
                    <div class="conv-sidebar-header">
                        <h1>전극 검사기 AI</h1>
                        <p>전극 검사 장비 검색 및 사양 분석</p>
                    </div>

                    <button type="button" class="conv-action-row" id="newChatBtn">
                        <span class="conv-action-icon">✏</span> 새로운 대화 시작
                    </button>

                    <button type="button" class="conv-action-row" id="searchToggleBtn">
                        <span class="conv-action-icon">🔍</span> 지난 대화 검색
                    </button>
                    <div class="conv-search-box" id="convSearchBox" style="display:none;">
                        <input type="text" id="convSearchInput" placeholder="대화 제목 검색...">
                    </div>

                    <div class="conv-list-label">최근 대화 목록</div>
                    <div class="conv-list" id="convList"></div>
                </div>

                <div class="main-chat">
                    <div id="messages" class="messages"></div>

                    <form id="chatForm" class="input-bar">
                        <textarea id="chatInput" rows="1" placeholder="필요한 전극 검사 조건이나 궁금한 내용을 입력하세요."></textarea>
                        <button type="submit" id="sendBtn">전송</button>
                    </form>
                </div>
            </div>

            <script>
                // ================================================================
                // Conversation State — 서버 세션/DB 없이 브라우저에만 둔다(요청서 12절).
                // 대화 여러 개를 배열로 관리하고 localStorage에 영속화한다. 매 API
                // 호출은 활성 대화(active conversation)가 들고 있는 조각(current_
                // requirement 등)을 그대로 요청 본문에 실어 보낸다 — 서버는 여전히
                // 요청 단위로 무상태이며, Agent의 RAG/ChromaDB와는 완전히 분리된
                // Frontend 전용 상태다.
                // ================================================================
                const STORAGE_KEY = 'electrode_ai_conversations_v1';
                // 브라우저를 껐다가 다시 켜도 대화 기록은 유지하되, 일정 시간(8시간)
                // 이상 사용하지 않으면 자동으로 초기화한다 — "컴퓨터 재부팅 시 초기화"는
                // 웹 API로 구분이 불가능해(브라우저 재시작과 동일하게 보임) 그 대체로
                // 채택한 비활성 시간 기준 초기화다.
                const INACTIVITY_CLEAR_MS = 8 * 60 * 60 * 1000;

                const state = {
                    conversations: [],        // Conversation[] — 아래 getOrCreateActiveConversation() 참고
                    activeConversationId: null,
                    searchQuery: '',
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

                // 마지막 활동(가장 최근 updatedAt/createdAt) 이후 INACTIVITY_CLEAR_MS가
                // 지났으면 전체 대화 기록을 비운다 — 일부만 지우는 게 아니라 세션
                // 전체를 초기화한다(사용자가 기대하는 "오늘 목록이 통째로 사라짐" 동작).
                function pruneInactiveConversations(conversations) {
                    if (!conversations.length) return conversations;
                    const timestamps = conversations
                        .map((c) => new Date(c.updatedAt || c.createdAt).getTime())
                        .filter((t) => !Number.isNaN(t));
                    if (!timestamps.length) return conversations;
                    const mostRecent = Math.max(...timestamps);
                    if (Date.now() - mostRecent > INACTIVITY_CLEAR_MS) {
                        return [];
                    }
                    return conversations;
                }

                function saveConversations() {
                    try {
                        localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations));
                    } catch (e) {
                        // localStorage 사용 불가(프라이빗 모드, 용량 초과 등) — 조용히 무시한다.
                        // 세션 내 메모리(state.conversations)는 계속 정상 동작하므로 새로고침
                        // 전까지는 대화가 유지된다(요청서 12절 1단계 수준으로 자연스럽게 저하).
                    }
                }

                function getActiveConversation() {
                    return state.conversations.find(c => c.id === state.activeConversationId) || null;
                }

                // 활성 대화가 없으면(홈 화면 상태) 이 시점에 새 레코드를 만든다 — "새로운
                // 대화 시작" 버튼을 눌러도 실제로 메시지를 보내기 전까지는 사이드바 목록에
                // 빈 대화가 쌓이지 않는다.
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

                const EXAMPLE_QUESTIONS = [
                    '두께 측정 장비 찾기',
                    '표면 결함 검사기 찾기',
                    'Inline 검사기 찾기',
                    'OCT 기반 장비 찾기',
                    '3D Profile 검사기 찾기',
                ];
                const EXAMPLE_QUESTION_TEXT = {
                    '두께 측정 장비 찾기': '전극 두께를 측정할 수 있는 검사기를 찾아줘.',
                    '표면 결함 검사기 찾기': '전극 표면 결함(스크래치, 이물)을 검사할 수 있는 검사기를 찾아줘.',
                    'Inline 검사기 찾기': 'Inline으로 실시간 검사할 수 있는 전극 검사기를 찾아줘.',
                    'OCT 기반 장비 찾기': 'OCT 기반으로 측정하는 전극 검사기를 찾아줘.',
                    '3D Profile 검사기 찾기': '전극의 3D 프로파일(형상)을 측정할 수 있는 검사기를 찾아줘.',
                };

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
                    if (msg.role === 'user' && conv.title === '새로운 대화') {
                        conv.title = truncateTitle(msg.content && msg.content.text);
                    }
                    saveConversations();
                    return full;
                }

                // ================================================================
                // 렌더링 — 메시지 type별 Component(순수 함수, HTML 문자열 반환)
                // ================================================================
                // 값이 없으면 null을 반환한다(문자열 '미정'이 아니라) — 호출부가 행 자체를
                // 렌더링하지 않고 건너뛸 수 있게 하기 위함이다(요청서: 값 없는 일반 항목은
                // "미정"으로 표시하지 말고 아예 숨긴다. Hard Requirement 비교 영역만 예외).
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

                const STATUS_BADGE = {
                    USER_DEFINED: '<span class="badge badge-userdefined">USER_DEFINED</span>',
                    VERIFIED: '<span class="badge badge-verified">VERIFIED</span>',
                    INFERRED: '<span class="badge badge-inferred">INFERRED</span>',
                    UNKNOWN: '<span class="badge badge-unknown">UNKNOWN</span>',
                };

                function sourceDetailHtml(source) {
                    if (!source || !source.document) return '';
                    const parts = [escapeHtml(source.document)];
                    if (source.chunk_id !== null && source.chunk_id !== undefined) parts.push('chunk_' + escapeHtml(source.chunk_id));
                    if (source.section) parts.push(escapeHtml(source.section));
                    // <summary>가 비어 있고 보이는 "📄 근거 보기" 문구는 CSS ::before로만
                    // 그려져(요청서 15절 접근성 테스트 — axe-core "summary-name" 위반
                    // 실측: 생성된 콘텐츠는 스크린리더 접근성 트리에 이름으로 잡히지
                    // 않는다) 스크린리더 사용자에게는 이름 없는 토글로 들린다.
                    // aria-label을 직접 채우고, 펼침/접힘 상태에 따라 문구가 바뀌도록
                    // ontoggle에서 갱신한다.
                    return `<details class="source-detail" ontoggle="this.querySelector('summary').setAttribute('aria-label', this.open ? '근거 숨기기' : '근거 보기')"><summary aria-label="근거 보기"></summary><div class="source-body">${parts.join(' · ')}</div></details>`;
                }

                // 값 + 단위 + status 배지 + (VERIFIED면) 근거 문서/chunk. 요청서 13절.
                // 값이 없으면 null을 반환한다 — 호출부(EquipmentCard)가 그 행을 아예
                // 렌더링하지 않는다("미정"으로 표시하지 않는다. Hard Requirement 비교
                // 영역은 이 함수를 쓰지 않고 항상 PASS/FAIL/UNKNOWN을 명시한다).
                function fmtSourcedCell(sn) {
                    if (!sn || sn.value === null || sn.value === undefined) {
                        return null;
                    }
                    const badge = STATUS_BADGE[sn.status] || '';
                    const valueText = escapeHtml(sn.value) + (sn.unit ? ' ' + escapeHtml(sn.unit) : '');
                    let html = `<span class="value">${valueText}</span> ${badge}`;
                    if (sn.status === 'VERIFIED' && sn.source && sn.source.document) {
                        html += sourceDetailHtml(sn.source);
                    }
                    return html;
                }

                function fmtSourcedRangeCell(sr) {
                    if (!sr || sr.min === null || sr.min === undefined || sr.max === null || sr.max === undefined) {
                        return null;
                    }
                    const badge = STATUS_BADGE[sr.status] || '';
                    const valueText = `${escapeHtml(sr.min)} ~ ${escapeHtml(sr.max)} ${escapeHtml(sr.unit || '')}`.trim();
                    let html = `<span class="value">${valueText}</span> ${badge}`;
                    if (sr.status === 'VERIFIED' && sr.source && sr.source.document) {
                        html += sourceDetailHtml(sr.source);
                    }
                    return html;
                }

                // ----- 경량 Markdown 렌더러 (요청서 8절) -----
                // 제목/소제목/bullet/번호 목록/표/강조/코드블록만 지원하는 최소 구현이다.
                // escapeHtml()로 먼저 이스케이프한 뒤 그 결과 위에서 안전한 태그만
                // 치환하므로(원본 <, >, &, ", ' 는 이미 엔티티로 바뀐 상태), 사용자/AI
                // 텍스트에 실제 HTML 태그가 섞여 있어도 그대로 렌더링되지 않는다.
                function renderMarkdownLite(rawText) {
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
                            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
                    }

                    for (let i = 0; i < lines.length; i++) {
                        const line = lines[i];
                        if (line.trim().startsWith('```')) {
                            if (codeBuffer === null) { flushList(); flushTable(); codeBuffer = []; }
                            else { htmlParts.push(`<pre class="md-code"><code>${codeBuffer.join('\\n')}</code></pre>`); codeBuffer = null; }
                            continue;
                        }
                        if (codeBuffer !== null) { codeBuffer.push(line); continue; }

                        const headerMatch = line.match(/^(#{1,3})\\s+(.*)$/);
                        if (headerMatch) {
                            flushList(); flushTable();
                            const level = headerMatch[1].length + 2;
                            htmlParts.push(`<h${level} class="md-heading">${inline(headerMatch[2])}</h${level}>`);
                            continue;
                        }

                        const tableRowMatch = line.match(/^\\|(.+)\\|\\s*$/);
                        if (tableRowMatch) {
                            const cells = tableRowMatch[1].split('|').map(c => c.trim());
                            if (cells.every(c => /^:?-{2,}:?$/.test(c))) {
                                continue; // 구분행(|---|---|)은 헤더 확정 후 건너뛴다.
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

                function renderTextMessage(content) {
                    return `<div class="msg-text md-body">${renderMarkdownLite(content.text)}</div>`;
                }

                function renderErrorMessage(content) {
                    return `<span class="msg-text">⚠️ ${escapeHtml(content.text)}</span>`;
                }

                // ----- RequirementSummaryCard (요청서 6절) -----
                // 정책: 사용자가 실제로 입력했거나 대화 중 확정된 값만 보여준다 — 값이
                // 없는 항목은 "미정"으로 채워 넣지 않고 행 자체를 렌더링하지 않는다
                // (실사용자 보고: "측정 원리 미정" 같은 줄이 반복되어 정보 밀도가 낮았다).
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
                        .map(([label, value]) => `<div class="card-row"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(value)}</span></div>`)
                        .join('');
                    return `
                        <div class="card">
                            <div class="card-header">📋 AI가 이해한 요구사항</div>
                            <div class="card-body">${rowsHtml || '<span class="value muted">아직 확정된 조건이 없습니다.</span>'}</div>
                        </div>
                    `;
                }

                // ----- SearchProgressCard (요청서 10절) -----
                // 가짜 진행률이 아니라 실제 API 호출 하나(/generate-spec)의 in-flight
                // 여부에 그대로 연결된다 — 'running'이면 전부 pending, 'done'이면 전부
                // done으로 한 번에 바뀐다(백엔드가 이 4단계를 한 호출 안에서 순서대로
                // 수행하는 것은 사실이며, 이 카드는 그 사실을 정직하게 보여줄 뿐 임의의
                // 시간 간격으로 채워지는 연출이 아니다).
                function renderSearchProgressCard(content) {
                    const stepsPending = ['질문 내용 분석 중', '관련 장비 및 사양 검색 중', '후보 장비 비교 중', '답변 생성 중'];
                    const stepsDone = ['질문 내용 분석 완료', '관련 장비 및 사양 검색 완료', '후보 장비 비교 완료', '답변 생성 완료'];
                    const done = content.status === 'done';
                    const steps = done ? stepsDone : stepsPending;
                    const itemsHtml = steps.map(s => `<li class="${done ? 'done' : 'pending'}">${escapeHtml(s)}</li>`).join('');
                    // 실제 AI와 대화하는 느낌을 주기 위한 typing indicator(요청서 11절) —
                    // 단순 spinner 대신 애니메이션 점 3개를 붙인다. 그 아래 단계 목록은
                    // 여전히 실제 API 호출의 in-flight 여부를 정직하게 반영한다(가짜
                    // 진행률 아님).
                    const runningDots = done ? '' : '<span class="typing-dots"><span></span><span></span><span></span></span>';
                    return `
                        <div class="card">
                            <div class="card-header">${done ? '✅ 검색 완료' : '전극검사기 AI가 장비 정보를 분석하고 있습니다'}${runningDots}</div>
                            <div class="card-body"><ul class="progress-list">${itemsHtml}</ul></div>
                        </div>
                    `;
                }

                // ----- EquipmentCard (요청서 11절) -----
                // 정책(요청서 문제5/6): "추천 순위(ranking)"와 "요구조건 충족 여부
                // (hard requirement compliance)"를 분리해서 보여준다. UNKNOWN이 하나라도
                // 있으면(FAIL이 없어도) "가장 적합한 장비"처럼 단정하지 않고 "확인 필요"로
                // 낮춰서 표현한다 — 검색된 후보 중 상대적으로 나은 순위일 뿐, 요구조건을
                // 전부 확인했다는 뜻이 아니기 때문이다.
                function equipmentBanner(hasFail, hasUnknown, hasRecords) {
                    if (hasFail) return '<div class="banner banner-fail">⚠️ 모든 Hard Requirement를 만족하는 장비를 찾지 못했습니다 — 참고 후보 장비입니다.</div>';
                    if (hasUnknown) return '<div class="banner banner-unknown">⚠️ 조건 일부 확인 필요 — 확인된 조건은 만족하지만, 사양서에서 확인되지 않은 조건이 있어 모든 요구조건을 충족한다고 단정할 수 없습니다.</div>';
                    if (hasRecords) return '<div class="banner banner-pass">✅ Hard Requirement 조건을 모두 충족합니다.</div>';
                    return '';
                }

                function equipmentHeaderPrefix(hasFail, hasUnknown, hasRecords) {
                    if (hasFail) return '🥈 참고 후보';
                    if (!hasFail && !hasUnknown && hasRecords) return '🥇 추천 장비';
                    return '🥈 추천 후보';
                }

                // Hard Requirement 결과를 "확인된 조건(PASS)/미충족 조건(FAIL)/확인 필요
                // (UNKNOWN)"으로 묶어 카드 안에 간단히 요약한다 — 아래 별도 comparison_result
                // 카드(각 항목의 상세 근거/배지)를 대체하지 않고 보완한다.
                function confirmationSummaryHtml(hardRequirementReport) {
                    const records = hardRequirementReport || [];
                    if (records.length === 0) return '';
                    const confirmed = records.filter(r => r.result === 'PASS').map(r => escapeHtml(r.item));
                    const failed = records.filter(r => r.result === 'FAIL').map(r => escapeHtml(r.item));
                    const unresolved = records.filter(r => r.result === 'UNKNOWN').map(r => escapeHtml(r.item));
                    const blocks = [];
                    if (confirmed.length) blocks.push(`<div class="confirm-block confirm-pass"><strong>확인된 조건</strong><br>${confirmed.map(x => '✓ ' + x).join('<br>')}</div>`);
                    if (failed.length) blocks.push(`<div class="confirm-block confirm-fail"><strong>미충족 조건</strong><br>${failed.map(x => '✗ ' + x).join('<br>')}</div>`);
                    if (unresolved.length) blocks.push(`<div class="confirm-block confirm-unknown"><strong>확인 필요</strong><br>${unresolved.map(x => '? ' + x).join('<br>')}</div>`);
                    return blocks.join('');
                }

                function renderDownloadArea(content, msgId) {
                    if (content.downloadUrl) {
                        return `<a class="download-btn" href="${escapeHtml(content.downloadUrl)}" download>마크다운 사양서 다운로드</a>`;
                    }
                    // 후보 장비가 아예 없으면(예: FAIL만 있어 select_best_candidate가
                    // null을 반환한 극단적인 경우는 없지만, 방어적으로) 근거 없는
                    // 사양서를 만들지 않고 버튼 자체를 숨긴다.
                    if (!content.chosenCandidate) {
                        return '';
                    }
                    if (content.markdownGenerating) {
                        return `<button type="button" class="download-btn" disabled style="border:none; opacity:.6; cursor:default;">생성 중...</button>`;
                    }
                    // 오류 배너는 보여주되, 버튼 자체는 사라지지 않고 "다시 시도"로
                    // 남아있어야 한다 — 그렇지 않으면 한 번 실패한 뒤에는 사용자가
                    // 재시도할 방법이 없어 새 검색을 다시 시작해야 하는 silent-failure에
                    // 가까운 상태가 된다(요청서: "클릭 후 아무 변화가 없는 silent
                    // failure가 없는지"·"다시 시도할 수 있는가").
                    const errorBanner = content.markdownError
                        ? `<div class="banner banner-fail" style="margin-top:8px;">⚠️ 마크다운 사양서 생성 중 오류가 발생했습니다: ${escapeHtml(content.markdownError)}</div>`
                        : '';
                    const label = content.markdownError ? '📄 마크다운 사양서 생성 다시 시도' : '📄 마크다운 사양서 생성';
                    return `${errorBanner}<button type="button" class="download-btn build-markdown-btn" data-msg-id="${escapeHtml(msgId)}" style="border:none; cursor:pointer;">${label}</button>`;
                }

                // ----- 참고 문서 / References(문서 14절) — EquipmentCard 하단에 별도
                // 영역으로 표시. 문서별 개별 "문서 보기" 링크는 만들지 않는다 — 이
                // 서버에는 SPEC 원본 파일을 브라우저에서 열어보는 뷰어 라우트가 없어서,
                // 실제로 동작하지 않는 링크를 화면에만 그려 넣는 것은 근거 없는 기능을
                // 지어내는 것과 같기 때문이다(요청서 전반의 "근거 없는 정보를 만들지
                // 않는다" 원칙). 대신 실제로 존재하는 정보(검색된 chunk 수)를 메타
                // 정보로 보여준다.
                function renderSourcesBlock(primarySources, retrievedSourcesCount) {
                    if (!primarySources || primarySources.length === 0) return '';
                    const uniqueSources = Array.from(new Set(primarySources));
                    const items = uniqueSources.map(s => `
                        <div class="source-row">
                            <span>📄 ${escapeHtml(s)}</span>
                        </div>
                    `).join('');
                    return `
                        <div class="sources-block">
                            <div class="sources-title">참고 문서 / References</div>
                            <div class="sources-list">${items}</div>
                            <div class="source-row source-meta" style="margin-top:6px;">검색된 chunk ${escapeHtml(retrievedSourcesCount)}개</div>
                        </div>
                    `;
                }

                // ----- 추가 질문 제안 / Related Questions -----
                // Backend가 별도의 "관련 질문 추천" API를 제공하지 않으므로, 이미 확인된
                // 이 검색 결과(hardRequirementReport)만 근거로 결정론적으로 만든다 —
                // LLM을 다시 호출해 근거 없는 질문을 지어내지 않는다. UNKNOWN 항목이
                // 있으면 그 항목을 확인하는 질문을, 없으면 일반적인 후속 질문만 제안한다.
                function buildRelatedQuestions(content) {
                    const records = content.hardRequirementReport || [];
                    const unknownItems = records.filter(r => r.result === 'UNKNOWN').map(r => r.item);
                    const questions = [];
                    unknownItems.slice(0, 2).forEach(item => {
                        questions.push(`${item} 항목은 어떻게 확인할 수 있나요?`);
                    });
                    questions.push('이 장비가 추천된 이유를 설명해주세요.');
                    questions.push('조건에 맞는 다른 장비도 함께 비교해주세요.');
                    return questions.slice(0, 3);
                }

                function renderRelatedQuestionsBlock(content) {
                    const questions = buildRelatedQuestions(content);
                    if (!questions.length) return '';
                    const items = questions.map(q => `<button type="button" class="related-item" data-related-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('');
                    return `
                        <div class="related-block">
                            <div class="related-title">추가 질문 제안</div>
                            <div class="related-list">${items}</div>
                        </div>
                    `;
                }

                function renderEquipmentCard(content, msgId) {
                    const spec = content.specification;
                    const eq = spec.equipment || {};
                    const target = spec.inspection_target || {};
                    const mp = spec.measurement_performance || {};
                    const dd = spec.defect_detection || {};
                    const ip = spec.inspection_performance || {};
                    const primarySources = (spec.primary_sources && spec.primary_sources.length > 0) ? spec.primary_sources : (spec.sources || []);

                    const noResults = content.retrievedSourcesCount === 0
                        ? '<div class="banner banner-unknown">⚠️ 조건에 맞는 참고 사양서를 찾지 못했습니다(검색된 chunk 0개). 아래 값은 사용자가 입력한 요구사항 외에는 근거가 없습니다.</div>'
                        : '';

                    // 검사 폭/속도는 target.width_mm(요구값 echo)이 아니라 후보 문서에서
                    // 실제로 확인된 equipment_max_width_mm/line_speed_mm_s를 보여준다 —
                    // 다른 행(정확도/최소 검출 결함 크기 등)과 동일하게 "요구값을 그냥
                    // 되돌려 보여주면서 마치 확인된 것처럼 보이는" 문제를 피하기 위함이다
                    // (실사용자 보고 버그: Width/Speed hard requirement가 FAIL인데도
                    // 카드에는 요구값이 그대로 표시되어 통과한 것처럼 보였다).
                    //
                    // 정책: 실제 장비 사양이 존재하는 항목만 보여준다 — None/빈 문자열/
                    // "미정" 등은 행 자체를 감춘다(Hard Requirement 비교 영역만 예외로
                    // 항상 PASS/FAIL/UNKNOWN을 명시한다).
                    const inspectionItemsText = (spec.inspection_items || []).join(', ');
                    const rows = [
                        ['측정 범위', fmtSourcedRangeCell(mp.measurement_range_full)],
                        ['정확도', fmtSourcedCell(mp.equipment_accuracy_um)],
                        ['분해능', fmtSourcedCell(mp.resolution_um)],
                        ['최소 검출 결함 크기', fmtSourcedCell(dd.equipment_minimum_defect_size_um || dd.minimum_defect_size_um)],
                        ['대응 가능 폭', fmtSourcedCell(target.equipment_max_width_mm)],
                        ['검사 속도', fmtSourcedCell(ip.line_speed_mm_s)],
                        ['검사 방식', eq.inline_offline ? `<span class="value">${escapeHtml(eq.inline_offline)}</span>` : null],
                        ['검사 항목', inspectionItemsText ? `<span class="value">${escapeHtml(inspectionItemsText)}</span>` : null],
                    ];
                    const rowsHtml = rows
                        .filter(([, valueHtml]) => valueHtml !== null && valueHtml !== undefined)
                        .map(([label, valueHtml]) => `<div class="card-row"><span class="label">${escapeHtml(label)}</span>${valueHtml}</div>`)
                        .join('');

                    return `
                        <div class="card">
                            <div class="card-header">${equipmentHeaderPrefix(content.hasFail, content.hasUnknown, content.hasRecords)} — ${escapeHtml(eq.name || 'N/A')}</div>
                            <div class="card-body">
                                ${equipmentBanner(content.hasFail, content.hasUnknown, content.hasRecords)}
                                ${noResults}
                                ${confirmationSummaryHtml(content.hardRequirementReport)}
                                ${rowsHtml}
                                ${renderSourcesBlock(primarySources, content.retrievedSourcesCount)}
                                ${renderRelatedQuestionsBlock(content)}
                                ${renderDownloadArea(content, msgId)}
                            </div>
                        </div>
                    `;
                }

                // ----- RequirementComparison (요청서 12/13절) -----
                // 정책: UNKNOWN을 PASS로 표시하지 않는다 — Backend(agent.candidate_matcher/
                // agent.spec_validator)가 이미 PASS/FAIL/UNKNOWN을 코드로 확정해 보내주므로
                // 여기서는 그 값을 그대로(재판단 없이) 배지로만 옮긴다.
                const RESULT_BADGE = {
                    PASS: '<span class="badge badge-pass">PASS</span>',
                    FAIL: '<span class="badge badge-fail">FAIL</span>',
                    UNKNOWN: '<span class="badge badge-unknown">UNKNOWN</span>',
                    'N/A': '<span class="badge badge-unknown" style="background:#e0e0e0; color:#555;">N/A</span>',
                };

                // Backend(agent.spec_validator/agent.candidate_matcher)가 만드는 reason
                // 문구는 "... → PASS"처럼 결과를 문장 끝에 텍스트로도 붙여준다(사람이 읽는
                // 근거 설명 자체에 필요) — 그런데 이 카드는 바로 옆에 같은 결과를 badge로도
                // 보여주므로 그대로 두면 "PASS ... PASS"처럼 중복돼 보인다. 여기서는 화면
                // 표시용으로만 그 꼬리를 잘라내고, reason 문자열 자체(다른 곳에서 재사용될
                // 수 있는 원본 데이터)는 건드리지 않는다.
                function stripTrailingResultArrow(reason) {
                    return (reason || '').replace(/\s*(→|->)\s*(PASS|FAIL|UNKNOWN)\s*$/i, '');
                }

                function renderComparisonCard(content) {
                    const records = content.hardRequirementReport || [];
                    if (records.length === 0) {
                        return `
                            <div class="card">
                                <div class="card-header">Hard Requirement 검증</div>
                                <div class="card-body"><span class="value muted">평가할 조건이 지정되지 않았습니다.</span></div>
                            </div>
                        `;
                    }
                    const itemsHtml = records.map(r => {
                        const badge = RESULT_BADGE[r.result] || RESULT_BADGE.UNKNOWN;
                        const src = (r.result !== 'UNKNOWN' && r.source && r.source.document) ? sourceDetailHtml(r.source) : '';
                        const reasonText = escapeHtml(stripTrailingResultArrow(r.reason));
                        return `<li><span class="item-name">${escapeHtml(r.item)}</span><span class="reason">${reasonText} ${badge}${src}</span></li>`;
                    }).join('');
                    return `
                        <div class="card">
                            <div class="card-header">사용자 요구조건 검증 (Hard Requirement)</div>
                            <div class="card-body"><ul class="hard-req-list">${itemsHtml}</ul></div>
                        </div>
                    `;
                }

                function renderMessageContent(msg) {
                    switch (msg.type) {
                        case 'text': return renderTextMessage(msg.content);
                        case 'requirement_summary': return renderRequirementSummaryCard(msg.content);
                        case 'search_status': return renderSearchProgressCard(msg.content);
                        case 'equipment_result': return renderEquipmentCard(msg.content, msg.id);
                        case 'comparison_result': return renderComparisonCard(msg.content);
                        case 'error': return renderErrorMessage(msg.content);
                        default: return '';
                    }
                }

                function renderExampleChips() {
                    const chips = EXAMPLE_QUESTIONS.map(q => `<button type="button" class="chip" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('');
                    return `<div class="chip-row">${chips}</div>`;
                }

                function makeWelcomeBlock() {
                    const wrap = document.createElement('div');
                    wrap.className = 'welcome-block';
                    wrap.innerHTML = `
                        <div class="welcome-icon">🔋</div>
                        <h2>안녕하세요. 전극검사기 AI입니다.</h2>
                        <p>찾고 있는 전극 검사 장비의 조건이나 궁금한 내용을 입력해주세요.</p>
                        ${renderExampleChips()}
                    `;
                    return wrap;
                }

                function renderAll() {
                    const container = document.getElementById('messages');
                    const conv = getActiveConversation();
                    const messages = conv ? conv.messages : [];
                    const wasAtBottom = (container.scrollTop + container.clientHeight) >= (container.scrollHeight - 40);

                    container.innerHTML = '';
                    if (messages.length === 0) {
                        container.classList.add('is-empty');
                        container.appendChild(makeWelcomeBlock());
                    } else {
                        container.classList.remove('is-empty');
                        messages.forEach(msg => {
                            const isUser = msg.role === 'user';
                            const row = document.createElement('div');
                            row.className = 'msg-row ' + (isUser ? 'user' : 'ai');
                            const bubble = document.createElement('div');
                            bubble.className = 'bubble ' + (isUser ? 'user' : (msg.type === 'error' ? 'ai error' : 'ai'));
                            // .bubble은 텍스트 메시지의 줄바꿈(\\n)을 살리려고 white-space:
                            // pre-wrap을 쓴다 — 그런데 카드 컴포넌트들은 들여쓰기된 템플릿
                            // 리터럴을 반환하므로, trim() 없이 그대로 넣으면 앞뒤 공백/개행이
                            // 그대로 렌더링되어 카드 위에 빈 공백이 보이는 문제가 있다.
                            bubble.innerHTML = renderMessageContent(msg).trim();
                            if (isUser) {
                                // 사용자 Avatar(문서 9절): Secondary-500 Purple.
                                const avatar = document.createElement('div');
                                avatar.className = 'user-avatar';
                                avatar.textContent = '나';
                                row.appendChild(bubble);
                                row.appendChild(avatar);
                            } else {
                                row.appendChild(bubble);
                            }
                            container.appendChild(row);
                        });
                    }
                    if (wasAtBottom || messages.length <= 1) {
                        container.scrollTop = container.scrollHeight;
                    }
                    wireExampleChips();
                    wireCardActions();
                    renderConvList();
                }

                function wireCardActions() {
                    document.querySelectorAll('.build-markdown-btn').forEach(btn => {
                        btn.addEventListener('click', () => buildMarkdownForMessage(btn.dataset.msgId));
                    });
                    // 추가 질문 제안 클릭 시 바로 전송한다(문서 15절: "즉시 질문을 전송").
                    document.querySelectorAll('.related-item').forEach(btn => {
                        btn.addEventListener('click', () => handleUserMessage(btn.dataset.relatedQuestion));
                    });
                }

                // 요청서 흐름의 마지막 단계(최종 사양서 다운로드) — EquipmentCard에 심은
                // 버튼에서 호출된다. 그 검색을 만든 시점의 requirement/validation을 그대로
                // 함께 보내(각 메시지 content에 스냅샷으로 저장해둠) 기존 build-markdown
                // API(agent/routes.py, renderers/markdown_renderer.py)를 그대로 재사용한다.
                async function buildMarkdownForMessage(msgId) {
                    const conv = getActiveConversation();
                    const msg = conv && conv.messages.find(m => m.id === msgId);
                    if (!msg || !msg.content.chosenCandidate) return;
                    // 클릭 즉시 버튼을 "생성 중..."으로 바꿔 눈에 보이는 피드백을 준다 —
                    // 요청이 오래 걸리면 버튼이 그대로 있어 "눌러도 반응이 없다"처럼
                    // 보일 수 있었다.
                    msg.content.markdownGenerating = true;
                    msg.content.markdownError = null;
                    renderAll();
                    try {
                        const data = await postJSON('/api/agent/build-candidate-markdown', {
                            candidate: msg.content.chosenCandidate,
                            requirement: msg.content.requirement,
                        });
                        msg.content.downloadUrl = data.download_url;
                    } catch (err) {
                        msg.content.markdownError = err.message;
                    } finally {
                        msg.content.markdownGenerating = false;
                        saveConversations();
                        renderAll();
                    }
                }

                function wireExampleChips() {
                    document.querySelectorAll('.chip').forEach(btn => {
                        btn.addEventListener('click', () => {
                            const question = btn.dataset.question;
                            handleUserMessage(EXAMPLE_QUESTION_TEXT[question] || question);
                        });
                    });
                }

                // ================================================================
                // 대화 목록 사이드바 — 검색/날짜별 그룹핑/선택
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
                                <button type="button" class="conv-item ${c.id === state.activeConversationId ? 'active' : ''}" data-conv-id="${escapeHtml(c.id)}" title="${escapeHtml(c.title || '새로운 대화')}">
                                    ${escapeHtml(c.title || '새로운 대화')}
                                </button>
                            `).join('')}
                        </div>
                    `).join('');

                    container.querySelectorAll('.conv-item').forEach(btn => {
                        btn.addEventListener('click', () => {
                            state.activeConversationId = btn.dataset.convId;
                            renderAll();
                        });
                    });
                }

                // ================================================================
                // 메시지 처리 — 요청서 5/7/8/9/14/15절
                // ================================================================
                function isExplanationQuery(text) {
                    return /왜|이유|설명해|근거가|어째서/.test(text);
                }

                // 요청서 14절: 근거 없는 내용을 새로 생성하지 않는다 — LLM을 호출하지
                // 않고, 이미 검증된 lastSearchResult(hard_requirement_report)만 문구로
                // 옮긴다.
                // 정책(요청서 문제6): "ranking"(검색된 후보 중 상대적으로 나음)과 "hard
                // requirement compliance"(요구조건을 실제로 다 확인했는지)를 표현을
                // 분리한다 — UNKNOWN이 하나라도 있으면 "추천된 이유"(=전부 만족한다는
                // 인상을 주는 표현) 대신 "확인된 조건을 가장 많이 만족하는 후보"라고만
                // 말하고, 확인되지 않은 조건과 추가 확인이 필요하다는 점을 명시한다.
                function buildExplanationMessage(conv) {
                    const result = conv.lastSearchResult;
                    if (!result) return '아직 추천된 장비가 없습니다. 먼저 요구사항을 말씀해 주세요.';
                    const spec = result.specification;
                    const records = result.hardRequirementReport || [];
                    const name = (spec.equipment && spec.equipment.name) || '이 장비';
                    const passItems = records.filter(r => r.result === 'PASS').map(r => r.item);
                    const failItems = records.filter(r => r.result === 'FAIL').map(r => r.item);
                    const unknownItems = records.filter(r => r.result === 'UNKNOWN').map(r => r.item);

                    if (records.length === 0) {
                        return `${name}에 대해 평가된 Hard Requirement 항목이 없습니다(요구사항에 확인 가능한 조건이 지정되지 않았습니다).`;
                    }

                    const hasFail = failItems.length > 0;
                    const hasUnknown = unknownItems.length > 0;

                    if (!hasFail && !hasUnknown) {
                        return `${name}가 추천된 이유는 다음과 같습니다.\\n\\n` + passItems.map(x => `✓ ${x} 조건 만족`).join('\\n');
                    }

                    const parts = [`현재 검색된 후보 중 확인된 요구조건을 가장 많이 만족하는 후보(${name})입니다.`];
                    if (passItems.length) parts.push('확인된 조건:\\n' + passItems.map(x => `✓ ${x}`).join('\\n'));
                    if (failItems.length) parts.push('충족하지 못한 조건:\\n' + failItems.map(x => `✗ ${x}`).join('\\n'));
                    if (unknownItems.length) parts.push('확인되지 않은 조건:\\n' + unknownItems.map(x => `? ${x}`).join('\\n'));
                    if (hasUnknown) parts.push('따라서 최종 도입 전에는 확인되지 않은 조건을 장비 제조사 또는 추가 사양서로 반드시 확인해야 합니다.');
                    return parts.join('\\n\\n');
                }

                // 요청서 문제1: 후속 메시지가 반영된 뒤 보여줄 문구는 절대 내부 필드명
                // (accuracy, raw_text, required_accuracy_um 등)을 그대로 노출하지 않는다 —
                // 서버(agent/routes.py._summarize_requirement_changes)가 이미 사람이 읽는
                // label/action(added·changed·removed)으로 정리해 보내주므로, 여기서는
                // 그 label만 문구로 옮긴다.
                function buildRequirementChangeMessage(changedSummary) {
                    const added = changedSummary.filter(c => c.action === 'added').map(c => c.label);
                    const changed = changedSummary.filter(c => c.action === 'changed').map(c => c.label);
                    const removed = changedSummary.filter(c => c.action === 'removed').map(c => c.label);

                    if (added.length === 0 && changed.length === 0 && removed.length === 1) {
                        return `요구 ${removed[0]} 조건을 삭제했습니다.\\n\\n기존 조건을 기준으로 다시 검색하겠습니다.`;
                    }

                    const lines = ['요구사항을 수정했습니다.', ''];
                    if (added.length) lines.push('추가된 조건:', ...added.map(l => `- ${l}`), '');
                    if (changed.length) lines.push('변경된 조건:', ...changed.map(l => `- ${l}`), '');
                    if (removed.length) lines.push('삭제된 조건:', ...removed.map(l => `- ${l}`), '');
                    lines.push('나머지 조건은 그대로 유지됩니다. 새로운 조건을 기준으로 다시 검색하겠습니다.');
                    return lines.join('\\n');
                }

                function buildFollowupQuestionText(validation) {
                    const questions = validation.questions || [];
                    if (!questions.length) return '';
                    const numbered = questions.map((q, i) => `${i + 1}. ${q}`).join('\\n');
                    return `더 적합한 장비를 찾기 위해 몇 가지 조건을 추가로 알려주시면 좋습니다(꼭 전부 답하지 않아도 지금 조건으로 검색은 계속 진행됩니다).\\n\\n${numbered}`;
                }

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

                    const data = await postJSON('/api/agent/generate-spec', { requirement: requirement });

                    progressMsg.content = { status: 'done' };

                    const hardRecords = data.hard_requirement_report || [];
                    const hasFail = hardRecords.some(r => r.result === 'FAIL');
                    const hasUnknown = hardRecords.some(r => r.result === 'UNKNOWN');
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
                            specification: data.specification, retrievedSourcesCount: retrievedSourcesCount,
                            hasFail: hasFail, hasUnknown: hasUnknown, hasRecords: hardRecords.length > 0,
                            hardRequirementReport: hardRecords,
                            // build-markdown 호출 시 이 검색을 만든 시점 그대로 재사용하기 위한 스냅샷.
                            requirement: requirement, validation: data.validation,
                            // "마크다운 사양서 생성" 버튼용 — RAG로 찾은 후보 장비 원본 사양
                            // (LLM을 거치지 않은 값). 후보가 아예 없으면 null.
                            chosenCandidate: data.chosen_candidate || null,
                        },
                    });
                    addMessage({ role: 'assistant', type: 'comparison_result', content: { hardRequirementReport: hardRecords } });
                }

                // #chatInput/#sendBtn만 disabled로 막는 것으로는 부족하다 — 추가
                // 질문 제안(.related-item)처럼 메인 입력창과 무관한 다른 클릭
                // 요소에서도 handleUserMessage()를 호출하는데, 이런 요소는 setInput
                // Disabled()의 대상이 아니라서 요청이 진행 중이어도 계속 클릭 가능한
                // 상태로 남는다 — 그 상태에서 빠르게 여러 번 누르면 동일 질문이 여러
                // 번 중복 전송된다(요청서 3/8절: "중복 요청이 발생하지 않는가"). 이
                // 플래그로 handleUserMessage 자체를 재진입 금지시켜 어떤 UI 요소에서
                // 호출되든 동일하게 막는다.
                let isProcessingMessage = false;

                async function handleUserMessage(rawText) {
                    const text = (rawText || '').trim();
                    if (!text || isProcessingMessage) return;
                    isProcessingMessage = true;

                    addMessage({ role: 'user', type: 'text', content: { text: text } });
                    renderAll();

                    const conv = getActiveConversation();

                    if (isExplanationQuery(text) && conv.lastSearchResult) {
                        addMessage({ role: 'assistant', type: 'text', content: { text: buildExplanationMessage(conv) } });
                        renderAll();
                        isProcessingMessage = false;
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
                        isProcessingMessage = false;
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
                    const loaded = loadConversations();
                    state.conversations = pruneInactiveConversations(loaded);
                    if (state.conversations.length > 0) {
                        const sorted = state.conversations.slice().sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
                        state.activeConversationId = sorted[0].id;
                    } else if (loaded.length > 0) {
                        // 비활성 초기화로 목록을 비웠다면 localStorage에도 즉시 반영한다.
                        saveConversations();
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
