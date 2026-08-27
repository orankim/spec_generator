"""
요청서 3절 섹션 8 — 추가 질문 제안 / Related Questions.

main.py의 buildRelatedQuestions()는 LLM을 다시 호출하지 않고 hard_requirement_report의
UNKNOWN 항목 + 고정 문구 2개로 결정론적으로 만든다(최대 3개). wireCardActions()가
".related-item" 클릭 시 handleUserMessage(질문 텍스트)를 바로 호출하도록 연결한다.
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


def test_related_questions_are_shown_after_search(agent_page: Page, mock_api):
    _send(agent_page, mock_api, "pass")
    related = agent_page.locator(".related-item")
    assert related.count() > 0
    expect(agent_page.locator(".related-title")).to_have_text("추가 질문 제안")


def test_unknown_items_produce_specific_followup_question(agent_page: Page, mock_api):
    """UNKNOWN 항목이 있으면 그 항목을 확인하는 질문이 제안 목록에 포함되어야 한다."""
    _send(agent_page, mock_api, "unknown")
    related_texts = agent_page.locator(".related-item").all_inner_texts()
    assert any("Accuracy" in t and "확인" in t for t in related_texts), (
        f"UNKNOWN 항목(Accuracy)에 대한 확인 질문이 제안되지 않음: {related_texts}"
    )


def test_clicking_related_question_sends_it_and_keeps_context(agent_page: Page, mock_api):
    """추가 질문 클릭은 dead UI가 아니라 실제로 대화창에 전송되어야 하고, 기존
    Context(currentRequirement)를 그대로 유지해 후속 취급(update-requirement)되어야
    한다."""
    _send(agent_page, mock_api, "pass")
    # .first는 "이유를 설명해주세요" 질문 — main.py의 isExplanationQuery() 정규식(왜|이유|
    # 설명해|근거가|어째서)에 걸려 API 호출 없이 로컬에서 바로 답한다(의도된 동작).
    # 이 테스트는 "실제 API를 호출하는" 다른 제안 질문을 클릭해야 한다.
    related_btn = agent_page.locator(".related-item").nth(1)
    question_text = related_btn.inner_text()

    from fixtures import make_requirement, make_update_response

    mock_api.mock(
        "**/api/agent/update-requirement",
        make_update_response(make_requirement(), changed_summary=[]),
    )
    related_btn.click()

    expect(agent_page.locator(".msg-row.user").last).to_contain_text(question_text)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    # dead UI가 아님: 실제로 update-requirement가 호출됐다(새 대화로 오인해
    # analyze-requirement가 다시 불리지 않았다 = context 유지).
    assert mock_api.call_count("**/api/agent/update-requirement") == 1
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 1


def test_clicking_related_question_does_not_duplicate_request_on_double_click(agent_page: Page, mock_api):
    """실제로 겹치는 "빠른 연속 클릭"을 재현하려면 두 클릭 사이에 네트워크 왕복이
    끼어들면 안 된다 — Python 쪽에서 여러 번 .click()을 호출하면 그 사이에 mock
    응답이 이미 완료되어 다음 클릭이 (겹치는 클릭이 아니라) 새로 나타난 다음 질문
    제안에 대한 정당한 클릭이 되어버릴 수 있다. 그래서 브라우저 안에서 순수 동기
    JS로 여러 번 .click()을 연달아 호출한다 — handleUserMessage()가 async여도 첫
    번째 await 이전(가드 플래그 설정 포함)까지는 동기 실행되므로, 같은 동기 스크립트
    안에서 곧바로 이어지는 클릭들은 네트워크 지연 여부와 무관하게 진짜로 겹친다."""
    _send(agent_page, mock_api, "pass")
    from fixtures import make_requirement, make_update_response

    mock_api.mock(
        "**/api/agent/update-requirement",
        make_update_response(make_requirement(), changed_summary=[]),
    )
    agent_page.evaluate(
        """
        () => {
            const btn = () => document.querySelectorAll('.related-item')[1];
            for (let i = 0; i < 4; i++) {
                const el = btn();
                if (el) el.click();
            }
        }
        """
    )
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)
    assert mock_api.call_count("**/api/agent/update-requirement") == 1, (
        "추가 질문 제안을 짧은 시간 안에 여러 번 클릭하면 동일 질문이 중복 전송됨"
    )
