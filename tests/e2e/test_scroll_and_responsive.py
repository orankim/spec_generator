"""
요청서 3절 섹션 12~13 — 스크롤/화면 이동, 반응형 UI.

main.py의 renderAll()은 `wasAtBottom`을 렌더링 직전에 측정해, 사용자가 이미
바닥 근처에 있었을 때만(또는 메시지가 1개 이하일 때) 강제로 스크롤을
내린다(`container.scrollTop = container.scrollHeight`) — 과거 메시지를 보고
있는 도중에는 건드리지 않는다. 이 로직을 실제 스크롤 위치로 검증한다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."
SECOND_QUESTION = "표면 결함도 같이 확인해줘."

VIEWPORTS = {
    "Desktop": {"width": 1920, "height": 1080},
    "Laptop": {"width": 1366, "height": 768},
    "Tablet": {"width": 768, "height": 1024},
    "Mobile": {"width": 375, "height": 812},
}


def _send(page: Page, mock_api, text: str = QUESTION):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


# ---------------------------------------------------------------
# 섹션 12 — 스크롤 및 화면 이동
# ---------------------------------------------------------------
def test_new_message_scrolls_into_view(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    is_near_bottom = agent_page.evaluate(
        """
        () => {
            const el = document.getElementById('messages');
            return (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 40);
        }
        """
    )
    assert is_near_bottom, "새 메시지 생성 후 사용자가 그 메시지를 바로 확인할 수 있는 위치로 이동하지 않음"


def test_does_not_force_scroll_when_user_is_reading_history(agent_page: Page, mock_api):
    """사용자가 과거 메시지를 보고 있는 도중에 새 메시지가 추가돼도 강제로 하단
    이동시키면 안 된다(요청서: "사용자가 과거 메시지를 보고 있는 중이면 강제로
    하단으로 이동시키지 않는가")."""
    _send(agent_page, mock_api, QUESTION)

    # 사용자가 맨 위로 스크롤해서 과거 메시지를 보는 중이라고 가정한다.
    agent_page.evaluate("() => { document.getElementById('messages').scrollTop = 0; }")
    scroll_before = agent_page.evaluate("() => document.getElementById('messages').scrollTop")
    assert scroll_before == 0

    from fixtures import make_requirement, make_update_response

    mock_api.mock(
        "**/api/agent/update-requirement",
        make_update_response(make_requirement(), changed_summary=[{"label": "검사 항목", "action": "changed"}]),
    )
    agent_page.fill("#chatInput", SECOND_QUESTION)
    agent_page.click("#sendBtn")
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    scroll_after = agent_page.evaluate("() => document.getElementById('messages').scrollTop")
    assert scroll_after == 0, "과거 메시지를 보고 있는 도중에 새 메시지가 추가되자 강제로 하단으로 스크롤됨"


def test_input_bar_stays_visible_after_long_conversation(agent_page: Page, mock_api):
    _send(agent_page, mock_api)
    expect(agent_page.locator(".input-bar")).to_be_in_viewport()
    expect(agent_page.locator("#sendBtn")).to_be_in_viewport()
    expect(agent_page.locator("#sendBtn")).to_be_enabled()


# ---------------------------------------------------------------
# 섹션 13 — 반응형 UI
# ---------------------------------------------------------------
def _assert_no_unwanted_horizontal_scroll(page: Page):
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    viewport_width = page.evaluate("window.innerWidth")
    assert scroll_width <= viewport_width + 1, f"가로 스크롤 발생: scrollWidth={scroll_width}, viewport={viewport_width}"


def test_layout_across_viewports(browser, live_server: str):
    for name, size in VIEWPORTS.items():
        ctx = browser.new_context(viewport=size)
        page = ctx.new_page()
        page.goto(f"{live_server}/agent")
        page.wait_for_selector("#chatInput")

        expect(page.locator("#chatInput")).to_be_in_viewport()
        expect(page.locator("#sendBtn")).to_be_in_viewport()
        _assert_no_unwanted_horizontal_scroll(page)

        ctx.close()


def test_hard_requirement_area_readable_and_conv_sidebar_does_not_cover_main_chat(browser, live_server: str):
    from conftest import ApiMocker

    for name, size in VIEWPORTS.items():
        ctx = browser.new_context(viewport=size)
        page = ctx.new_page()
        mocker = ApiMocker(page)
        page.goto(f"{live_server}/agent")
        page.wait_for_selector("#chatInput")

        mocker.mock("**/api/agent/analyze-requirement", make_analyze_response())
        mocker.mock("**/api/agent/generate-spec", make_generate_spec_response("fail"))
        page.fill("#chatInput", QUESTION)
        page.click("#sendBtn")
        expect(page.locator(".hard-req-list")).to_be_visible(timeout=10000)

        # 사이드바가 본문(main-chat)을 가리지 않아야 한다 — 서로 겹치는 영역이 없어야 함.
        sidebar_box = page.locator(".conv-sidebar").bounding_box()
        main_chat_box = page.locator(".main-chat").bounding_box()
        if sidebar_box and main_chat_box:
            sidebar_right_edge = sidebar_box["x"] + sidebar_box["width"]
            assert sidebar_right_edge <= main_chat_box["x"] + 1, (
                f"[{name}] 대화 목록 사이드바가 본문 영역을 가림: sidebar_right={sidebar_right_edge}, "
                f"main_chat_x={main_chat_box['x']}"
            )

        hard_req_box = page.locator(".hard-req-list").bounding_box()
        assert hard_req_box is not None and hard_req_box["width"] > 0, f"[{name}] Hard Requirement 영역이 렌더링되지 않음"
        _assert_no_unwanted_horizontal_scroll(page)

        ctx.close()
