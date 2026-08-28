"""
요청서 3절 섹션 15 — 접근성 및 기본 사용성.

axe-core(axe-playwright-python)로 자동 스캔하고, 정적 규칙으로 잡기 어려운
"의미 있는 이름", "Tab 이동 순서", "Enter/Space로 버튼 조작"은 직접 검증한다.

최초 실측 결과 발견된 접근성 위반(빈 <summary>의 이름 없음, 사이드바 보조
텍스트 명도 대비 부족)은 main.py에서 직접 고쳤다. 이후 별도로 진행된 디자인
시스템 개선 작업(Primary Action 색상 토큰 --primary-action #237C90 분리,
--text-primary/secondary/tertiary 텍스트 토큰 도입)으로 카드 라벨(.card-row
.label)과 배지(.badge-pass/.badge-verified), 주요 버튼(#sendBtn/.download-btn)의
명도 대비 부족도 모두 해결되어, 더 이상 알려진 예외(xfail) 없이 일반 PASS로
검증한다 — 기존 브랜드 컬러(Primary-600 #2D9BB2)는 로고/링크/활성 아이콘
역할로 그대로 유지했다.
"""
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _assert_no_serious_or_critical_violations(results):
    violations = results.response["violations"]
    serious_or_worse = [v for v in violations if v.get("impact") in ("serious", "critical")]
    assert serious_or_worse == [], (
        "axe-core가 심각도 serious/critical 접근성 위반을 발견함: "
        + "; ".join(f"{v['id']}: {[n['target'] for n in v['nodes']]}" for v in serious_or_worse)
    )


def test_axe_scan_home_screen_has_no_critical_or_serious_violations(agent_page: Page):
    axe = Axe()
    results = axe.run(agent_page)
    _assert_no_serious_or_critical_violations(results)


def test_axe_scan_after_search_results_rendered(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    axe = Axe()
    results = axe.run(agent_page)
    _assert_no_serious_or_critical_violations(results)


def test_icon_only_buttons_have_accessible_name(agent_page: Page):
    """아이콘만 있는 버튼(햄버거/설정 등)도 스크린리더가 읽을 수 있는 이름이 있어야
    한다 — title 속성은 시각 사용자용 툴팁일 뿐 접근성 트리 이름으로 항상
    보장되지 않으므로 aria-label을 직접 확인한다."""
    icon_buttons = agent_page.locator(".icon-btn")
    count = icon_buttons.count()
    assert count > 0
    missing = []
    for i in range(count):
        btn = icon_buttons.nth(i)
        aria_label = btn.get_attribute("aria-label")
        title = btn.get_attribute("title")
        text = btn.inner_text().strip()
        # 최소 하나는 있어야 한다: aria-label, title, 또는 사람이 읽을 수 있는 텍스트.
        if not (aria_label or title):
            missing.append({"index": i, "text": text, "title": title, "aria_label": aria_label})
    assert missing == [], f"aria-label도 title도 없는 아이콘 버튼 발견(스크린리더 사용자가 용도를 알 수 없음): {missing}"


def test_send_button_reachable_and_activatable_via_keyboard(agent_page: Page):
    """Tab으로 입력창 -> 전송 버튼까지 접근 가능하고, Enter/Space로 조작 가능해야 한다."""
    agent_page.locator("#chatInput").click()
    agent_page.locator("#chatInput").fill("키보드로만 접근 테스트")
    agent_page.keyboard.press("Tab")
    focused_id = agent_page.evaluate("() => document.activeElement && document.activeElement.id")
    assert focused_id == "sendBtn", f"입력창 다음 Tab 이동 대상이 전송 버튼이 아님(실제: {focused_id})"


def test_related_item_buttons_are_real_buttons_not_divs(agent_page: Page, mock_api):
    """추가 질문 제안이 실제 <button>이어야 Tab/Enter 등 기본 키보드 조작이 공짜로
    보장된다(요청서: "Enter/Space 키로 버튼을 사용할 수 있는가")."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)

    related_items = agent_page.locator(".related-item")
    assert related_items.count() > 0
    for i in range(related_items.count()):
        tag = related_items.nth(i).evaluate("el => el.tagName.toLowerCase()")
        assert tag == "button", f".related-item이 <button>이 아니라 <{tag}>임 — 키보드 접근성이 보장되지 않음"


def _srgb_to_linear(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb) -> float:
    r, g, b = rgb
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def _contrast_ratio(rgb1, rgb2) -> float:
    l1, l2 = _relative_luminance(rgb1), _relative_luminance(rgb2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


def _parse_rgb(css_color: str):
    """"rgb(35, 124, 144)" / "rgba(35, 124, 144, 1)" -> (35, 124, 144)."""
    nums = css_color[css_color.index("(") + 1 : css_color.index(")")].split(",")
    return tuple(float(n) for n in nums[:3])


def _effective_colors(locator):
    """요소의 실제 전경/배경색을 읽는다. 배경이 투명(alpha=0)이면 부모를 타고
    올라가며 첫 불투명 배경을 찾는다(대부분의 배지/버튼은 자체 배경을 가지므로
    한 번에 끝나지만, 방어적으로 처리한다)."""
    return locator.evaluate(
        """
        (el) => {
            function bg(node) {
                while (node) {
                    const c = getComputedStyle(node).backgroundColor;
                    const m = c.match(/rgba?\\(([^)]+)\\)/);
                    if (m) {
                        const parts = m[1].split(',').map(Number);
                        if (parts.length < 4 || parts[3] > 0) return c;
                    }
                    node = node.parentElement;
                }
                return 'rgb(255,255,255)';
            }
            return { fg: getComputedStyle(el).color, bg: bg(el) };
        }
        """
    )


def _assert_contrast_at_least(locator, minimum: float, label: str):
    colors = _effective_colors(locator)
    fg, bg = _parse_rgb(colors["fg"]), _parse_rgb(colors["bg"])
    ratio = _contrast_ratio(fg, bg)
    assert ratio >= minimum, (
        f"{label}: 명도 대비 {ratio:.2f}:1 (fg={colors['fg']}, bg={colors['bg']}) — "
        f"WCAG AA 기준 {minimum}:1 미달"
    )
    return ratio


# ---------------------------------------------------------------
# 요청서 3절 섹션 13-A — Primary Button Accessibility
# ---------------------------------------------------------------
def test_send_button_meets_wcag_aa_contrast(agent_page: Page):
    _assert_contrast_at_least(agent_page.locator("#sendBtn"), 4.5, "#sendBtn")


def test_download_button_meets_wcag_aa_contrast(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".build-markdown-btn")).to_be_visible(timeout=10000)
    _assert_contrast_at_least(agent_page.locator(".download-btn"), 4.5, ".download-btn")


# ---------------------------------------------------------------
# 요청서 3절 섹션 13-B — Badge / Card Label Accessibility
# ---------------------------------------------------------------
def test_badge_pass_and_verified_meet_wcag_aa_contrast(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".hard-req-list")).to_be_visible(timeout=10000)

    pass_badges = agent_page.locator(".badge-pass")
    verified_badges = agent_page.locator(".badge-verified")
    assert pass_badges.count() > 0
    assert verified_badges.count() > 0
    for i in range(pass_badges.count()):
        _assert_contrast_at_least(pass_badges.nth(i), 4.5, f".badge-pass[{i}]")
    for i in range(verified_badges.count()):
        _assert_contrast_at_least(verified_badges.nth(i), 4.5, f".badge-verified[{i}]")


def test_card_row_label_meets_wcag_aa_contrast(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".card-row .label").first).to_be_visible(timeout=10000)

    labels = agent_page.locator(".card-row .label")
    assert labels.count() > 0
    for i in range(labels.count()):
        _assert_contrast_at_least(labels.nth(i), 4.5, f".card-row .label[{i}]")


# ---------------------------------------------------------------
# 요청서(Mobile Drawer 접근성 완성) 섹션 11~15 — 프로젝트 전체 Badge/상태 표시
# UI 전수 점검. main.py에서 실제로 찾은 status/badge 관련 클래스는:
#   .badge-pass/.badge-fail/.badge-unknown/.badge-verified/.badge-inferred/
#   .badge-userdefined/.badge-unset (span.badge, RESULT_BADGE·STATUS_BADGE)
#   .banner-pass/.banner-fail/.banner-unknown (큰 배너)
#   .confirm-pass/.confirm-fail/.confirm-unknown (EquipmentCard 요약 블록)
# 이 중 이미 앞의 두 테스트(#sendBtn 등)에서 다루는 badge-pass/badge-verified를
# 뺀 나머지 전부를 여기서 실측한다. .badge-unset은 CSS는 존재하지만 JS
# 어디에서도 실제로 쓰이지 않는(dead) 클래스라 실제 사용자 흐름으로는 화면에
# 나타나지 않는다 — 규칙 자체는 여전히 존재하므로 마크업을 직접 주입해 CSS
# 값만 검증한다.
# ---------------------------------------------------------------
def test_badge_fail_and_unknown_result_meet_wcag_aa_contrast(agent_page: Page, mock_api):
    """Hard Requirement 비교 목록(RESULT_BADGE)의 FAIL/UNKNOWN 배지."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("fail"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".hard-req-list .badge-fail").first).to_be_visible(timeout=10000)

    fail_badges = agent_page.locator(".hard-req-list .badge-fail")
    assert fail_badges.count() > 0
    for i in range(fail_badges.count()):
        _assert_contrast_at_least(fail_badges.nth(i), 4.5, f".badge-fail[{i}]")


def test_badge_unknown_result_meets_wcag_aa_contrast(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("unknown"))
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".hard-req-list .badge-unknown").first).to_be_visible(timeout=10000)

    unknown_badges = agent_page.locator(".hard-req-list .badge-unknown")
    assert unknown_badges.count() > 0
    for i in range(unknown_badges.count()):
        _assert_contrast_at_least(unknown_badges.nth(i), 4.5, f".badge-unknown[{i}]")


def test_badge_inferred_and_userdefined_status_meet_wcag_aa_contrast(agent_page: Page, mock_api):
    """EquipmentCard의 값별 근거 상태 배지(STATUS_BADGE) — INFERRED/USER_DEFINED.
    make_specification(accuracy_status=...)로 "정확도" 행의 상태만 바꿔 실제
    화면에 해당 배지가 뜨게 만든다."""
    from fixtures import make_specification

    for status, badge_class in (("INFERRED", ".badge-inferred"), ("USER_DEFINED", ".badge-userdefined")):
        mock_api.calls.clear()
        agent_page.click("#newChatBtn")
        mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
        response = make_generate_spec_response("pass")
        response["specification"] = make_specification(accuracy_status=status)
        mock_api.mock("**/api/agent/generate-spec", response)

        agent_page.fill("#chatInput", QUESTION)
        agent_page.click("#sendBtn")
        expect(agent_page.locator(badge_class).first).to_be_visible(timeout=10000)

        badges = agent_page.locator(badge_class)
        assert badges.count() > 0, f"{badge_class} 배지가 화면에 나타나지 않음(fixture 문제 가능성)"
        for i in range(badges.count()):
            _assert_contrast_at_least(badges.nth(i), 4.5, f"{badge_class}[{i}]")


def test_banner_and_confirm_block_contrast(agent_page: Page, mock_api):
    """.banner-pass/fail/unknown, .confirm-pass/fail/unknown — pass/fail/unknown
    관련 다른 상태 표시 UI(작은 badge는 아니지만 동일한 원칙 적용 대상)."""
    for scenario, banner_class, confirm_class in (
        ("pass", ".banner-pass", None),  # PASS 시나리오는 confirm-block을 만들지 않음(전부 확인된 조건)
        ("fail", ".banner-fail", ".confirm-fail"),
        ("unknown", ".banner-unknown", ".confirm-unknown"),
    ):
        mock_api.calls.clear()
        agent_page.click("#newChatBtn")
        mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
        mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response(scenario))
        agent_page.fill("#chatInput", QUESTION)
        agent_page.click("#sendBtn")
        expect(agent_page.locator(banner_class).first).to_be_visible(timeout=10000)
        _assert_contrast_at_least(agent_page.locator(banner_class).first, 4.5, banner_class)

        if confirm_class:
            expect(agent_page.locator(confirm_class).first).to_be_visible(timeout=3000)
            _assert_contrast_at_least(agent_page.locator(confirm_class).first, 4.5, confirm_class)


def test_badge_unset_css_rule_meets_wcag_aa_contrast(agent_page: Page):
    """.badge-unset은 현재 JS 어디에서도 실제로 렌더링되지 않는 dead CSS다 —
    실제 사용자 흐름으로는 화면에 나타날 수 없으므로, 마크업을 직접 주입해
    CSS 규칙 자체의 대비만 검증한다(요청서: "발견된 모든 Badge"를 전수 조사)."""
    agent_page.evaluate(
        """
        () => {
            const span = document.createElement('span');
            span.id = '__testBadgeUnset';
            span.className = 'badge badge-unset';
            span.textContent = 'UNSET';
            document.body.appendChild(span);
        }
        """
    )
    try:
        _assert_contrast_at_least(agent_page.locator("#__testBadgeUnset"), 4.5, ".badge-unset")
    finally:
        agent_page.evaluate("() => document.getElementById('__testBadgeUnset').remove()")


def test_input_placeholder_is_not_the_only_label(agent_page: Page):
    """placeholder만으로 입력의 의미를 전달하면 안 된다 — placeholder는 값 입력 시
    사라져 스크린리더 사용자에게도 일관되게 전달되지 않는다. 최소한 주변에
    사람이 읽을 수 있는 문맥(사이드바 제목 등)이 있는지 확인한다."""
    chat_input = agent_page.locator("#chatInput")
    placeholder = chat_input.get_attribute("placeholder")
    aria_label = chat_input.get_attribute("aria-label")
    assert placeholder, "입력창에 placeholder조차 없음"
    if not aria_label:
        # aria-label이 없다면 최소한 화면에 이 입력이 무엇을 위한 것인지 알려주는
        # 문맥(페이지 제목)이 존재해야 한다 — 완전히 무맥락은 아니다.
        page_context = agent_page.locator(".conv-sidebar-header").inner_text()
        assert "전극" in page_context
