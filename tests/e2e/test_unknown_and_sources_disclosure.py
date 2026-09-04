"""
UX 개선 C — "확인되지 않은 사양" 접이식 목록, UX 개선 D — 근거 자료 접이식 UI.

배경: 사양서 결과 화면에 UNKNOWN 항목이 너무 많이 나열되면 "AI가 아는 정보가
별로 없다"는 인상을 준다(실제로는 "현재 근거 문서에 그 사양이 없다"는 뜻일 뿐).
main.py의 EquipmentCard는 값이 있는 항목만 기본으로 보여주고, 값이 없는(UNKNOWN)
수치 항목은 "확인되지 않은 사양 N개 보기"라는 <details>로 접어 필요할 때만
펼쳐보게 한다 — 데이터 자체(어떤 항목이 UNKNOWN인지)는 지우지 않는다.

근거 자료도 마찬가지로 "SPEC-013.md" 같은 파일명 목록을 항상 펼쳐 보여주는 대신
기본은 접고("근거 자료 N개 보기"), 실제로 채택된 후보의 문서에는 장비명을 함께
보여준다(Equipment-centric). 근거 데이터(source_document/evidence) 자체는
삭제/변형하지 않는다.

Ollama 없이도 실행 가능하다(mock_api로 /api/agent/* 응답을 가로챈다 — Level 1).
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _send(page: Page, mock_api, scenario: str):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response(scenario))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _equipment_card(page: Page):
    return page.locator(".card").filter(has=page.locator(".confirm-block, .banner-pass, .banner-unknown, .banner-fail")).first


# ---------------------------------------------------------------
# Test 5 — UNKNOWN 기본 숨김
# ---------------------------------------------------------------
def test_unknown_specs_hidden_by_default_visible_values_shown(agent_page: Page, mock_api):
    """make_specification()은 정확도/측정범위/대응폭만 값을 채우고, 분해능/최소
    검출 결함 크기/검사 속도는 값을 채우지 않는다(SourcedNumber 기본값=UNKNOWN) —
    기본 화면에는 값이 있는 항목만 보이고, UNKNOWN 항목은 <details>가 닫힌 채로
    존재해야 한다(완전히 삭제되면 안 됨)."""
    _send(agent_page, mock_api, "pass")
    card = _equipment_card(agent_page)

    # 값이 있는 항목은 기본으로 보인다.
    visible_labels = card.locator(".card-row .label").all_inner_texts()
    assert "정확도" in visible_labels
    assert "측정 범위" in visible_labels

    # 값이 없는 항목(분해능 등)은 기본 화면(.card-row)에는 없다.
    assert "분해능" not in visible_labels
    assert "검사 속도" not in visible_labels

    # 그러나 완전히 사라진 게 아니라 접힌 <details> 뒤에 존재해야 한다.
    detail = card.locator(".unknown-specs-detail")
    expect(detail).to_be_attached()
    assert detail.get_attribute("open") is None, "확인되지 않은 사양 목록이 기본적으로 펼쳐져 있음"

    summary_text = detail.locator("summary").inner_text()
    assert "확인되지 않은 사양" in summary_text
    assert "UNKNOWN" not in summary_text, "시스템 용어 UNKNOWN이 그대로 노출됨"


# ---------------------------------------------------------------
# Test 6 — UNKNOWN 펼치기
# ---------------------------------------------------------------
def test_unknown_specs_expand_on_click_reveals_hidden_items_without_deleting_data(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "unknown")  # accuracy도 UNKNOWN으로 추가됨
    card = _equipment_card(agent_page)
    detail = card.locator(".unknown-specs-detail")

    summary = detail.locator("summary")
    count_text = summary.inner_text()
    assert "정확도" not in card.locator(".card-row .label").all_inner_texts(), (
        "정확도가 UNKNOWN인데 기본 화면(.card-row)에 노출됨"
    )

    summary.click()
    expect(detail).to_have_attribute("open", "")

    revealed_labels = detail.locator(".unknown-spec-row .label").all_inner_texts()
    assert "정확도" in revealed_labels, "펼친 뒤에도 UNKNOWN이었던 정확도 항목이 보이지 않음"
    revealed_text = detail.inner_text()
    assert "사양서에 정보 없음" in revealed_text
    assert "UNKNOWN" not in revealed_text, "펼친 뒤에도 시스템 용어 UNKNOWN이 그대로 노출됨"

    # 다시 클릭하면 접힌다(토글 가능).
    summary.click()
    assert detail.get_attribute("open") is None


# ---------------------------------------------------------------
# Test 7 — 근거 자료 접기/펼치기
# ---------------------------------------------------------------
def test_sources_block_collapsed_by_default_and_toggles_on_click(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    card = _equipment_card(agent_page)
    sources = card.locator(".sources-block")
    expect(sources).to_be_attached()
    assert sources.get_attribute("open") is None, "근거 자료가 기본적으로 펼쳐져 있음(화면이 복잡해짐)"

    summary = sources.locator("summary.sources-title")
    expect(summary).to_contain_text("근거 자료")
    expect(summary).to_contain_text("보기")

    summary.click()
    expect(sources).to_have_attribute("open", "")
    expect(sources.locator(".sources-list")).to_be_visible()

    summary.click()
    assert sources.get_attribute("open") is None


# ---------------------------------------------------------------
# Test 8 — 근거 데이터 보존(equipment-centric 표시로 바뀌어도 원본 데이터 유지)
# ---------------------------------------------------------------
def test_sources_block_shows_equipment_name_but_preserves_source_document(agent_page: Page, mock_api):
    """make_candidate()의 기본값(manufacturer=ThicknessPro, model=TP-800,
    source_document=SPEC-013.md)과 make_specification()의 equipment.name
    (ThicknessPro TP-800)이 같은 문서를 가리키므로, 펼쳤을 때 장비명과 원본 파일명
    (SPEC-013.md)이 함께 보여야 한다 — 파일명만 나열하던 예전 방식을 장비 중심으로
    바꾸되, 근거 문서 자체(source_document)는 지우지 않는다."""
    _send(agent_page, mock_api, "pass")
    card = _equipment_card(agent_page)
    sources = card.locator(".sources-block")
    sources.locator("summary.sources-title").click()

    sources_text = sources.inner_text()
    assert "SPEC-013.md" in sources_text, "근거 문서 파일명(source_document)이 사라짐"
    assert "ThicknessPro TP-800" in sources_text, "장비 중심 표시(equipment name)가 보이지 않음"

    equipment_line = sources.locator(".source-equipment").first
    expect(equipment_line).to_contain_text("ThicknessPro TP-800")


def test_no_candidate_falls_back_to_document_only_without_fabricating_equipment(agent_page: Page, mock_api):
    """chosen_candidate가 없으면(예: 후보 없음) 장비명을 지어내지 않고 파일명만
    보여준다 — 근거 없는 정보를 새로 만들지 않는다는 원칙 확인."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock(
        "**/api/agent/generate-spec",
        make_generate_spec_response("pass", include_candidate=False),
    )
    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)

    card = _equipment_card(agent_page)
    sources = card.locator(".sources-block")
    sources.locator("summary.sources-title").click()
    assert sources.locator(".source-equipment").count() == 0, "근거 없는 장비명을 지어내 표시함"
    assert "SPEC-013.md" in sources.inner_text()
