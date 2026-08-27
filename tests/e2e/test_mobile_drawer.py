"""
요청서(디자인 시스템/모바일 UX 개선) 섹션 7~13 — 모바일 Sidebar Overlay Drawer.

배경: 이전 수정(PR #34)은 640px 이하에서 사이드바를 "폭 0으로 접기"로 처리해
전송 버튼이 뷰포트 밖으로 밀리는 문제 자체는 고쳤지만, 펼쳤을 때 여전히 본문과
폭을 나눠 가지는 한계가 있었다. 이번에는 `.conv-sidebar`를 640px 이하에서
`position: fixed` + `transform: translateX()` 기반 Overlay Drawer로 바꿔, 열려
있어도 본문(.main-chat) 폭이 전혀 줄어들지 않는지 검증한다.

`.shell.sidebar-collapsed` 클래스는 데스크톱(숨김)과 모바일(열림)에서 반대
의미로 재사용된다 — "지금 열려 있는가"는 실제 렌더링된 위치/투명도로 판단하고,
클래스 이름 자체에 의존하지 않는다(main.py의 isMobileDrawerMode() 로직과 동일한
관점).
"""
from playwright.sync_api import BrowserContext, Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

MOBILE_VIEWPORT = {"width": 375, "height": 812}
QUESTION = "두께 검사기 찾아줘."


def _is_drawer_open(page: Page) -> bool:
    box = page.locator("#convSidebar").bounding_box()
    # Drawer는 아이콘 레일(56px) 바로 뒤(left:56px)에서 시작한다. 닫힌 상태는
    # translateX(-100%)로 x = 56 - width(=280) = -224, 열린 상태는 x = 56 —
    # 0을 기준으로 확실히 갈린다.
    return box["x"] >= 0


def test_mobile_drawer_starts_closed(page: Page, live_server: str):
    ctx_page = page
    ctx_page.set_viewport_size(MOBILE_VIEWPORT)
    ctx_page.goto(f"{live_server}/agent")
    ctx_page.wait_for_selector("#chatInput")

    assert not _is_drawer_open(ctx_page), "모바일 초기 상태에서 Drawer가 열려 있음(기본은 닫힘이어야 함)"
    assert ctx_page.get_attribute("#hamburgerBtn", "aria-expanded") == "false"
    expect(ctx_page.locator("#chatInput")).to_be_visible()
    expect(ctx_page.locator("#sendBtn")).to_be_visible()


def test_hamburger_click_opens_drawer_without_shrinking_main_content(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    main_chat_width_before = page.locator(".main-chat").bounding_box()["width"]

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)  # transform 전환(.2s) 완료 대기

    assert _is_drawer_open(page), "햄버거 클릭 후 Drawer가 열리지 않음"
    assert page.get_attribute("#hamburgerBtn", "aria-expanded") == "true"

    main_chat_width_after = page.locator(".main-chat").bounding_box()["width"]
    assert main_chat_width_after == main_chat_width_before, (
        "Drawer를 열었더니 본문(.main-chat) 폭이 줄어듦 — Overlay가 아니라 여전히 "
        f"폭을 나눠 가짐(before={main_chat_width_before}, after={main_chat_width_after})"
    )


def test_backdrop_appears_when_drawer_open_and_not_when_closed(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    backdrop = page.locator("#mobileBackdrop")
    closed_opacity = backdrop.evaluate("el => getComputedStyle(el).opacity")
    closed_pointer_events = backdrop.evaluate("el => getComputedStyle(el).pointerEvents")
    assert closed_opacity == "0"
    assert closed_pointer_events == "none"

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    open_opacity = backdrop.evaluate("el => getComputedStyle(el).opacity")
    open_pointer_events = backdrop.evaluate("el => getComputedStyle(el).pointerEvents")
    assert open_opacity == "1", "Drawer가 열렸는데 Backdrop이 보이지 않음"
    assert open_pointer_events == "auto"


def test_backdrop_click_closes_drawer(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    assert _is_drawer_open(page)

    # 주의: Playwright의 position은 대상 요소 자신의 좌상단을 기준으로 한다(페이지
    # 절대 좌표가 아니다). Backdrop의 bounding box는 Drawer 패널과 같은 x=56에서
    # 시작해 서로 겹치는 구간(56~336)이 있고, 그 구간은 z-index가 더 높은 Drawer
    # 패널이 위에 있어 클릭을 가로챈다 — Drawer 폭(280px)보다 오른쪽인 지점
    # (element-relative 300, 즉 페이지 x=56+300=356)을 클릭해야 실제로 Backdrop이
    # 받는다.
    page.click("#mobileBackdrop", position={"x": 300, "y": 20})
    page.wait_for_timeout(250)
    assert not _is_drawer_open(page), "Backdrop 클릭 후에도 Drawer가 닫히지 않음"
    assert page.get_attribute("#hamburgerBtn", "aria-expanded") == "false"


def test_hamburger_click_again_closes_drawer(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    assert _is_drawer_open(page)

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    assert not _is_drawer_open(page), "햄버거를 다시 눌러도 Drawer가 닫히지 않음"


def test_escape_key_closes_drawer(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    assert _is_drawer_open(page)

    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert not _is_drawer_open(page), "Escape 키를 눌러도 Drawer가 닫히지 않음"


def test_escape_on_desktop_does_not_collapse_sidebar(page: Page, live_server: str):
    """데스크톱에서는 Escape가 아무 사이드바 동작도 일으키면 안 된다(모바일 전용
    동작이 데스크톱을 침범하지 않는지 확인)."""
    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    sidebar_width_before = page.locator(".conv-sidebar").bounding_box()["width"]
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    sidebar_width_after = page.locator(".conv-sidebar").bounding_box()["width"]
    assert sidebar_width_after == sidebar_width_before, "데스크톱에서 Escape가 사이드바를 접어버림(모바일 전용 동작이 새어나옴)"


def test_focus_moves_into_drawer_on_open_and_returns_to_hamburger_on_close(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    # main.py의 openSidebar()는 Drawer 안으로 포커스를 옮기기 전 80ms를 미룬다
    # (Playwright로 synthetic click을 보내면 브라우저가 클릭 대상의 포커스를
    # 잠깐 더 붙들고 있어 그 즉시 다른 요소로 옮기는 focus() 호출이 조용히
    # 무시되는 현상을 피하기 위함 — 실측상 50ms부터 안정적으로 통과했다) — 그
    # 지연을 넉넉히 흡수하도록 400ms 대기한다.
    page.wait_for_timeout(400)
    focused_in_drawer = page.evaluate(
        "() => document.getElementById('convSidebar').contains(document.activeElement)"
    )
    assert focused_in_drawer, "Drawer를 열었는데 포커스가 Drawer 내부로 이동하지 않음"

    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    focused_id = page.evaluate("() => document.activeElement && document.activeElement.id")
    assert focused_id == "hamburgerBtn", f"Drawer를 닫았는데 포커스가 햄버거 버튼으로 돌아오지 않음(실제: {focused_id})"


def test_drawer_does_not_cause_horizontal_overflow_when_open(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    viewport_width = page.evaluate("window.innerWidth")
    assert scroll_width <= viewport_width + 1, f"Drawer가 열린 상태에서 가로 스크롤 발생: scrollWidth={scroll_width}, viewport={viewport_width}"


def test_closing_drawer_restores_normal_main_content(page: Page, mock_api, live_server: str):
    """Drawer를 열고 닫은 뒤에도 입력/전송이 정상 동작해야 한다(요청서 12절:
    "Sidebar를 닫으면 정상적으로 Main Content로 복귀")."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)
    page.click("#hamburgerBtn")
    page.wait_for_timeout(250)

    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)


# ---------------------------------------------------------------
# 요청서 섹션 13-D — Mobile Input Visibility (여러 실기기 해상도)
# ---------------------------------------------------------------
MOBILE_INPUT_VIEWPORTS = {
    "iPhone SE/8 (375x812)": {"width": 375, "height": 812},
    "iPhone 12/13 (390x844)": {"width": 390, "height": 844},
    "iPhone 11/XR (414x896)": {"width": 414, "height": 896},
    "iPad portrait (768x1024)": {"width": 768, "height": 1024},
}


def test_input_and_send_button_visible_across_mobile_viewports(browser, live_server: str):
    for name, size in MOBILE_INPUT_VIEWPORTS.items():
        ctx: BrowserContext = browser.new_context(viewport=size)
        page = ctx.new_page()
        page.goto(f"{live_server}/agent")
        page.wait_for_selector("#chatInput")

        expect(page.locator("#chatInput")).to_be_visible()
        expect(page.locator("#sendBtn")).to_be_visible()

        send_box = page.locator("#sendBtn").bounding_box()
        assert send_box["x"] + send_box["width"] <= size["width"] + 1, (
            f"[{name}] 전송 버튼이 뷰포트 밖으로 밀려남: right={send_box['x'] + send_box['width']}, "
            f"viewport_width={size['width']}"
        )

        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        assert scroll_width <= size["width"] + 1, f"[{name}] 가로 스크롤 발생: scrollWidth={scroll_width}"

        # 키보드 입력 가능 여부도 함께 확인한다.
        page.fill("#chatInput", "모바일 입력 테스트")
        expect(page.locator("#chatInput")).to_have_value("모바일 입력 테스트")

        ctx.close()


def test_sidebar_open_does_not_break_input_on_any_mobile_viewport(browser, live_server: str):
    for name, size in MOBILE_INPUT_VIEWPORTS.items():
        if size["width"] > 640:
            continue  # 640px 초과는 Overlay Drawer 대상이 아님(데스크톱 취급).
        ctx: BrowserContext = browser.new_context(viewport=size)
        page = ctx.new_page()
        page.goto(f"{live_server}/agent")
        page.wait_for_selector("#chatInput")

        page.click("#hamburgerBtn")
        page.wait_for_timeout(250)

        send_box = page.locator("#sendBtn").bounding_box()
        assert send_box["x"] + send_box["width"] <= size["width"] + 1, (
            f"[{name}] Drawer를 연 상태에서 전송 버튼이 뷰포트 밖으로 밀려남"
        )
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        assert scroll_width <= size["width"] + 1, f"[{name}] Drawer가 열린 상태에서 가로 스크롤 발생"

        ctx.close()


# ---------------------------------------------------------------
# 요청서 섹션 13-E — Desktop Regression
# ---------------------------------------------------------------
def test_desktop_layout_keeps_three_column_structure_unaffected_by_drawer_css(page: Page, live_server: str):
    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    # 모바일 Drawer용 CSS(position:fixed)가 데스크톱에는 전혀 적용되지 않아야 한다.
    sidebar_position = page.locator("#convSidebar").evaluate("el => getComputedStyle(el).position")
    assert sidebar_position != "fixed", "데스크톱에서 사이드바가 모바일 Drawer용 position:fixed를 물려받음"

    backdrop_display = page.locator("#mobileBackdrop").evaluate("el => getComputedStyle(el).display")
    assert backdrop_display == "none", "데스크톱에서 Backdrop이 렌더링 대상으로 남아있음"

    icon_sidebar_box = page.locator(".icon-sidebar").bounding_box()
    conv_sidebar_box = page.locator(".conv-sidebar").bounding_box()
    main_chat_box = page.locator(".main-chat").bounding_box()

    # 아이콘 레일 -> 대화 사이드바 -> 본문 순서로, 서로 겹치지 않고 나란히 배치되어야 한다.
    assert icon_sidebar_box["x"] + icon_sidebar_box["width"] <= conv_sidebar_box["x"] + 1
    assert conv_sidebar_box["x"] + conv_sidebar_box["width"] <= main_chat_box["x"] + 1
    assert conv_sidebar_box["width"] == 280
