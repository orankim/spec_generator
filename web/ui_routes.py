"""
전극 검사기 AI(챗봇) 페이지 라우트 — main.py에서 분리한 순수 화면 계층.

과거에는 이 파일 내용(공통 CSS 850줄 + 챗봇 프론트엔드 JS 1940줄)이 main.py에
Python 문자열로 그대로 박혀 있었다(라우트/프론트엔드/로직이 한 파일에 뒤섞임).
CSS/JS는 어떤 Python 값도 보간(interpolate)하지 않는 완전한 정적 자산이었으므로
(원래도 f-string이 아니라 그냥 삼중따옴표 문자열이었다), static/css/app.css와
static/js/app.js로 그대로 옮기고 여기서는 <link>/<script src> 태그로만 참조한다
— main.py가 이미 "/static"을 StaticFiles로 mount해 두었으므로 별도 서빙 설정이
필요 없다. HTML/CSS/JS "내용" 자체는 한 글자도 바뀌지 않았다(들여쓰기만 파일
최상위 기준으로 정리됨).

Backend 파이프라인(RequirementParser/RequirementSchema/RAG 검색/CandidateMatcher/
Hard Requirement 판정)은 agent/routes.py가 그대로 담당하며, 이 파일은 손대지
않는다.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


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
        <link rel="stylesheet" href="/static/css/app.css">
    </head>
    <body>
        {body_html}
        <script src="/static/js/app.js"></script>
    </body>
    </html>
    """


@router.get("/", include_in_schema=False)
async def read_root():
    """루트 접속 시 바로 전극 검사기 AI 화면으로 이동한다 (유일한 사용자 기능)."""
    return RedirectResponse(url="/agent")


@router.get("/agent", response_class=HTMLResponse)
async def agent_page():
    """
    전극 검사기 사양서 자동 생성 AI — 대화형(챗봇) 인터페이스.

    아이콘 사이드바 + 대화 관리 사이드바(새 대화/검색/날짜별 이력) + 메인 대화
    영역의 3단 레이아웃. Backend 파이프라인(RequirementParser/RequirementSchema/
    RAG 검색/CandidateMatcher/Hard Requirement 판정)은 전혀 바꾸지 않았다 —
    /api/agent/analyze-requirement · /api/agent/generate-spec · /api/agent/
    update-requirement · /api/agent/build-markdown을 기존과 동일하게 그대로
    호출한다.

    Conversation은 서버에 저장하지 않고 브라우저에만 둔다 — 여러 개의 대화를
    배열(state.conversations)로 관리하고 sessionStorage에 저장한다(키:
    electrode_ai_conversations_v1). sessionStorage는 브라우저 탭/창을 완전히
    닫으면 사라지므로(localStorage와 달리) "브라우저를 종료했다 다시 실행하면
    이전 대화 목록이 남아있지 않아야 한다"는 정책을 정확히 만족한다. Agent의
    RAG/ChromaDB와는 완전히 분리된 Frontend 전용 상태이며, 매 API 호출은 활성
    대화가 들고 있는 조각(current_requirement 등)을 그대로 요청 본문에 실어
    보낸다 — 서버는 여전히 요청 단위로 무상태다. 실제 상태 관리/렌더링 로직은
    static/js/app.js에 있다.
    """
    body_html = """
    <div class="shell" id="appShell">
        <div class="icon-sidebar">
            <button type="button" id="hamburgerBtn" class="icon-btn" title="사이드바 접기/펼치기" aria-expanded="true" aria-controls="convSidebar">☰</button>
            <div class="icon-sidebar-spacer"></div>
            <button type="button" class="icon-btn icon-btn-ghost" title="추가 AI 서비스(예정)" disabled>⚙</button>
        </div>

        <!-- 모바일(640px 이하)에서만 렌더링되는 Overlay Drawer용 Backdrop
             (요청서 7~10절) — 데스크톱에서는 CSS 기본값(display:none)으로
             완전히 비활성화된다. -->
        <div class="mobile-backdrop" id="mobileBackdrop" aria-hidden="true"></div>

        <!-- 대화 삭제 확인 모달(요청서 4-2절)이 렌더링되는 위치. 사이드바가
             접혀(width:0/opacity:0) 있어도 모달은 항상 화면 중앙에 정상적으로
             보여야 하므로, 사이드바 내부가 아니라 .shell 바로 아래(항상 표시되는
             레이어)에 별도 root를 둔다. renderConvDeleteModal()이 state.pendingDeleteId
             유무에 따라 내용을 채우거나 비운다. -->
        <div id="convDeleteModalRoot"></div>

        <div class="conv-sidebar" id="convSidebar" role="navigation" aria-label="대화 목록">
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
    """
    return HTMLResponse(content=render_page("전극 검사기 사양서 AI", body_html))
