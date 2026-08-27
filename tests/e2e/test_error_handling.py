"""
요청서 3절 섹션 14 — 네트워크 및 API 오류.

main.py의 handleUserMessage()는 postJSON() 실패(네트워크 에러/비-200/JSON 파싱
실패)를 하나의 try/catch/finally로 처리한다 — 어떤 실패든 error 타입 메시지를
추가하고 finally에서 입력을 다시 활성화한다. 이 테스트는 6가지 실패 시나리오
모두에서 "화면이 멈추지 않고, 오류가 보이고, 다시 시도 가능하고, 이전 대화가
사라지지 않는지"를 확인한다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _assert_recoverable_after_error(page: Page, mock_api):
    """오류 후 공통 검증: 입력 재활성화 + 다시 시도 가능 + 이전 대화 보존."""
    expect(page.locator("#chatInput")).to_be_enabled(timeout=5000)
    expect(page.locator("#sendBtn")).to_be_enabled()
    expect(page.locator(".bubble.error")).to_be_visible()

    messages_before_retry = page.locator(".msg-row").count()
    assert messages_before_retry > 0, "오류 발생 후 이전 대화 내용이 화면에서 사라짐"

    # 재시도: 성공 응답으로 바꾸고 같은 질문을 다시 보낸다.
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", "다시 시도")
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)
    assert page.locator(".msg-row").count() > messages_before_retry, "오류 후 재시도가 실제로 처리되지 않음"


def test_connection_failure_shows_error_not_frozen_ui(agent_page: Page, mock_api):
    """1. API 서버 연결 실패."""
    mock_api.abort("**/api/agent/analyze-requirement")
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    _assert_recoverable_after_error(agent_page, mock_api)


def test_http_500_shows_error_message(agent_page: Page, mock_api):
    """2. API 응답 500."""
    mock_api.mock("**/api/agent/analyze-requirement", {"detail": "내부 서버 오류(테스트 주입)"}, status=500)
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".bubble.error")).to_contain_text("내부 서버 오류")
    _assert_recoverable_after_error(agent_page, mock_api)


def test_slow_response_does_not_freeze_ui_and_eventually_resolves(agent_page: Page, mock_api):
    """3. API 응답 지연 — 로딩 상태가 영구 고착되지 않고 결국 완료된다."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response(), delay_ms=800)
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"), delay_ms=800)
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".progress-list")).to_be_visible(timeout=3000)
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    expect(agent_page.locator("#chatInput")).to_be_enabled()
    expect(agent_page.locator("#sendBtn")).to_be_enabled()


def test_malformed_json_response_shows_error_not_frozen_ui(agent_page: Page, mock_api):
    """4. 잘못된 JSON 응답 — res.json() 파싱 자체가 실패하는 경우."""
    mock_api.mock_raw("**/api/agent/analyze-requirement", body="{이것은 유효한 JSON이 아님", status=200)
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    _assert_recoverable_after_error(agent_page, mock_api)


def test_no_rag_results_shows_unknown_banner_not_crash(agent_page: Page, mock_api):
    """5. RAG 검색 결과 없음 — retrieved_sources가 비어있어도 화면이 죽지 않는다."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock(
        "**/api/agent/generate-spec",
        make_generate_spec_response("pass", retrieved_sources_count=0, include_candidate=False),
    )
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    expect(agent_page.locator(".banner-unknown")).to_contain_text("찾지 못했습니다")
    assert agent_page.page_errors == [], f"검색 결과 0건 상황에서 uncaught exception 발생: {agent_page.page_errors}"


def test_no_candidate_equipment_hides_markdown_button_not_crash(agent_page: Page, mock_api):
    """6. 후보 장비 없음 — chosen_candidate=null이어도 화면이 죽지 않고, 근거 없는
    마크다운 버튼을 만들지 않는다(의도된 동작, silent failure 아님)."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock(
        "**/api/agent/generate-spec",
        make_generate_spec_response("pass", include_candidate=False),
    )
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    assert agent_page.locator(".build-markdown-btn").count() == 0
    assert agent_page.page_errors == []
    assert agent_page.console_errors == []
