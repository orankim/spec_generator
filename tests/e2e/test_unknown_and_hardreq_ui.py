"""
요청서 3절 섹션 9~11 — UNKNOWN/미정 UI, Hard Requirement PASS/FAIL/UNKNOWN 배지,
추천 결과와 Hard Requirement 일관성.

핵심 회귀 대상(요청서에서 명시한 나쁜 예): "0 ~ 300 μmVERIFIED"처럼 값과 상태
텍스트가 붙어 보이는 문제, 그리고 "UNKNOWN이 있는데 모든 조건 충족 문구가 뜨는"
논리적 모순. main.py의 fmtSourcedCell/fmtSourcedRangeCell은 값을 <span
class="value">와 상태를 <span class="badge">로 별도 DOM 노드에 담고, equipment
Banner()는 hasFail/hasUnknown/hasRecords 우선순위로 배너 문구를 딱 하나만
고른다 — 이 테스트는 그 결과가 실제 DOM에서도 값/배지가 분리돼 있고, 모순 조합이
없는지 확인한다.
"""
import re

from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."

FORBIDDEN_COMBINED_PATTERNS = [
    re.compile(r"\d\s*(um|μm|mm)\s*(VERIFIED|UNKNOWN|INFERRED|USER_DEFINED)"),
]


def _send(page: Page, mock_api, scenario: str):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response(scenario))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


# ---------------------------------------------------------------
# 섹션 9 — UNKNOWN/미정 UI
# ---------------------------------------------------------------
def test_value_and_status_badge_are_visually_separated_not_concatenated(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    equipment_card = agent_page.locator(".card").filter(has=agent_page.locator(".confirm-block, .banner-pass")).first

    # 값 span과 배지 span이 서로 다른 DOM 노드여야 한다(요청서의 나쁜 예:
    # "0 ~ 300 μmVERIFIED"처럼 하나의 텍스트로 붙어 보이면 안 된다).
    value_spans = equipment_card.locator(".card-row .value")
    badge_spans = equipment_card.locator(".card-row .badge")
    assert value_spans.count() > 0
    assert badge_spans.count() > 0

    for i in range(value_spans.count()):
        value_text = value_spans.nth(i).inner_text()
        assert not any(p.search(value_text) for p in FORBIDDEN_COMBINED_PATTERNS), (
            f"값과 상태 배지가 한 텍스트 노드에 붙어서 렌더링됨: {value_text!r}"
        )
        for status_word in ("VERIFIED", "UNKNOWN", "INFERRED", "USER_DEFINED"):
            assert status_word not in value_text, f"값 셀 안에 상태 텍스트가 섞여 있음: {value_text!r}"


def test_unknown_fields_are_hidden_in_equipment_card_but_explicit_in_hard_requirement(agent_page: Page, mock_api):
    """일반 EquipmentCard 항목은 근거 없는 값을 "미정"으로 채우지 않고 행 자체를
    숨긴다(화면이 UNKNOWN 투성이로 길어지지 않음) — 반면 Hard Requirement 비교
    영역은 항상 PASS/FAIL/UNKNOWN을 명시적으로 보여줘야 한다."""
    _send(agent_page, mock_api, "unknown")
    full_text = agent_page.locator("#messages").inner_text()

    # Hard Requirement 비교 영역에는 UNKNOWN이 명시적으로 있어야 한다.
    comparison_card = agent_page.locator(".hard-req-list")
    expect(comparison_card).to_be_visible()
    assert "UNKNOWN" in comparison_card.inner_text()

    # 일반 EquipmentCard 쪽에는 "정확도" 행 자체가 UNKNOWN 값으로 채워져 길게
    # 나열되지 않아야 한다(fmtSourcedCell이 value=None이면 행을 숨김).
    equipment_card_body = agent_page.locator(".card").filter(has_text="추천").first.locator(".card-body")
    row_labels = equipment_card_body.locator(".card-row .label").all_inner_texts()
    assert "정확도" not in row_labels, "값이 없는 일반 항목이 '미정'/빈 값으로 채워져 화면에 나열됨"


# ---------------------------------------------------------------
# 섹션 10 — Hard Requirement PASS/FAIL/UNKNOWN 배지
# ---------------------------------------------------------------
def test_pass_badge_shown_with_green_success_class(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    pass_badges = agent_page.locator(".hard-req-list .badge-pass")
    assert pass_badges.count() > 0
    for i in range(pass_badges.count()):
        expect(pass_badges.nth(i)).to_have_text("PASS")


def test_fail_badge_is_visually_distinct_from_pass(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "fail")
    fail_badges = agent_page.locator(".hard-req-list .badge-fail")
    assert fail_badges.count() > 0
    for i in range(fail_badges.count()):
        expect(fail_badges.nth(i)).to_have_text("FAIL")
    # FAIL 항목에는 "왜 실패했는지" 확인 가능한 이유 텍스트가 함께 있어야 한다.
    reason_texts = agent_page.locator(".hard-req-list li .reason").all_inner_texts()
    assert all(len(r.strip()) > 5 for r in reason_texts), f"실패 이유 텍스트가 비어있거나 너무 짧음: {reason_texts}"


def test_unknown_result_never_rendered_as_pass_badge(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "unknown")
    hard_req_items = agent_page.locator(".hard-req-list li")
    count = hard_req_items.count()
    found_unknown = False
    for i in range(count):
        item = hard_req_items.nth(i)
        text = item.inner_text()
        if "Accuracy" in text:
            assert "UNKNOWN" in text
            assert item.locator(".badge-pass").count() == 0, "UNKNOWN 항목이 PASS 배지로 잘못 렌더링됨"
            found_unknown = True
    assert found_unknown, "테스트 전제(Accuracy=UNKNOWN)가 화면에 반영되지 않음"

    # "모든 조건 충족" 같은 단정적 문구가 있으면 안 된다.
    full_text = agent_page.locator("#messages").inner_text()
    assert "모두 충족" not in full_text
    assert "확인 필요" in full_text


# ---------------------------------------------------------------
# 섹션 11 — 추천 결과와 Hard Requirement 일관성(모순 자동 탐지)
# ---------------------------------------------------------------
def test_all_pass_shows_all_conditions_met_banner(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    banner = agent_page.locator(".banner-pass")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("모두 충족")
    assert agent_page.locator(".banner-fail, .banner-unknown").count() == 0


def test_fail_present_never_claims_all_conditions_met(agent_page: Page, mock_api):
    """FAIL이 있으면 절대로 '모든 조건 충족' 계열 배너가 함께 뜨면 안 된다(모순 탐지)."""
    _send(agent_page, mock_api, "fail")
    full_text = agent_page.locator("#messages").inner_text()
    assert "모두 충족" not in full_text, "FAIL 항목이 있는데도 '모든 조건 충족' 문구가 함께 표시됨(논리적 모순)"
    banner = agent_page.locator(".banner-fail")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("찾지 못했습니다")


def test_unknown_without_fail_shows_partial_confirmation_needed_not_pass(agent_page: Page, mock_api):
    """FAIL 없음 + UNKNOWN 존재 → '일부 조건 확인 필요' 배너만 뜨고, PASS/FAIL 배너와
    동시에 뜨지 않아야 한다(모순 탐지)."""
    _send(agent_page, mock_api, "unknown")
    assert agent_page.locator(".banner-pass").count() == 0, "UNKNOWN이 있는데 '모두 충족' PASS 배너가 함께 표시됨"
    assert agent_page.locator(".banner-fail").count() == 0
    banner = agent_page.locator(".banner-unknown")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("확인 필요")

    # 추천 헤더도 "추천 장비"(단정)가 아니라 "추천 후보"로 낮춰 표현해야 한다.
    header_text = agent_page.locator(".card-header").first.inner_text()
    assert "추천 장비" not in header_text, "UNKNOWN이 있는데도 헤더가 '추천 장비'로 단정적으로 표시됨"


def test_only_one_banner_rendered_per_equipment_card(agent_page: Page, mock_api):
    """세 가지 배너(pass/fail/unknown) 중 정확히 하나만 렌더링되어야 한다 — 서로 다른
    결론을 동시에 보여주는 모순 자체를 원천 차단하는 구조인지 확인한다."""
    for scenario in ("pass", "fail", "unknown"):
        mock_api.calls.clear()
        page = agent_page
        page.click("#newChatBtn")
        _send(page, mock_api, scenario)
        banners = page.locator(".banner-pass, .banner-fail, .banner-unknown")
        assert banners.count() == 1, f"[{scenario}] 배너가 0개 또는 여러 개 렌더링됨(모순 가능성): {banners.count()}"
