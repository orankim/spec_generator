"""
요청서 3절 섹션 5 — "새로운 대화 시작" 기능.

main.py의 newChatBtn 핸들러는 state.activeConversationId를 null로 되돌릴 뿐,
실제 Conversation 레코드는 getOrCreateActiveConversation()이 첫 메시지 전송
시점에 새로 만든다(agent_page.py 주석 참고) — 그래서 "새 대화 시작"을 누른 직후에는
빈 홈 화면이 보여야 하고, 새 메시지를 보내야 비로소 새 레코드가 생긴다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

FIRST_QUESTION = "두께 검사기 찾아줘."
SECOND_QUESTION = "표면 결함 검사기 찾아줘."


def _send(page: Page, text: str):
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def test_new_chat_button_resets_to_empty_home_screen(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, FIRST_QUESTION)
    assert agent_page.locator(".conv-item").count() == 1

    agent_page.click("#newChatBtn")
    expect(agent_page.locator(".welcome-block")).to_be_visible()
    assert agent_page.locator(".msg-row").count() == 0, "새 대화 시작 후에도 이전 메시지가 화면에 남아있음"
    # 이전 대화는 사이드바 목록에서 사라지지 않아야 한다(삭제가 아니라 "새로 시작"이므로).
    assert agent_page.locator(".conv-item").count() == 1


def test_new_conversation_does_not_mix_previous_messages_and_can_receive_new_question(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, FIRST_QUESTION)
    first_conv_message_count = agent_page.locator(".msg-row").count()
    assert first_conv_message_count > 0

    agent_page.click("#newChatBtn")
    _send(agent_page, SECOND_QUESTION)

    # 새 대화 메시지 목록에 첫 대화 내용(예: FIRST_QUESTION)이 섞여 있으면 안 된다.
    full_text = agent_page.locator("#messages").inner_text()
    assert FIRST_QUESTION not in full_text
    assert SECOND_QUESTION in full_text
    # 새 대화가 사이드바에 별도 항목으로 추가되어야 한다(총 2개).
    assert agent_page.locator(".conv-item").count() == 2


def test_new_conversation_does_not_retain_previous_requirement_context(agent_page: Page, mock_api):
    """새 대화에서는 이전 대화의 currentRequirement가 이어지지 않아야 한다 — 이어졌다면
    후속 메시지 취급(update-requirement)될 것이고, 새 대화 취급이면 analyze-requirement가
    다시 호출되어야 한다."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, FIRST_QUESTION)

    agent_page.click("#newChatBtn")
    _send(agent_page, SECOND_QUESTION)

    assert mock_api.call_count("**/api/agent/analyze-requirement") == 2, (
        "새 대화의 첫 메시지가 이전 대화의 currentRequirement를 이어받아 "
        "update-requirement(후속 취급)로 잘못 보내짐"
    )
    assert mock_api.call_count("**/api/agent/update-requirement") == 0


def test_can_switch_back_to_previous_conversation_from_sidebar(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, FIRST_QUESTION)

    agent_page.click("#newChatBtn")
    _send(agent_page, SECOND_QUESTION)

    # 사이드바에서 첫 번째 대화로 되돌아간다.
    conv_items = agent_page.locator(".conv-item")
    assert conv_items.count() == 2
    # 두 번째(오래된) 항목이 첫 대화 — 목록은 최신순 정렬이므로 마지막 항목을 클릭.
    conv_items.last.click()

    full_text = agent_page.locator("#messages").inner_text()
    assert FIRST_QUESTION in full_text
    assert SECOND_QUESTION not in full_text
