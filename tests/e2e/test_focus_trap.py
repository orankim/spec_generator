"""
요청서(Mobile Drawer 접근성 완성) 섹션 2~4, 16 — Mobile Overlay Drawer의 Focus Trap.

main.py의 getFocusableElements(container)는 Drawer 내부에서 실제로 화면에 보이는
(hidden/display:none이 아닌) 포커스 가능 요소를 그때그때 동적으로 찾는다 — 첫/
마지막 요소를 하드코딩하지 않으므로, 대화가 쌓여 .conv-item 버튼이 늘어나거나
검색창이 열려 요소가 추가돼도 그대로 맞는다. 이 트랩은 "모바일 Drawer 모드 +
열림" 조건에서만 keydown(Tab) 리스너가 개입하고, 그 외(데스크톱, 또는 닫힌 상태)
에는 아무 것도 하지 않아 데스크톱의 기존 키보드 탐색을 건드리지 않는다.
"""
from playwright.sync_api import Page, expect

MOBILE_VIEWPORT = {"width": 375, "height": 812}


def _open_drawer(page: Page):
    page.click("#hamburgerBtn")
    page.wait_for_timeout(400)  # openSidebar()의 80ms 포커스 지연 + 여유


def _focusable_ids_in_drawer(page: Page):
    return page.evaluate(
        """
        () => {
            const selector = 'a[href], button:not([disabled]), textarea:not([disabled]), '
                + 'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
            return Array.from(document.getElementById('convSidebar').querySelectorAll(selector))
                .filter(el => {
                    const s = getComputedStyle(el);
                    return s.display !== 'none' && s.visibility !== 'hidden' && el.getClientRects().length > 0;
                })
                .map(el => el.id || el.tagName);
        }
        """
    )


# ---------------------------------------------------------------
# Test 2/3 — 마지막<->첫 번째 순환
# ---------------------------------------------------------------
def test_tab_from_last_focusable_wraps_to_first(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    ids = _focusable_ids_in_drawer(page)
    assert len(ids) >= 2, f"테스트 전제 조건(포커스 가능 요소 2개 이상) 불충족: {ids}"
    first_id, last_id = ids[0], ids[-1]

    # 마지막 요소로 직접 포커스를 옮긴 뒤 Tab을 누른다.
    page.evaluate(f"() => document.getElementById('{last_id}').focus()")
    assert page.evaluate("() => document.activeElement.id") == last_id
    page.keyboard.press("Tab")
    active = page.evaluate("() => document.activeElement.id")
    assert active == first_id, f"마지막 요소에서 Tab을 눌렀는데 첫 번째({first_id})로 순환하지 않음(실제: {active})"


def test_shift_tab_from_first_focusable_wraps_to_last(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    ids = _focusable_ids_in_drawer(page)
    assert len(ids) >= 2, f"테스트 전제 조건(포커스 가능 요소 2개 이상) 불충족: {ids}"
    first_id, last_id = ids[0], ids[-1]

    assert page.evaluate("() => document.activeElement.id") == first_id  # Drawer Open 시 첫 요소에 이미 포커스됨
    page.keyboard.press("Shift+Tab")
    active = page.evaluate("() => document.activeElement.id")
    assert active == last_id, f"첫 번째 요소에서 Shift+Tab을 눌렀는데 마지막({last_id})으로 순환하지 않음(실제: {active})"


# ---------------------------------------------------------------
# Test 4 — 여러 번 Tab을 눌러도 Main Content로 탈출하지 않음
# ---------------------------------------------------------------
def test_repeated_tab_never_escapes_to_main_content(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    for _ in range(10):  # 실제 요소 개수보다 훨씬 많이 눌러 순환이 계속되는지 확인
        page.keyboard.press("Tab")
        in_drawer = page.evaluate(
            "() => document.getElementById('convSidebar').contains(document.activeElement)"
        )
        assert in_drawer, "반복적인 Tab으로 포커스가 Drawer 밖(Main Content 등)으로 빠져나감"

    for _ in range(10):
        page.keyboard.press("Shift+Tab")
        in_drawer = page.evaluate(
            "() => document.getElementById('convSidebar').contains(document.activeElement)"
        )
        assert in_drawer, "반복적인 Shift+Tab으로 포커스가 Drawer 밖으로 빠져나감"


def test_main_content_is_inert_while_drawer_open(page: Page, live_server: str):
    """요청서 10절: 가능하면 inert로 배경 콘텐츠를 포커스/상호작용 대상에서
    제외 — main.py의 setBackgroundInert()가 실제로 .main-chat에 inert를
    적용/해제하는지 확인한다."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    assert page.evaluate("() => document.querySelector('.main-chat').inert") is False
    _open_drawer(page)
    assert page.evaluate("() => document.querySelector('.main-chat').inert") is True, "Drawer가 열렸는데 .main-chat이 inert 처리되지 않음"

    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.querySelector('.main-chat').inert") is False, "Drawer를 닫았는데 .main-chat의 inert가 풀리지 않음"


# ---------------------------------------------------------------
# 동적 탐색 검증 — 첫/마지막 요소를 하드코딩하지 않았는지 확인
# ---------------------------------------------------------------
def test_focus_trap_uses_dynamic_focusable_list_not_hardcoded(page: Page, live_server: str):
    """검색창을 열어 포커스 가능 요소를 하나 늘린 뒤에도(newChatBtn,
    searchToggleBtn, convSearchInput 3개) 트랩이 새로운 마지막 요소를 정확히
    인식하는지 확인한다 — 요소 2개짜리 목록을 하드코딩했다면 이 테스트가
    실패한다."""
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    ids_before = _focusable_ids_in_drawer(page)
    assert "convSearchInput" not in ids_before, "검색창을 열기 전인데 이미 포커스 가능 목록에 포함됨"

    # 검색 토글을 눌러 검색창을 연다(Drawer 안에서 Tab으로 도달 가능한 새 요소).
    page.evaluate("() => document.getElementById('searchToggleBtn').click()")
    page.wait_for_timeout(100)
    ids_after = _focusable_ids_in_drawer(page)
    assert "convSearchInput" in ids_after, f"검색창을 연 뒤에도 포커스 목록에 반영되지 않음: {ids_after}"

    new_last_id = ids_after[-1]
    first_id = ids_after[0]
    page.evaluate(f"() => document.getElementById('{new_last_id}').focus()")
    page.keyboard.press("Tab")
    active = page.evaluate("() => document.activeElement.id")
    assert active == first_id, (
        f"검색창이 열려 목록이 바뀌었는데도 새 마지막 요소({new_last_id})에서 Tab이 "
        f"첫 요소({first_id})로 순환하지 않음(실제: {active}) — 하드코딩된 목록을 쓰고 있을 가능성"
    )


# ---------------------------------------------------------------
# Test 5/6 — Escape/Backdrop로 닫힌 뒤 트랩 해제
# ---------------------------------------------------------------
def test_trap_disengages_after_escape_close(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.activeElement.id") == "hamburgerBtn"

    # 트랩이 풀렸으므로 Tab을 누르면 일반적인 문서 흐름대로 다음 아이콘 버튼 등으로
    # 자연스럽게 이동해야 한다(Drawer 안에 갇히지 않음).
    page.keyboard.press("Tab")
    active_in_drawer = page.evaluate(
        "() => document.getElementById('convSidebar').contains(document.activeElement)"
    )
    assert not active_in_drawer, "Escape로 닫은 뒤에도 Tab이 여전히 Drawer 안에 갇혀 있음(트랩이 해제되지 않음)"


def test_trap_disengages_after_backdrop_close(page: Page, live_server: str):
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _open_drawer(page)

    # element-relative 좌표: Backdrop은 x=56(아이콘 레일 뒤)부터 시작하고 Drawer
    # 패널(280px)이 앞부분을 덮으므로, 그보다 오른쪽(300)을 클릭해야 실제로
    # Backdrop이 클릭을 받는다.
    page.click("#mobileBackdrop", position={"x": 300, "y": 20})
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.activeElement.id") == "hamburgerBtn"

    page.keyboard.press("Tab")
    active_in_drawer = page.evaluate(
        "() => document.getElementById('convSidebar').contains(document.activeElement)"
    )
    assert not active_in_drawer, "Backdrop 클릭으로 닫은 뒤에도 Tab이 여전히 Drawer 안에 갇혀 있음"


def test_escape_does_not_change_main_content_or_input(page: Page, mock_api, live_server: str):
    """요청서 7절: Escape를 눌러도 Main Content 상태/Conversation/입력창 내용이
    바뀌면 안 된다."""
    from fixtures import make_analyze_response, make_generate_spec_response

    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", "두께 검사기 찾아줘.")
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    messages_before = page.locator("#messages").inner_html()
    page.fill("#chatInput", "지우면 안 되는 초안")

    _open_drawer(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)

    messages_after = page.locator("#messages").inner_html()
    assert messages_before == messages_after, "Escape로 Drawer를 닫았는데 대화 내용(Main Content)이 바뀜"
    expect(page.locator("#chatInput")).to_have_value("지우면 안 되는 초안")


# ---------------------------------------------------------------
# 섹션 17 — Desktop Regression
# ---------------------------------------------------------------
def test_focus_trap_not_active_on_desktop(page: Page, live_server: str):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    assert page.evaluate("() => window.getComputedStyle(document.getElementById('convSidebar')).position") != "fixed"
    assert page.evaluate("() => document.getElementById('mobileBackdrop').offsetParent") is None or \
        page.evaluate("() => getComputedStyle(document.getElementById('mobileBackdrop')).display") == "none"

    # 데스크톱에서는 사이드바 안의 마지막 요소에서 Tab을 눌러도 트랩되지 않고
    # 본문(main-chat)으로 자연스럽게 넘어가야 한다.
    page.evaluate("() => document.getElementById('searchToggleBtn').focus()")
    page.keyboard.press("Tab")
    still_in_sidebar = page.evaluate(
        "() => document.getElementById('convSidebar').contains(document.activeElement)"
    )
    # convSearchBox가 숨겨진 기본 상태에서는 searchToggleBtn 다음 포커스 가능 요소가
    # convList 안에 없으므로(대화 없음) 자연스럽게 사이드바를 벗어나야 한다.
    assert not still_in_sidebar, "데스크톱에서 Tab이 사이드바에 갇힘(Focus Trap이 잘못 활성화됨)"

    assert page.evaluate("() => document.querySelector('.main-chat').inert") is False, "데스크톱에서 본문이 불필요하게 inert 처리됨"


def test_desktop_sidebar_always_visible_no_drawer_overlay(page: Page, live_server: str):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    sidebar_box = page.locator("#convSidebar").bounding_box()
    assert sidebar_box["width"] == 280
    assert sidebar_box["x"] >= 0  # 화면 밖으로 밀려나 있지 않음(오버레이로 숨겨진 상태가 아님)


# ---------------------------------------------------------------
# 섹션 18 — Mobile Viewport Regression (Focus Trap 포함)
# ---------------------------------------------------------------
MOBILE_VIEWPORTS_FOR_TRAP = {
    "375x812": {"width": 375, "height": 812},
    "390x844": {"width": 390, "height": 844},
    "414x896": {"width": 414, "height": 896},
}


def test_focus_trap_works_across_mobile_viewports(browser, live_server: str):
    for name, size in MOBILE_VIEWPORTS_FOR_TRAP.items():
        ctx = browser.new_context(viewport=size)
        page = ctx.new_page()
        page.goto(f"{live_server}/agent")
        page.wait_for_selector("#chatInput")
        _open_drawer(page)

        ids = _focusable_ids_in_drawer(page)
        assert len(ids) >= 2, f"[{name}] 포커스 가능 요소가 예상보다 적음: {ids}"
        assert page.evaluate("() => document.activeElement.id") == ids[0], f"[{name}] Drawer Open 시 첫 요소로 포커스되지 않음"

        page.evaluate(f"() => document.getElementById('{ids[-1]}').focus()")
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.id") == ids[0], f"[{name}] 마지막->첫 순환 실패"

        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        assert scroll_width <= size["width"] + 1, f"[{name}] Drawer 열림 상태에서 가로 스크롤 발생"

        ctx.close()


def test_768_viewport_behaves_as_desktop_not_drawer(page: Page, live_server: str):
    """768x1024(iPad 세로)는 640px 브레이크포인트보다 넓어 Drawer가 아니라
    데스크톱과 동일한 상시 사이드바로 동작해야 한다."""
    page.set_viewport_size({"width": 768, "height": 1024})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    assert page.evaluate("() => window.getComputedStyle(document.getElementById('convSidebar')).position") != "fixed"
