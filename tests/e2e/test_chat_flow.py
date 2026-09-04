"""
요청서 3절 Scenario 2~5 — 질문 입력, Enter/전송 버튼, 빠른 연속 클릭, 긴 입력.

/api/agent/analyze-requirement, /api/agent/generate-spec을 mock_api로 가로채
LLM/RAG 변동성 없이 프론트엔드 로직(중복 전송 방지, 로딩 상태, AI 응답 렌더링)만
검증한다. AI 응답의 "정확한 문장"이 아니라 핵심 UI 요소(요구사항 요약/검색 완료/
추천 장비/Hard Requirement) 존재 여부를 확인한다(요청서 지시사항).
"""
import re

from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response, make_requirement

QUESTION = (
    "폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, "
    "0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘."
)

LONG_QUESTION = (
    "폭 1000 mm 이상의 전극을 Inline으로 검사하고 두께와 표면 결함, 스크래치, 오염, "
    "핀홀, Edge Defect를 동시에 검사할 수 있으며 측정 범위는 0~500 μm이고 검사 속도는 "
    "500 mm/s 이상인 장비를 찾아줘."
)


def _mock_success_flow(mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))


def _send_via_button(page: Page, text: str):
    page.fill("#chatInput", text)
    page.click("#sendBtn")


def _wait_for_ai_response(page: Page):
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function(
        "() => !document.getElementById('sendBtn').disabled",
        timeout=10000,
    )


# ---------------------------------------------------------------
# Scenario 2 — 새 질문 입력
# ---------------------------------------------------------------
def test_input_value_reflected_and_sent_on_button_click(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    _send_via_button(agent_page, QUESTION)
    expect(agent_page.locator(".msg-row.user").last).to_contain_text(QUESTION[:20])


def test_input_cleared_after_send_no_double_submit(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    _send_via_button(agent_page, QUESTION)
    expect(agent_page.locator("#chatInput")).to_have_value("")
    _wait_for_ai_response(agent_page)
    assert agent_page.locator(".msg-row.user").count() == 1, "한 번의 전송이 두 번 이상 사용자 메시지로 남았다"


def test_loading_indicator_shown_then_input_disabled_then_reenabled(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response(), delay_ms=600)
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"), delay_ms=600)
    _send_via_button(agent_page, QUESTION)

    # 로딩 중: 입력창/전송 버튼이 "같은 시점"에 함께 비활성화되어야 한다 — 두 개의
    # 개별 web-first assertion을 순차 폴링하면 800ms대의 짧은 mock 지연 구간을
    # 서로 다른 타이밍에 관찰해 flaky해질 수 있어, 한 번의 evaluate로 동시에 읽는다.
    disabled_state = agent_page.evaluate(
        "() => ({input: document.getElementById('chatInput').disabled, "
        "btn: document.getElementById('sendBtn').disabled})"
    )
    assert disabled_state["input"] is True, "로딩 중 입력창이 비활성화되지 않음"
    assert disabled_state["btn"] is True, "로딩 중 전송 버튼이 비활성화되지 않음"
    # 검색 진행 카드(typing indicator)가 보여야 한다.
    expect(agent_page.locator(".progress-list")).to_be_visible(timeout=3000)

    _wait_for_ai_response(agent_page)
    # 완료 후에는 다시 활성화되어야 한다(로딩 상태가 영구적으로 유지되지 않음).
    expect(agent_page.locator("#chatInput")).to_be_enabled()
    expect(agent_page.locator("#sendBtn")).to_be_enabled()


def test_ai_response_contains_core_ui_elements(agent_page: Page, mock_api):
    """AI 응답의 정확한 문장이 아니라, 요구사항 요약/검색 완료/추천 장비/필수 조건
    핵심 요소가 존재하는지만 검증한다(요청서 지시사항 — LLM/RAG 변동성 대비).

    "Hard Requirement"라는 개발자 용어는 UX 개선으로 "필수 조건"으로 바뀌었다 —
    내부 데이터(hard_requirement_report/ComplianceRecord)는 그대로이므로 화면
    표현만 이 문구로 확인한다."""
    _mock_success_flow(mock_api)
    _send_via_button(agent_page, QUESTION)
    _wait_for_ai_response(agent_page)

    full_text = agent_page.locator("#messages").inner_text()
    assert "AI가 이해한 요구사항" in full_text
    assert "검색 완료" in full_text
    assert re.search(r"추천\s*장비|추천\s*후보|참고\s*후보", full_text)
    assert "필수 조건" in full_text
    assert "Hard Requirement" not in full_text, "개발자 용어 'Hard Requirement'가 그대로 노출됨"


# ---------------------------------------------------------------
# Scenario 3 — Enter 키 vs 전송 버튼
# ---------------------------------------------------------------
def test_enter_key_sends_message_same_as_button(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    agent_page.fill("#chatInput", QUESTION)
    agent_page.locator("#chatInput").press("Enter")
    expect(agent_page.locator(".msg-row.user").last).to_contain_text(QUESTION[:20])
    _wait_for_ai_response(agent_page)
    assert agent_page.locator(".msg-row.user").count() == 1


def test_shift_enter_does_not_submit_adds_newline(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    agent_page.fill("#chatInput", "1번째 줄")
    agent_page.locator("#chatInput").press("Shift+Enter")
    agent_page.locator("#chatInput").type("2번째 줄")
    # Shift+Enter는 줄바꿈만 추가하고 전송하지 않는다.
    assert agent_page.locator(".msg-row.user").count() == 0
    expect(agent_page.locator("#chatInput")).to_have_value("1번째 줄\n2번째 줄")


def test_empty_input_not_sent(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    agent_page.click("#sendBtn")
    agent_page.wait_for_timeout(300)
    assert agent_page.locator(".msg-row.user").count() == 0
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 0


def test_whitespace_only_input_not_sent(agent_page: Page, mock_api):
    _mock_success_flow(mock_api)
    agent_page.fill("#chatInput", "    ")
    agent_page.click("#sendBtn")
    agent_page.wait_for_timeout(300)
    assert agent_page.locator(".msg-row.user").count() == 0
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 0


# ---------------------------------------------------------------
# Scenario 4 — 빠른 연속 클릭
# ---------------------------------------------------------------
def test_rapid_repeated_clicks_do_not_duplicate_request_or_message(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response(), delay_ms=300)
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"), delay_ms=300)

    agent_page.fill("#chatInput", QUESTION)
    send_btn = agent_page.locator("#sendBtn")
    # 버튼이 비활성화되기 전 짧은 순간에 여러 번 클릭을 시도한다 — disabled 처리가
    # 늦으면(레이스 컨디션) 중복 전송이 발생할 수 있다.
    for _ in range(5):
        try:
            send_btn.click(timeout=200, force=True)
        except Exception:
            break

    _wait_for_ai_response(agent_page)
    assert agent_page.locator(".msg-row.user").count() == 1, "빠른 연속 클릭으로 동일 질문이 중복 전송됨"
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 1, "API 요청이 중복 발생함"
    # UI가 깨지지 않았는지(가로 스크롤 없음)도 함께 확인한다.
    body_scroll_width = agent_page.evaluate("document.documentElement.scrollWidth")
    viewport_width = agent_page.evaluate("window.innerWidth")
    assert body_scroll_width <= viewport_width + 1


# ---------------------------------------------------------------
# Scenario 5 — 긴 질문 입력
# ---------------------------------------------------------------
def test_long_question_does_not_break_layout(agent_page: Page, mock_api):
    mock_api.mock(
        "**/api/agent/analyze-requirement",
        make_analyze_response(requirement=make_requirement(raw_text=LONG_QUESTION)),
    )
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))

    _send_via_button(agent_page, LONG_QUESTION)
    _wait_for_ai_response(agent_page)

    body_scroll_width = agent_page.evaluate("document.documentElement.scrollWidth")
    viewport_width = agent_page.evaluate("window.innerWidth")
    assert body_scroll_width <= viewport_width + 1, "긴 질문 입력 후 비정상적인 가로 스크롤 발생"

    user_bubble = agent_page.locator(".bubble.user").last
    expect(user_bubble).to_be_visible()
    # 메시지가 잘리지 않고 전체 텍스트를 담고 있어야 한다(말줄임 처리되지 않음).
    expect(user_bubble).to_contain_text(LONG_QUESTION)

    expect(agent_page.locator(".msg-row.ai").last).to_be_visible()
    expect(agent_page.locator("#chatInput")).to_be_visible()
    expect(agent_page.locator("#sendBtn")).to_be_visible()
