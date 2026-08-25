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
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
        font-family: -apple-system, "Segoe UI", "맑은 고딕", sans-serif;
        background: #eef1f5;
        color: #1a2530;
    }

    /* ===== App shell ===== */
    .app {
        display: flex;
        flex-direction: column;
        height: 100vh;
        max-width: 920px;
        margin: 0 auto;
        background: #ffffff;
        box-shadow: 0 0 0 1px #e2e8f0;
    }
    .app-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 14px 20px;
        border-bottom: 1px solid #e2e8f0;
        flex-shrink: 0;
    }
    .app-header .icon { font-size: 26px; line-height: 1; }
    .app-header h1 { font-size: 16px; margin: 0; color: #1a2530; font-weight: 700; }
    .app-header p { font-size: 12px; margin: 2px 0 0; color: #718096; }

    /* ===== Messages ===== */
    .messages {
        flex: 1;
        overflow-y: auto;
        padding: 20px;
        display: flex;
        flex-direction: column;
        gap: 14px;
    }
    .msg-row { display: flex; }
    .msg-row.user { justify-content: flex-end; }
    .msg-row.ai { justify-content: flex-start; }
    .bubble {
        max-width: 82%;
        border-radius: 10px;
        padding: 12px 14px;
        font-size: 14px;
        line-height: 1.65;
        word-break: break-word;
    }
    /* white-space:pre-wrap은 .bubble 전체가 아니라 일반 텍스트 메시지에만 적용한다 —
       .bubble에 두면 카드 컴포넌트(.card 등)의 들여쓰기된 템플릿 리터럴 안 개행/공백까지
       상속되어(white-space는 상속 속성) 카드 사이에 의도치 않은 빈 공백이 렌더링된다. */
    .msg-text { white-space: pre-wrap; }
    .card, .card * { white-space: normal; }
    .bubble.user { background: #2b6cb0; color: #ffffff; border-bottom-right-radius: 3px; }
    .bubble.ai { background: #f7f8fa; color: #1a2530; border: 1px solid #e2e8f0; border-bottom-left-radius: 3px; }
    .bubble.error { background: #fff5f5; border: 1px solid #feb2b2; color: #822727; }

    /* ===== Cards (used inside AI bubbles) ===== */
    .card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
    .bubble .card { margin-top: 4px; }
    .card + .card { margin-top: 10px; }
    .card-header {
        padding: 9px 14px;
        background: #f0f4f8;
        border-bottom: 1px solid #e2e8f0;
        font-weight: 700;
        font-size: 13px;
        color: #2d3748;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .card-body { padding: 10px 14px; }
    .card-row {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 6px 0;
        border-bottom: 1px dashed #edf2f7;
        font-size: 13px;
    }
    .card-row:last-child { border-bottom: none; }
    .card-row .label { color: #718096; flex-shrink: 0; }
    .card-row .value {
        color: #1a2530;
        font-weight: 600;
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .card-row .value.muted { color: #a0aec0; font-weight: 400; }

    /* ===== Status badges ===== */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .02em;
        white-space: nowrap;
    }
    .badge-pass { background: #e6fffa; color: #276749; border: 1px solid #9ae6b4; }
    .badge-fail { background: #fff5f5; color: #9b2c2c; border: 1px solid #feb2b2; }
    .badge-unknown { background: #fffaf0; color: #9c4221; border: 1px solid #fbd38d; }
    .badge-verified { background: #ebf8ff; color: #2c5282; border: 1px solid #90cdf4; }
    .badge-inferred { background: #faf5ff; color: #553c9a; border: 1px solid #d6bcfa; }
    .badge-userdefined { background: #f0fff4; color: #22543d; border: 1px solid #9ae6b4; }
    .badge-unset { background: #f7fafc; color: #a0aec0; border: 1px solid #e2e8f0; }

    .banner { padding: 8px 12px; border-radius: 6px; font-size: 13px; font-weight: 700; margin-bottom: 10px; }
    .banner-pass { background: #f0fff4; border: 1px solid #9ae6b4; color: #276749; }
    .banner-fail { background: #fff5f5; border: 1px solid #feb2b2; color: #822727; }
    .banner-unknown { background: #fffaf0; border: 1px solid #fbd38d; color: #7b341e; }

    /* ===== Hard requirement comparison list ===== */
    .hard-req-list { list-style: none; margin: 0; padding: 0; }
    .hard-req-list li {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 10px;
        padding: 7px 0;
        border-bottom: 1px dashed #edf2f7;
        font-size: 13px;
    }
    .hard-req-list li:last-child { border-bottom: none; }
    .hard-req-list .item-name { color: #2d3748; font-weight: 600; flex-shrink: 0; }
    .hard-req-list .reason { color: #4a5568; flex: 1; text-align: right; }

    /* ===== Search progress ===== */
    .progress-list { list-style: none; margin: 0; padding: 0; }
    .progress-list li { padding: 3px 0; font-size: 13px; color: #4a5568; }
    .progress-list li.done { color: #2d3748; }
    .progress-list li.done::before { content: "✓ "; color: #38a169; font-weight: 700; }
    .progress-list li.pending::before { content: "… "; color: #a0aec0; }

    /* ===== Source (VERIFIED evidence) ===== */
    details.source-detail { margin-top: 4px; font-size: 12px; }
    details.source-detail summary { color: #3182ce; cursor: pointer; list-style: none; }
    details.source-detail summary::-webkit-details-marker { display: none; }
    details.source-detail summary::before { content: "📄 근거 보기"; }
    details.source-detail[open] summary::before { content: "📄 근거 숨기기"; }
    details.source-detail .source-body { color: #718096; margin-top: 4px; padding-left: 4px; }

    /* ===== Example question chips (shown before first message) ===== */
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .chip {
        border: 1px solid #cbd5e0;
        background: #ffffff;
        color: #2b6cb0;
        border-radius: 16px;
        padding: 6px 14px;
        font-size: 13px;
        cursor: pointer;
    }
    .chip:hover { background: #ebf8ff; }

    /* ===== Input bar ===== */
    .input-bar {
        display: flex;
        gap: 10px;
        padding: 14px 20px;
        border-top: 1px solid #e2e8f0;
        background: #ffffff;
        flex-shrink: 0;
    }
    .input-bar textarea {
        flex: 1;
        resize: none;
        border: 1px solid #cbd5e0;
        border-radius: 8px;
        padding: 10px 12px;
        font-size: 14px;
        font-family: inherit;
        max-height: 140px;
    }
    .input-bar textarea:focus { outline: none; border-color: #2b6cb0; }
    .input-bar button {
        border: none;
        background: #2b6cb0;
        color: white;
        padding: 0 22px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
    }
    .input-bar button:hover:not(:disabled) { background: #2c5282; }
    .input-bar button:disabled { background: #a0aec0; cursor: not-allowed; }

    a.download-btn {
        display: inline-block;
        margin-top: 8px;
        padding: 8px 16px;
        background: #319795;
        color: white;
        text-decoration: none;
        border-radius: 6px;
        font-weight: 700;
        font-size: 13px;
    }
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

    기존 "입력 -> 분석 버튼 -> 요구사항 확인 -> 사양서 생성" 단계형 위저드를,
    하나의 대화 흐름 안에서 조건을 계속 추가/수정하며 재검색할 수 있는 채팅
    인터페이스로 개편했다. Backend 파이프라인(RequirementParser/RequirementSchema/
    RAG 검색/CandidateMatcher/Hard Requirement 판정)은 전혀 바꾸지 않았다 —
    /api/agent/analyze-requirement · /api/agent/generate-spec · /api/agent/
    build-markdown을 기존과 동일하게 그대로 호출하고, 새로 추가된 것은 후속
    메시지를 대화 상태(state.currentRequirement)에 결정론적으로 "패치"하는
    /api/agent/update-requirement 하나뿐이다(agent/requirement_parser.py의
    apply_conversational_patch — LLM을 호출하지 않는다).

    Conversation State(요청서 7절)는 서버에 별도로 저장하지 않고 이 페이지의
    JS 전역 `state` 객체가 그대로 들고 있다 — 매 API 호출마다 현재 요구사항
    전체를 함께 보내는 기존 방식(예전 UI의 `existing_requirement`)을 그대로
    확장한 것이라, 서버 쪽에 세션/DB 같은 새 인프라를 추가하지 않는다.
    """
    body_html = """
            <div class="app">
                <div class="app-header">
                    <div class="icon">🔋</div>
                    <div>
                        <h1>전극 검사기 AI</h1>
                        <p>전극 검사 설비 요구사항 분석 및 추천</p>
                    </div>
                </div>

                <div id="messages" class="messages"></div>

                <form id="chatForm" class="input-bar">
                    <textarea id="chatInput" rows="1" placeholder="메시지를 입력하세요..."></textarea>
                    <button type="submit" id="sendBtn">전송</button>
                </form>
            </div>

            <script>
                // ================================================================
                // Conversation State — 요청서 7절. 서버 세션 없이 브라우저 메모리에만
                // 둔다. 매 API 호출은 이 상태 중 필요한 조각(current_requirement 등)을
                // 그대로 요청 본문에 실어 보낸다 — 서버는 여전히 요청 단위로 무상태다.
                // ================================================================
                const state = {
                    conversationId: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
                    messages: [],            // {id, role, type, content, timestamp}
                    currentRequirement: null,
                    currentCandidates: null, // 마지막 generate-spec의 hard_requirement_report
                    lastSearchResult: null,  // {specification, validation, hardRequirementReport, retrievedSourcesCount}
                };

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
                    const full = Object.assign({ id: genId(), timestamp: new Date().toISOString() }, msg);
                    state.messages.push(full);
                    return full;
                }

                function lastMessageOfType(type) {
                    for (let i = state.messages.length - 1; i >= 0; i--) {
                        if (state.messages[i].type === type) return state.messages[i];
                    }
                    return null;
                }

                // ================================================================
                // 렌더링 — 메시지 type별 Component(순수 함수, HTML 문자열 반환)
                // ================================================================
                function fmtRange(range) {
                    if (!range || range.min === null || range.min === undefined || range.max === null || range.max === undefined) return '미정';
                    return `${range.min} ~ ${range.max} ${range.unit || ''}`.trim();
                }

                function fmtReqValue(rv, withPlusMinus) {
                    if (!rv || rv.value === null || rv.value === undefined) return '미정';
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
                    return `<details class="source-detail"><summary></summary><div class="source-body">${parts.join(' · ')}</div></details>`;
                }

                // 값 + 단위 + status 배지 + (VERIFIED면) 근거 문서/chunk. 요청서 13절.
                function fmtSourcedCell(sn) {
                    if (!sn || sn.value === null || sn.value === undefined) {
                        return '<span class="value muted">미정</span>';
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
                        return '<span class="value muted">미정</span>';
                    }
                    const badge = STATUS_BADGE[sr.status] || '';
                    const valueText = `${escapeHtml(sr.min)} ~ ${escapeHtml(sr.max)} ${escapeHtml(sr.unit || '')}`.trim();
                    let html = `<span class="value">${valueText}</span> ${badge}`;
                    if (sr.status === 'VERIFIED' && sr.source && sr.source.document) {
                        html += sourceDetailHtml(sr.source);
                    }
                    return html;
                }

                function renderTextMessage(content) {
                    return `<span class="msg-text">${escapeHtml(content.text)}</span>`;
                }

                function renderErrorMessage(content) {
                    return `<span class="msg-text">⚠️ ${escapeHtml(content.text)}</span>`;
                }

                // ----- RequirementSummaryCard (요청서 6절) -----
                function renderRequirementSummaryCard(content) {
                    const req = content.requirement || {};
                    const target = req.target || {};
                    const rows = [
                        ['검사 대상', target.material || '미정'],
                        ['검사 방식', req.inline_offline || '미정'],
                        ['최소 검사 폭', target.width_mm !== null && target.width_mm !== undefined ? `${target.width_mm} mm` : '미정'],
                        ['검사 항목', (req.inspection_items || []).length ? req.inspection_items.join(', ') : '미정'],
                        ['측정 범위', fmtRange(req.measurement_range)],
                        ['측정 방식', req.measurement_method || '미정'],
                        ['측정 원리', req.measurement_principle || '미정'],
                        ['요구 정확도', fmtReqValue(req.accuracy, true)],
                    ];
                    const rowsHtml = rows.map(([label, value]) => {
                        const isUnset = value === '미정';
                        return `<div class="card-row"><span class="label">${escapeHtml(label)}</span><span class="value${isUnset ? ' muted' : ''}">${escapeHtml(value)}</span></div>`;
                    }).join('');
                    return `
                        <div class="card">
                            <div class="card-header">📋 AI가 이해한 요구사항</div>
                            <div class="card-body">${rowsHtml}</div>
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
                    const steps = ['Requirement Parsing 완료', '관련 사양서 검색', '후보 장비 생성', 'Hard Requirement 검증'];
                    const done = content.status === 'done';
                    const itemsHtml = steps.map(s => `<li class="${done ? 'done' : 'pending'}">${escapeHtml(s)}</li>`).join('');
                    return `
                        <div class="card">
                            <div class="card-header">${done ? '✅ 검색 완료' : '⏳ 요구사항을 분석하고 검색 중입니다...'}</div>
                            <div class="card-body"><ul class="progress-list">${itemsHtml}</ul></div>
                        </div>
                    `;
                }

                // ----- EquipmentCard (요청서 11절) -----
                function equipmentBanner(hasFail, hasUnknown, hasRecords) {
                    if (hasFail) return '<div class="banner banner-fail">⚠️ 조건을 모두 충족하는 장비를 찾지 못했습니다 — 가장 유사한 후보입니다.</div>';
                    if (hasUnknown) return '<div class="banner banner-unknown">⚠️ 일부 조건은 사양서에서 확인하지 못했습니다(UNKNOWN).</div>';
                    if (hasRecords) return '<div class="banner banner-pass">✅ Hard Requirement 조건을 모두 충족합니다.</div>';
                    return '';
                }

                function renderDownloadArea(content, msgId) {
                    if (content.downloadUrl) {
                        return `<a class="download-btn" href="${escapeHtml(content.downloadUrl)}" download>마크다운 사양서 다운로드</a>`;
                    }
                    return `<button type="button" class="download-btn build-markdown-btn" data-msg-id="${escapeHtml(msgId)}" style="border:none; cursor:pointer;">📄 마크다운 사양서 생성</button>`;
                }

                function renderEquipmentCard(content, msgId) {
                    const spec = content.specification;
                    const eq = spec.equipment || {};
                    const target = spec.inspection_target || {};
                    const mp = spec.measurement_performance || {};
                    const dd = spec.defect_detection || {};
                    const primarySources = (spec.primary_sources && spec.primary_sources.length > 0) ? spec.primary_sources : (spec.sources || []);

                    const noResults = content.retrievedSourcesCount === 0
                        ? '<div class="banner banner-unknown">⚠️ 조건에 맞는 참고 사양서를 찾지 못했습니다(검색된 chunk 0개). 아래 값은 사용자가 입력한 요구사항 외에는 근거가 없습니다.</div>'
                        : '';

                    const rows = [
                        ['측정 범위', fmtSourcedRangeCell(mp.measurement_range_full)],
                        ['정확도', fmtSourcedCell(mp.equipment_accuracy_um)],
                        ['분해능', fmtSourcedCell(mp.resolution_um)],
                        ['최소 검출 결함 크기', fmtSourcedCell(dd.equipment_minimum_defect_size_um || dd.minimum_defect_size_um)],
                        ['검사 폭', target.width_mm !== null && target.width_mm !== undefined ? `<span class="value">${escapeHtml(target.width_mm)} mm</span>` : '<span class="value muted">미정</span>'],
                        ['검사 방식', eq.inline_offline ? `<span class="value">${escapeHtml(eq.inline_offline)}</span>` : '<span class="value muted">미정</span>'],
                    ];
                    const rowsHtml = rows.map(([label, valueHtml]) => `<div class="card-row"><span class="label">${escapeHtml(label)}</span>${valueHtml}</div>`).join('');

                    return `
                        <div class="card">
                            <div class="card-header">🥇 추천 장비 — ${escapeHtml(eq.name || 'N/A')}</div>
                            <div class="card-body">
                                ${equipmentBanner(content.hasFail, content.hasUnknown, content.hasRecords)}
                                ${noResults}
                                ${rowsHtml}
                                <div class="card-row"><span class="label">검사 항목</span><span class="value">${escapeHtml((spec.inspection_items || []).join(', ') || 'N/A')}</span></div>
                                <div class="card-row"><span class="label">참고 문서</span><span class="value">${escapeHtml(primarySources.join(', ') || '없음')} (chunk ${escapeHtml(content.retrievedSourcesCount)}개)</span></div>
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
                };

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
                        return `<li><span class="item-name">${escapeHtml(r.item)}</span><span class="reason">${escapeHtml(r.reason || '')} ${badge}${src}</span></li>`;
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
                    if (state.messages.length > 0) return '';
                    const chips = EXAMPLE_QUESTIONS.map(q => `<button type="button" class="chip" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('');
                    return `<div class="chip-row">${chips}</div>`;
                }

                function renderAll() {
                    const container = document.getElementById('messages');
                    const wasAtBottom = (container.scrollTop + container.clientHeight) >= (container.scrollHeight - 40);

                    container.innerHTML = '';
                    if (state.messages.length === 0) {
                        container.appendChild(makeAiBubble(WELCOME_TEXT, renderExampleChips()));
                    } else {
                        state.messages.forEach(msg => {
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
                            row.appendChild(bubble);
                            container.appendChild(row);
                        });
                    }
                    if (wasAtBottom || state.messages.length <= 1) {
                        container.scrollTop = container.scrollHeight;
                    }
                    wireExampleChips();
                    wireCardActions();
                }

                function wireCardActions() {
                    document.querySelectorAll('.build-markdown-btn').forEach(btn => {
                        btn.addEventListener('click', () => buildMarkdownForMessage(btn.dataset.msgId));
                    });
                }

                // 요청서 흐름의 마지막 단계(최종 사양서 다운로드) — EquipmentCard에 심은
                // 버튼에서 호출된다. 그 검색을 만든 시점의 requirement/validation을 그대로
                // 함께 보내(각 메시지 content에 스냅샷으로 저장해둠) 기존 build-markdown
                // API(agent/routes.py, renderers/markdown_renderer.py)를 그대로 재사용한다.
                async function buildMarkdownForMessage(msgId) {
                    const msg = state.messages.find(m => m.id === msgId);
                    if (!msg) return;
                    try {
                        const data = await postJSON('/api/agent/build-markdown', {
                            specification: msg.content.specification,
                            requirement: msg.content.requirement,
                            validation: msg.content.validation,
                        });
                        msg.content.downloadUrl = data.download_url;
                        renderAll();
                    } catch (err) {
                        addMessage({ role: 'assistant', type: 'error', content: { text: '마크다운 사양서 생성 중 오류: ' + err.message } });
                        renderAll();
                    }
                }

                function makeAiBubble(text, extraHtml) {
                    const row = document.createElement('div');
                    row.className = 'msg-row ai';
                    const bubble = document.createElement('div');
                    bubble.className = 'bubble ai';
                    bubble.innerHTML = `<span class="msg-text">${escapeHtml(text)}</span>` + (extraHtml || '');
                    row.appendChild(bubble);
                    return row;
                }

                function wireExampleChips() {
                    document.querySelectorAll('.chip').forEach(btn => {
                        btn.addEventListener('click', () => {
                            const question = btn.dataset.question;
                            handleUserMessage(EXAMPLE_QUESTION_TEXT[question] || question);
                        });
                    });
                }

                const WELCOME_TEXT = '안녕하세요.\\n\\n전극 검사 설비의 요구사항을 알려주시면 사양서를 검색하여 적합한 검사 장비를 찾아드리겠습니다.\\n\\n예를 들어,\\n\\n"폭 800 mm 이상의 전극을 Inline으로 검사하고, 0~500 μm 범위를 측정할 수 있는 장비를 찾아줘."\\n\\n와 같이 입력할 수 있습니다.';

                // ================================================================
                // 메시지 처리 — 요청서 5/7/8/9/14/15절
                // ================================================================
                function isExplanationQuery(text) {
                    return /왜|이유|설명해|근거가|어째서/.test(text);
                }

                // 요청서 14절: 근거 없는 내용을 새로 생성하지 않는다 — LLM을 호출하지
                // 않고, 이미 검증된 lastSearchResult(hard_requirement_report)만 문구로
                // 옮긴다.
                function buildExplanationMessage() {
                    const result = state.lastSearchResult;
                    if (!result) return '아직 추천된 장비가 없습니다. 먼저 요구사항을 말씀해 주세요.';
                    const spec = result.specification;
                    const records = result.hardRequirementReport || [];
                    const passLines = records.filter(r => r.result === 'PASS').map(r => `✓ ${r.item} 조건 만족`);
                    const failLines = records.filter(r => r.result === 'FAIL').map(r => `✗ ${r.item} 조건 미충족`);
                    const unknownLines = records.filter(r => r.result === 'UNKNOWN').map(r => `? ${r.item}은(는) 사양서에서 확인되지 않았습니다.`);

                    let text = `${(spec.equipment && spec.equipment.name) || '이 장비'}가 추천된 이유는 다음과 같습니다.\\n\\n`;
                    const blocks = [];
                    if (passLines.length) blocks.push(passLines.join('\\n'));
                    if (failLines.length) blocks.push('다만,\\n\\n' + failLines.join('\\n'));
                    if (unknownLines.length) blocks.push(unknownLines.join('\\n'));
                    text += blocks.length ? blocks.join('\\n\\n') : '(평가된 Hard Requirement 항목이 없습니다.)';
                    return text;
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

                async function runSearch(requirement) {
                    const progressMsg = addMessage({ role: 'assistant', type: 'search_status', content: { status: 'running' } });
                    renderAll();

                    const data = await postJSON('/api/agent/generate-spec', { requirement: requirement });

                    progressMsg.content = { status: 'done' };

                    const hardRecords = data.hard_requirement_report || [];
                    const hasFail = hardRecords.some(r => r.result === 'FAIL');
                    const hasUnknown = hardRecords.some(r => r.result === 'UNKNOWN');
                    const retrievedSourcesCount = (data.retrieved_sources || []).length;

                    state.lastSearchResult = {
                        specification: data.specification,
                        validation: data.validation,
                        hardRequirementReport: hardRecords,
                        retrievedSourcesCount: retrievedSourcesCount,
                    };
                    state.currentCandidates = hardRecords;

                    addMessage({
                        role: 'assistant', type: 'equipment_result',
                        content: {
                            specification: data.specification, retrievedSourcesCount: retrievedSourcesCount,
                            hasFail: hasFail, hasUnknown: hasUnknown, hasRecords: hardRecords.length > 0,
                            // build-markdown 호출 시 이 검색을 만든 시점 그대로 재사용하기 위한 스냅샷.
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

                    if (isExplanationQuery(text) && state.lastSearchResult) {
                        addMessage({ role: 'assistant', type: 'text', content: { text: buildExplanationMessage() } });
                        renderAll();
                        return;
                    }

                    setInputDisabled(true);
                    try {
                        if (!state.currentRequirement) {
                            // 최초 메시지 — 기존 LLM 기반 전체 파싱(agent.requirement_parser.
                            // parse_requirement_text)을 그대로 재사용한다.
                            const data = await postJSON('/api/agent/analyze-requirement', { user_text: text });
                            state.currentRequirement = data.requirement;
                            addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            if (!data.validation.is_valid) {
                                addMessage({ role: 'assistant', type: 'text', content: { text: buildFollowupQuestionText(data.validation) } });
                            }
                            renderAll();
                            await runSearch(state.currentRequirement);
                        } else {
                            // 후속 메시지 — LLM을 다시 부르지 않고 결정론적 패치만 적용한다
                            // (agent.requirement_parser.apply_conversational_patch, 요청서
                            // 22절 원칙 6).
                            const data = await postJSON('/api/agent/update-requirement', { current_requirement: state.currentRequirement, message: text });
                            state.currentRequirement = data.requirement;
                            if (data.changed_fields && data.changed_fields.length > 0) {
                                addMessage({ role: 'assistant', type: 'text', content: { text: '기존 요구사항에 다음 조건을 반영했습니다: ' + data.changed_fields.join(', ') + '\\n\\n새로운 조건을 기준으로 다시 검색하겠습니다.' } });
                                addMessage({ role: 'assistant', type: 'requirement_summary', content: { requirement: data.requirement, validation: data.validation } });
                            } else {
                                addMessage({ role: 'assistant', type: 'text', content: { text: '이 메시지에서 반영할 새 조건을 찾지 못해 기존 요구사항으로 계속 검색하겠습니다.' } });
                            }
                            renderAll();
                            await runSearch(state.currentRequirement);
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

                // 최종 사양서 다운로드(요청서 흐름의 마지막 단계) — EquipmentCard가 아니라
                // 별도 텍스트 메시지로 안내한다. 검색 결과가 있을 때만 노출한다.
                renderAll();
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
