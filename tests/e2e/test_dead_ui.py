"""
요청서 3절 섹션 16 — Dead UI 탐지.

이 파일은 다른 테스트 파일에 흩어져 있는 개별 시나리오(전송 버튼, 마크다운 버튼,
추가 질문 제안 등)를 "클릭했을 때 실제로 기능하는가"라는 하나의 관점으로 모아
한 번에 훑는다 — element 존재 여부가 아니라 클릭 → 관찰 가능한 상태 변화
(DOM 변경, 네트워크 요청, 또는 로컬 상태 변경)가 실제로 일어나는지를 각각
확인한다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _send(page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def test_new_conversation_button_actually_changes_screen_state(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    before = agent_page.locator("#messages").inner_html()
    agent_page.click("#newChatBtn")
    after = agent_page.locator("#messages").inner_html()
    assert before != after, "'새로운 대화 시작' 클릭 후 화면에 아무 변화가 없음(dead UI)"
    expect(agent_page.locator(".welcome-block")).to_be_visible()


def test_search_toggle_button_actually_reveals_search_box(agent_page: Page):
    search_box = agent_page.locator("#convSearchBox")
    assert not search_box.is_visible() or search_box.evaluate("el => getComputedStyle(el).display") == "none"
    agent_page.click("#searchToggleBtn")
    expect(search_box).to_be_visible()
    assert agent_page.locator("#convSearchInput:focus").count() == 1, "검색창을 열었는데 입력 포커스가 이동하지 않음"


def test_conversation_search_input_actually_filters_list(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    agent_page.click("#newChatBtn")
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", "표면 결함 검사기 찾아줘.")
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    assert agent_page.locator(".conv-item").count() == 2
    agent_page.click("#searchToggleBtn")
    agent_page.fill("#convSearchInput", "표면")
    visible_items = agent_page.locator(".conv-item")
    assert visible_items.count() == 1, "대화 검색 입력이 실제로 목록을 필터링하지 않음(dead UI)"
    expect(visible_items.first).to_contain_text("표면")


def test_conversation_list_item_click_actually_switches_active_conversation(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    conv_item = agent_page.locator(".conv-item").first
    assert "active" in (conv_item.get_attribute("class") or "")

    agent_page.click("#newChatBtn")
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", "표면 결함 검사기 찾아줘.")
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    older_item = agent_page.locator(".conv-item").last
    older_item.click()
    full_text = agent_page.locator("#messages").inner_text()
    assert QUESTION in full_text, "대화 목록 항목 클릭이 실제로 대화를 전환하지 않음(dead UI)"


def test_send_button_actually_dispatches_request(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 1
    assert mock_api.call_count("**/api/agent/generate-spec") == 1


def test_related_question_button_actually_sends_and_updates_dom(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    before = agent_page.locator("#messages").inner_html()

    from fixtures import make_requirement, make_update_response

    mock_api.mock(
        "**/api/agent/update-requirement",
        make_update_response(make_requirement(), changed_summary=[]),
    )
    agent_page.locator(".related-item").nth(1).click()
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    after = agent_page.locator("#messages").inner_html()
    assert before != after, "추가 질문 제안 클릭 후 화면에 아무 변화가 없음(dead UI)"
    assert mock_api.call_count("**/api/agent/update-requirement") == 1


def test_markdown_button_actually_dispatches_request_and_changes_dom(agent_page: Page, mock_api):
    """실제 백엔드로 확인 — /api/agent/build-candidate-markdown이 결정론적 순수
    라우트라 mock 없이도 진짜 요청/응답 왕복을 볼 수 있다(test_markdown_button.py의
    상세 시나리오와 별개로, 여기서는 "dead UI가 아니다"라는 최소 사실만 재확인한다)."""
    _send(agent_page, mock_api)
    requests_seen = []
    agent_page.on(
        "request",
        lambda req: requests_seen.append(req.url) if "/api/agent/build-candidate-markdown" in req.url else None,
    )
    before = agent_page.locator("#messages").inner_html()

    agent_page.locator(".build-markdown-btn").click()
    expect(agent_page.locator("a.download-btn")).to_be_visible(timeout=10000)

    after = agent_page.locator("#messages").inner_html()
    assert before != after, "'마크다운 사양서 생성' 클릭 후 화면에 아무 변화가 없음(dead UI)"
    assert len(requests_seen) == 1, "'마크다운 사양서 생성' 클릭이 실제 네트워크 요청으로 이어지지 않음"


def test_hamburger_button_actually_toggles_sidebar(agent_page: Page):
    sidebar = agent_page.locator("#convSidebar")
    width_before = sidebar.bounding_box()["width"]
    agent_page.click("#hamburgerBtn")
    agent_page.wait_for_timeout(250)  # CSS transition(.15s) 완료 대기
    width_after = sidebar.bounding_box()["width"]
    assert width_before != width_after, "햄버거 버튼 클릭 후 사이드바 폭에 변화가 없음(dead UI)"


def test_disabled_settings_icon_is_honestly_disabled_not_dead(agent_page: Page):
    """"추가 AI 서비스(예정)" 아이콘은 클릭해도 반응이 없는 게 맞다 — 다만 이것이
    "죽은 버튼"이 아니라 "의도적으로 비활성화된 버튼"임을 disabled 속성으로
    명확히 표시하고 있는지 확인한다(사용자에게 클릭 가능한 것처럼 보이는 채로
    아무 일도 안 일어나는 진짜 dead UI와는 구분되어야 한다)."""
    settings_btn = agent_page.locator(".icon-btn-ghost")
    expect(settings_btn).to_be_disabled()
