"""
요청서 3절 섹션 6 — 대화 목록 및 브라우저 상태.

정책 확인(대화로 명시적으로 확정, PR #33): 대화 이력은 "브라우저를 끄면 무조건
사라짐"이 아니라 "8시간 이상 비활성 시 자동 초기화"다(main.py의
INACTIVITY_CLEAR_MS/pruneInactiveConversations()/boot()). 이 정책은 이미
tests/test_conversation_inactivity_reset.py(JS 함수를 Node로 직접 실행해 경계값
검증)로 커버되어 있으므로, 여기서는 실제 브라우저 행동(같은 세션 새로고침 시 유지,
새 브라우저 컨텍스트=localStorage 없음일 때 이력 없음, 8시간 경과 후 재방문 시
초기화)만 종단으로 검증한다.

또한 "존재하지 않는 대화가 남아있으면 안 된다"(빈 날짜 그룹 생성 금지, 이전 질문
자동 복원 금지)와 "불필요한 영구 저장 구조가 없는가"(sessionStorage/Cookie 미사용)도
함께 확인한다.
"""
import json
import time

from playwright.sync_api import BrowserContext, Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

STORAGE_KEY = "electrode_ai_conversations_v1"
QUESTION = "두께 검사기 찾아줘."
EIGHT_HOURS_MS = 8 * 60 * 60 * 1000


def _send(page: Page, text: str):
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def test_same_session_refresh_keeps_conversation(agent_page: Page, mock_api, live_server: str):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, QUESTION)
    assert agent_page.locator(".conv-item").count() == 1

    agent_page.reload()
    agent_page.wait_for_selector("#chatInput")
    full_text = agent_page.locator("#messages").inner_text()
    assert QUESTION in full_text, "같은 세션에서 새로고침했는데 대화 이력이 사라짐(8시간 이내 정책 위반)"
    assert agent_page.locator(".conv-item").count() == 1


def test_new_browser_context_has_no_leftover_history(browser, live_server: str):
    """storage state가 없는 완전히 새 컨텍스트 = 사용자가 처음 쓰는 브라우저와 동일하다."""
    ctx: BrowserContext = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    assert page.locator(".conv-item").count() == 0
    assert page.locator(".conv-group-label").count() == 0, "실제 대화가 없는데 빈 날짜 그룹(오늘/어제)이 생성됨"
    expect(page.locator(".welcome-block")).to_be_visible()
    assert page.locator(".msg-row").count() == 0, "이전 질문이 자동으로 복원됨"

    storage = page.evaluate(f"() => localStorage.getItem('{STORAGE_KEY}')")
    assert storage is None or json.loads(storage) == []
    ctx.close()


def test_no_unnecessary_session_storage_or_cookies(agent_page: Page, mock_api, live_server: str):
    """대화 데이터를 sessionStorage나 Cookie로 이중 저장하는 구조가 없는지 확인한다 —
    영속 저장 지점은 localStorage(STORAGE_KEY) 하나여야 한다."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, QUESTION)

    session_storage_len = agent_page.evaluate("() => window.sessionStorage.length")
    assert session_storage_len == 0, "대화 상태가 sessionStorage에도 저장되고 있음(중복 저장 구조)"

    cookies = agent_page.context.cookies()
    assert cookies == [], f"불필요한 Cookie가 생성됨: {cookies}"

    local_storage_keys = agent_page.evaluate(
        "() => Object.keys(localStorage)"
    )
    assert local_storage_keys == [STORAGE_KEY], f"예상치 못한 localStorage 키 발견: {local_storage_keys}"


def test_conversation_seeded_recently_survives_reload(browser, live_server: str):
    """8시간 이내의 최근 대화를 localStorage에 직접 주입한 뒤 새로고침해도 유지되어야 한다
    (진짜 브라우저 재시작을 흉내내되, 프로세스 재시작 여부와 무관하게 정책은 '경과 시간'
    기준이라는 것을 검증)."""
    ctx: BrowserContext = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    now_ms = int(time.time() * 1000)
    recent_conversations = [
        {
            "id": "recent-1",
            "title": QUESTION,
            "createdAt": now_ms - 60_000,
            "updatedAt": now_ms - 60_000,
            "messages": [{"id": "m1", "role": "user", "type": "text", "content": {"text": QUESTION}, "timestamp": now_ms - 60_000}],
            "currentRequirement": None,
            "currentCandidates": None,
            "lastSearchResult": None,
        }
    ]
    page.evaluate(
        "(data) => localStorage.setItem(data.key, JSON.stringify(data.conversations))",
        {"key": STORAGE_KEY, "conversations": recent_conversations},
    )
    page.reload()
    page.wait_for_selector("#chatInput")

    assert page.locator(".conv-item").count() == 1
    assert QUESTION in page.locator("#messages").inner_text()
    ctx.close()


def test_conversation_inactive_over_8_hours_is_cleared_on_reload(browser, live_server: str):
    """8시간을 초과해 비활성 상태였던 대화는 재방문 시 자동으로 사라져야 한다."""
    ctx: BrowserContext = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    now_ms = int(time.time() * 1000)
    stale_ts = now_ms - EIGHT_HOURS_MS - 60_000
    stale_conversations = [
        {
            "id": "stale-1",
            "title": QUESTION,
            "createdAt": stale_ts,
            "updatedAt": stale_ts,
            "messages": [{"id": "m1", "role": "user", "type": "text", "content": {"text": QUESTION}, "timestamp": stale_ts}],
            "currentRequirement": None,
            "currentCandidates": None,
            "lastSearchResult": None,
        }
    ]
    page.evaluate(
        "(data) => localStorage.setItem(data.key, JSON.stringify(data.conversations))",
        {"key": STORAGE_KEY, "conversations": stale_conversations},
    )
    page.reload()
    page.wait_for_selector("#chatInput")

    assert page.locator(".conv-item").count() == 0
    assert QUESTION not in page.locator("#messages").inner_text()
    expect(page.locator(".welcome-block")).to_be_visible()

    stored_after = page.evaluate(f"() => JSON.parse(localStorage.getItem('{STORAGE_KEY}') || '[]')")
    assert stored_after == [], "8시간 초과 대화를 화면에서는 지웠지만 localStorage에는 남겨둠"
    ctx.close()
