"""
요청서 3절 Scenario 1 — 최초 접속.

사용자가 아무 대화 이력도 없는 상태로 /agent에 처음 접속했을 때, 화면이 정상
렌더링되고 존재하지 않는 대화가 보이지 않으며 콘솔 오류가 없는지 검증한다.
"""
from playwright.sync_api import Page, expect


def test_page_renders_with_input_and_send_button(page: Page, live_server: str):
    page.goto(f"{live_server}/agent")
    expect(page.locator("#chatInput")).to_be_visible()
    expect(page.locator("#sendBtn")).to_be_visible()
    expect(page.locator("#sendBtn")).to_have_text("전송")


def test_empty_state_shows_welcome_block_not_fake_history(page: Page, live_server: str):
    page.goto(f"{live_server}/agent")
    # 빈 상태 — 환영 블록이 보여야 한다.
    expect(page.locator(".welcome-block")).to_be_visible()
    expect(page.locator(".welcome-block h2")).to_contain_text("전극검사기 AI")
    # 대화 목록에는 "존재하지 않는 가짜 대화"가 없어야 한다 — 빈 상태 문구만 있어야 한다.
    expect(page.locator("#convList")).to_contain_text("대화 이력이 없습니다.")
    assert page.locator(".conv-item").count() == 0


def test_no_console_or_page_errors_on_load(page: Page, live_server: str):
    page.goto(f"{live_server}/agent")
    page.wait_for_timeout(300)
    assert page.page_errors == [], f"페이지 로드 중 uncaught exception 발생: {page.page_errors}"
    assert page.console_errors == [], f"페이지 로드 중 console.error 발생: {page.console_errors}"


def test_layout_not_broken_no_horizontal_scroll(page: Page, live_server: str):
    page.goto(f"{live_server}/agent")
    body_scroll_width = page.evaluate("document.documentElement.scrollWidth")
    viewport_width = page.evaluate("window.innerWidth")
    assert body_scroll_width <= viewport_width + 1, (
        f"최초 접속 화면에서 불필요한 가로 스크롤 발생: scrollWidth={body_scroll_width}, "
        f"viewportWidth={viewport_width}"
    )


def test_example_question_chips_are_present_and_clickable_targets(page: Page, live_server: str):
    """홈 화면의 Quick Start 질문 chip도 "화면 붕괴 없음"의 일부 — 존재 + 클릭 가능해야 한다."""
    page.goto(f"{live_server}/agent")
    chips = page.locator(".chip")
    assert chips.count() > 0
    for i in range(chips.count()):
        expect(chips.nth(i)).to_be_visible()
        expect(chips.nth(i)).to_be_enabled()
