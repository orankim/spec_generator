"""
요청서 3절 섹션 6 및 이번 종합 테스트 요청서 22절 — 대화 목록 및 브라우저 상태.

정책(이번 요청서 22절에서 명시적으로 재확인, 대화로 sessionStorage 전환 결정):
"브라우저 탭/창을 완전히 종료했다가 다시 실행하면 이전 대화 목록이 영구적으로
남아있으면 안 된다." 이전에는 localStorage를 사용해 실제 브라우저 재시작
이후에도 대화 목록이 남아있는 문제가 있었다(Playwright의 새 BrowserContext는
"새 프로필"과 같아서 이 문제를 잡아내지 못했다) — 이번에 sessionStorage로
전환해 브라우저 표준 동작만으로 정책을 만족하도록 수정했다(main.py).

sessionStorage는 같은 탭을 유지하는 동안(새로고침 포함)에는 대화 기록을
보존하되, 그 탭이 닫히면 사라진다. 이 파일은 다음을 검증한다:

1. 같은 탭에서 새로고침 시 대화 유지(기존 정책 유지).
2. 완전히 새 탭/브라우징 컨텍스트 = sessionStorage 없음 = 이전 대화 없음
   (실제 "탭을 닫았다 새로 열었다"의 정확한 시뮬레이션 — sessionStorage는
   최상위 브라우징 컨텍스트 단위이므로 같은 프로필 안에서 새 탭을 열어도
   공유되지 않는다).
3. 8시간 이상 비활성 시 자동 초기화(tests/test_conversation_inactivity_reset.py의
   경계값 단위 테스트를 실제 브라우저 동작으로 보강).
4. localStorage에는 대화 데이터가 전혀 남지 않는지(예전 정책의 잔재가 없는지).
5. "존재하지 않는 대화가 남아있으면 안 된다"(빈 날짜 그룹 생성 금지, 이전 질문
   자동 복원 금지).
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

    storage = page.evaluate(f"() => sessionStorage.getItem('{STORAGE_KEY}')")
    assert storage is None or json.loads(storage) == []
    ctx.close()


def test_closing_and_reopening_tab_does_not_keep_history(browser, live_server: str):
    """
    요청서 22절의 핵심 시나리오: 대화를 나눈 뒤 그 탭을 완전히 닫고, 같은
    브라우저 프로필(같은 BrowserContext)에서 새 탭을 열어 다시 접속했을 때
    이전 대화 목록이 남아있으면 안 된다.

    sessionStorage는 최상위 브라우징 컨텍스트(탭) 단위로 격리되므로, 같은
    BrowserContext 안에서 이전 페이지를 닫고 새 페이지를 여는 것은 실제
    "탭을 닫았다가 새로 열었다"를 정확히 재현한다 — BrowserContext 자체를
    새로 만드는 것(다른 테스트)과 달리, 여기서는 localStorage였다면 여전히
    남아있었을 조건(같은 프로필)을 그대로 유지한 채 탭만 닫는다.
    """
    ctx: BrowserContext = browser.new_context()
    page1 = ctx.new_page()
    page1.goto(f"{live_server}/agent")
    page1.wait_for_selector("#chatInput")

    page1.route("**/api/agent/analyze-requirement", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(make_analyze_response())
    ))
    page1.route("**/api/agent/generate-spec", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(make_generate_spec_response("pass"))
    ))
    _send(page1, QUESTION)
    assert page1.locator(".conv-item").count() == 1
    page1.close()

    page2 = ctx.new_page()
    page2.goto(f"{live_server}/agent")
    page2.wait_for_selector("#chatInput")

    assert page2.locator(".conv-item").count() == 0, "탭을 닫았다 새로 열었는데 이전 대화 목록이 남아있음"
    assert QUESTION not in page2.locator("#messages").inner_text()
    expect(page2.locator(".welcome-block")).to_be_visible()
    ctx.close()


def test_no_conversation_data_in_local_storage(agent_page: Page, mock_api, live_server: str):
    """대화 데이터가 localStorage에는 전혀 남지 않아야 한다(이전 정책의 잔재 확인) —
    영속 저장 지점은 sessionStorage(STORAGE_KEY) 하나뿐이어야 한다."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, QUESTION)

    local_storage_keys = agent_page.evaluate("() => Object.keys(localStorage)")
    assert local_storage_keys == [], f"대화 상태가 localStorage에도 저장되고 있음(이전 정책 잔재): {local_storage_keys}"

    cookies = agent_page.context.cookies()
    assert cookies == [], f"불필요한 Cookie가 생성됨: {cookies}"

    session_storage_keys = agent_page.evaluate("() => Object.keys(sessionStorage)")
    assert session_storage_keys == [STORAGE_KEY], f"예상치 못한 sessionStorage 키 발견: {session_storage_keys}"


def test_conversation_seeded_recently_survives_reload(browser, live_server: str):
    """8시간 이내의 최근 대화를 sessionStorage에 직접 주입한 뒤 새로고침해도 유지되어야
    한다 — 같은 탭이 유지되는 동안에는 정책이 '경과 시간' 기준이라는 것을 검증한다."""
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
        "(data) => sessionStorage.setItem(data.key, JSON.stringify(data.conversations))",
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
        "(data) => sessionStorage.setItem(data.key, JSON.stringify(data.conversations))",
        {"key": STORAGE_KEY, "conversations": stale_conversations},
    )
    page.reload()
    page.wait_for_selector("#chatInput")

    assert page.locator(".conv-item").count() == 0
    assert QUESTION not in page.locator("#messages").inner_text()
    expect(page.locator(".welcome-block")).to_be_visible()

    stored_after = page.evaluate(f"() => JSON.parse(sessionStorage.getItem('{STORAGE_KEY}') || '[]')")
    assert stored_after == [], "8시간 초과 대화를 화면에서는 지웠지만 sessionStorage에는 남겨둠"
    ctx.close()
