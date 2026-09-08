"""
견적 통합 개선 — 추천 장비 카드(EquipmentCard) 안에 인라인으로 표시되는
"예상 견적" 블록(main.py renderQuoteSummaryBlock)의 e2e 검증.

이전에는 quote_analyses가 있어도(사용자가 견적 키워드를 쓴 경우에만) 답변 맨
아래에 별도의 "견적 분석" 카드로 뜬금없이 나타났다. 지금은 backend가 견적
키워드 유무와 무관하게 quote_analyses를 채워 보내고, 프론트엔드는 그 값을
추천 장비 자신의 EquipmentCard 안에서 바로 이어서 보여준다 — "이 견적이 어떤
장비의 것인지"가 항상 명확해야 한다(요청서 7-1절).

가격 Hallucination 방어 확인: 연결된 QUOTE가 없으면 화면 어디에도 금액(₩)이
나타나지 않고, "없음"을 명시하는 문구만 보여야 한다(요청서 9/10단계).
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response, make_quote_analysis

QUESTION = "두께 검사기 찾아줘."


def _send(page: Page, mock_api, generate_spec_response: dict):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", generate_spec_response)
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def test_quote_summary_shown_inside_equipment_card_with_expandable_detail(agent_page: Page, mock_api):
    quote_analysis = make_quote_analysis(
        source_file="QUOTE-013.md", equipment_amount=100_000_000.0, options_amount=20_000_000.0,
        vat_amount=12_000_000.0, grand_total=132_000_000.0,
    )
    response = make_generate_spec_response(quote_analyses={"SPEC-013.md": [quote_analysis]})
    _send(agent_page, mock_api, response)

    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    quote_block = equipment_card.locator(".quote-summary-block")
    expect(quote_block).to_be_visible()
    expect(quote_block).to_contain_text("예상 견적")
    expect(quote_block).to_contain_text("132,000,000")

    # 기본 화면에서는 견적 구성 세부 항목(옵션/부가세 등)이 아직 보이지 않아야
    # 한다(요청서 7-2절: 기본은 총액만, 상세는 펼쳐야 보임).
    assert "옵션" not in quote_block.inner_text()

    quote_block.locator("details.quote-detail-toggle summary").click()
    expect(quote_block.locator(".quote-detail-row", has_text="옵션")).to_be_visible()
    expect(quote_block.locator(".quote-detail-row", has_text="옵션")).to_contain_text("20,000,000")
    expect(quote_block.locator(".quote-detail-row", has_text="합계")).to_contain_text("132,000,000")

    # 견적 근거(출처 파일명)도 접이식으로 확인 가능해야 한다(기존 근거자료 UX와 통일).
    quote_block.locator("details.sources-block summary").click()
    expect(quote_block).to_contain_text("QUOTE-013.md")


def test_no_linked_quote_shows_no_data_message_without_fabricating_price(agent_page: Page, mock_api):
    response = make_generate_spec_response()  # quote_analyses 기본값 {} — 연결된 견적 없음.
    _send(agent_page, mock_api, response)

    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    quote_block = equipment_card.locator(".quote-summary-block")
    expect(quote_block).to_be_visible()
    expect(quote_block).to_contain_text("현재 저장된 견적 자료가 없어")

    # 어디에도 금액이 지어내어 표시되면 안 된다.
    assert "₩" not in quote_block.inner_text()


def test_multiple_quotes_for_same_equipment_are_each_shown_not_merged(agent_page: Page, mock_api):
    """Case H(옵션 포함/대안 견적) 같은 동일 장비 복수 견적 — 하나로 뭉개지 않고
    각각 구조적으로 구분해서 보여준다(요청서 6-2절)."""
    primary = make_quote_analysis(source_file="QUOTE-013.md", grand_total=100_000_000.0)
    alternate = make_quote_analysis(source_file="QUOTE-013-B.md", grand_total=150_000_000.0)
    response = make_generate_spec_response(quote_analyses={"SPEC-013.md": [primary, alternate]})
    _send(agent_page, mock_api, response)

    equipment_card = agent_page.locator(".card").filter(has_text="추천").first
    quote_block = equipment_card.locator(".quote-summary-block")
    full_text = quote_block.inner_text()
    assert "100,000,000" in full_text
    assert "150,000,000" in full_text
    assert "기본 견적" in full_text
    assert "대안 견적" in full_text
