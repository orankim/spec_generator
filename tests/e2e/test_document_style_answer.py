"""
대화창 UI 재디자인 — 답변이 카드 여러 개로 분절되지 않고 하나의 문서형 구조로
렌더링되는지 확인한다. 사이드바는 이번 작업 대상이 아니므로 여기서 다루지 않는다
(사이드바 무변경 여부는 tests/e2e/test_mobile_drawer.py 등 기존 테스트가 계속
지킨다 — 이 파일은 그 테스트들을 건드리지 않는다).

핵심 변경 배경: 예전에는 "확인된/미충족/확인 필요 요약"(EquipmentCard)과
"항목별 상세 비교"(별도 comparison_result 카드)가 두 개의 카드로 나뉘어 있었다.
지금은 하나의 카드 안에서 요약 다음에 표(table.hard-req-list)가 바로 이어진다 —
데이터(PASS/FAIL/UNKNOWN 판정)는 그대로이고 표시 형태만 문서형으로 바뀌었다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _send(page: Page, mock_api, scenario: str = "pass"):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response(scenario))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


# ---------------------------------------------------------------
# Test 1 — 답변이 문서형 구조로 렌더링되는지: 요약 + 상세 비교표가 같은 카드
# 안에서 소제목(doc-subheading)으로 구분되고, 예전처럼 별도 "사용자 요구조건
# 검증" 카드가 더는 생기지 않는다.
# ---------------------------------------------------------------
def test_answer_renders_as_single_document_not_split_cards(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")

    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    expect(equipment_card).to_be_visible()

    # 항목별 상세 비교가 이 카드 "안에" table로 존재한다(예전의 <ul class="hard-req-list">
    # 별도 카드가 아니라).
    table = equipment_card.locator("table.hard-req-list")
    expect(table).to_be_visible()
    expect(table.locator("thead th")).to_have_count(4)
    header_texts = table.locator("thead th").all_inner_texts()
    assert header_texts == ["조건", "요구사항", "장비 사양", "결과"]

    # 소제목(doc-subheading)으로 섹션이 구분된다.
    subheadings = equipment_card.locator(".doc-subheading").all_inner_texts()
    assert "필수 조건 비교" in subheadings

    # 예전에 존재했던 별도의 "사용자 요구조건 검증 (필수 조건)" 카드 헤더는 더 이상
    # 생성되지 않는다(같은 정보가 이제 위 표로 통합됨).
    full_text = agent_page.locator("#messages").inner_text()
    assert "사용자 요구조건 검증" not in full_text


def test_hard_requirement_table_shows_requirement_and_spec_columns(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    rows = equipment_card.locator("table.hard-req-list tbody tr")
    assert rows.count() > 0
    # Accuracy 행: 요구 "1.0 um 이하", 장비 사양 "0.8 um"이 각각 별도 열에 보여야 한다.
    accuracy_row = equipment_card.locator("table.hard-req-list tbody tr", has_text="Accuracy")
    expect(accuracy_row).to_be_visible()
    row_text = accuracy_row.inner_text()
    assert "0.8" in row_text  # 장비 사양(equipment_spec_display 대신 재구성한 값)
    assert "1" in row_text  # 요구사항(fixtures.make_hard_requirement_report의 requirement=1.0)


# ---------------------------------------------------------------
# Test 2/3 — 근거 자료 기본 접힘 + 펼치기(기존 UX 유지 확인, 문서형 레이아웃에서도).
# ---------------------------------------------------------------
def test_evidence_still_collapsed_by_default_in_document_layout(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    sources = equipment_card.locator("details.sources-block")
    expect(sources).to_be_visible()
    assert sources.get_attribute("open") is None
    sources.locator("summary").click()
    assert sources.get_attribute("open") is not None


# ---------------------------------------------------------------
# Test 4 — UNKNOWN 항목이 대량 노출되지 않는지(기존 UX 유지).
# ---------------------------------------------------------------
def test_unknown_fields_stay_collapsed_in_document_layout(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "unknown")
    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    unknown_detail = equipment_card.locator("details.unknown-specs-detail")
    expect(unknown_detail).to_be_visible()
    assert unknown_detail.get_attribute("open") is None


# Test 5(로딩 표시 유지)는 tests/e2e/test_ui_loading_state.py가 이미 전담해서
# 검증한다 — 이 문서형 레이아웃 작업이 로딩 상태 로직 자체를 건드리지 않았으므로
# 여기서 다시 만들지 않는다(중복 방지). 회귀 여부는 그 파일을 그대로 실행해 확인.

# ---------------------------------------------------------------
# 실제 화면 스크린샷(요청서 22절: "코드만 보고 완료하지 말고 실제 화면을 확인").
# 자동 assert는 없다 — 사람이 눈으로 확인할 산출물이다.
# ---------------------------------------------------------------
def test_screenshot_document_style_answer(agent_page: Page, mock_api, tmp_path):
    _send(agent_page, mock_api, "pass")
    agent_page.screenshot(path=str(tmp_path / "document_style_answer.png"), full_page=True)
    import shutil

    shutil.copy(str(tmp_path / "document_style_answer.png"), "e2e_document_style_answer.png")
