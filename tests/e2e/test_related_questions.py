"""
'추가 질문 제안' / Related Questions 섹션 제거 회귀 테스트.

이 기능은 원래 main.py의 buildRelatedQuestions()/renderRelatedQuestionsBlock()
(hard_requirement_report의 UNKNOWN 항목 + 고정 문구 2개로 결정론적으로 만든 제안
버튼 목록)이었으나, UX 개선 작업에서 AI 답변 끝의 '추가 질문 제안' 섹션 자체를
완전히 제거하기로 했다. 이 파일은 그 제거가 실제로 적용됐는지(그리고 이후 다시
실수로 부활하지 않는지) 확인한다.

주의: "왜 추천됐는지 설명해달라"는 질문에 답하는 isExplanationQuery()/
buildExplanationMessage() 로직 자체는 이 제거 대상이 아니다 — 사용자가 직접
채팅으로 물어보면 여전히 동작해야 한다(tests/test_conversational_patch.py 등
기존 테스트가 별도로 커버). 이 파일은 오직 "AI 답변에 자동으로 붙는 제안 버튼
UI"가 사라졌는지만 확인한다.
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


def test_related_questions_section_no_longer_rendered_after_search(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    assert agent_page.locator(".related-item").count() == 0, "제거되었어야 할 추가 질문 제안 버튼이 여전히 렌더링됨"
    assert agent_page.locator(".related-block").count() == 0, "제거되었어야 할 추가 질문 제안 블록이 여전히 렌더링됨"
    full_text = agent_page.locator("#messages").inner_text()
    assert "추가 질문 제안" not in full_text


def test_related_questions_section_absent_even_with_unknown_items(agent_page: Page, mock_api):
    """UNKNOWN 항목이 있어 예전이라면 특히 더 많은 제안이 붙었을 시나리오에서도
    섹션 자체가 나타나지 않아야 한다."""
    _send(agent_page, mock_api, "unknown")
    assert agent_page.locator(".related-item").count() == 0
    assert agent_page.locator(".related-block").count() == 0


def test_explanation_chat_query_still_works_without_the_suggestion_buttons(agent_page: Page, mock_api):
    """제안 버튼 UI는 사라졌지만, 사용자가 채팅으로 직접 "이유를 설명해줘"라고
    물어보는 기능(main.py의 isExplanationQuery/buildExplanationMessage)은 이번
    제거 대상이 아니므로 그대로 동작해야 한다."""
    _send(agent_page, mock_api, "pass")
    before = agent_page.locator(".msg-row.ai").count()

    agent_page.fill("#chatInput", "이 장비가 추천된 이유가 뭐야?")
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".msg-row.ai")).to_have_count(before + 1, timeout=5000)
    last_ai_text = agent_page.locator(".msg-row.ai").last.inner_text()
    assert len(last_ai_text.strip()) > 0
