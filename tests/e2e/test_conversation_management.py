"""
UX 개선 — 신규 대화 예시 질문 placeholder(2절) + 대화 관리(⋯) 메뉴 열기/닫기(4절).

main.py의 관련 구현:
- NEW_CONVERSATION_PLACEHOLDER/DEFAULT_CHAT_PLACEHOLDER + renderAll()의
  messages.length === 0 분기가 #chatInput의 placeholder를 전환한다.
- renderConvItemRow()/renderConvList()가 각 대화 항목을 ".conv-item-row"로
  그리고, "⋯"(.conv-item-menu-btn) 클릭 시 ".conv-item-dropdown"(이름 변경/
  삭제)을 띄운다.

이름 변경/삭제 자체의 상세 동작은 tests/e2e/test_conversation_rename.py /
tests/e2e/test_conversation_delete.py에서 각각 다룬다(파일을 나눈 이유: 처음에
하나의 파일에 20개 이상을 몰아넣었더니 이 환경에서 순차 실행 시 뒤쪽 테스트가
간헐적으로 timeout — 기존 프로젝트 관례대로 관심사별 작은 파일로 나눈다).
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."
NEW_CONVERSATION_PLACEHOLDER_SNIPPET = "Inline으로 검사하고"


def _send(page: Page, text: str = QUESTION):
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _seed_conversations(page: Page, conversations: list):
    page.evaluate(
        "(data) => sessionStorage.setItem(data.key, JSON.stringify(data.conversations))",
        {"key": "electrode_ai_conversations_v1", "conversations": conversations},
    )
    page.reload()
    page.wait_for_selector("#chatInput")


def _conv(conv_id: str, title: str, updated_offset_ms: int = 0):
    now_ms = 1_800_000_000_000  # 고정 타임스탬프(테스트 간 결정론적 정렬)
    ts = now_ms - updated_offset_ms
    return {
        "id": conv_id,
        "title": title,
        "createdAt": ts,
        "updatedAt": ts,
        "messages": [{"id": conv_id + "-m1", "role": "user", "type": "text", "content": {"text": title}, "timestamp": ts}],
        "currentRequirement": None,
        "currentCandidates": None,
        "lastSearchResult": None,
    }


# ---------------------------------------------------------------
# 신규 대화 첫 화면 예시 질문 placeholder
# ---------------------------------------------------------------
def test_new_empty_conversation_shows_example_question_as_placeholder(agent_page: Page):
    chat_input = agent_page.locator("#chatInput")
    placeholder = chat_input.get_attribute("placeholder")
    assert NEW_CONVERSATION_PLACEHOLDER_SNIPPET in placeholder, f"신규 대화 예시 질문 placeholder가 아님: {placeholder!r}"
    assert chat_input.input_value() == "", "placeholder가 실제 입력값(value)으로 들어가 있음"


def test_example_placeholder_is_not_sent_as_message_on_empty_submit(agent_page: Page, mock_api):
    agent_page.click("#sendBtn")
    agent_page.wait_for_timeout(300)
    assert agent_page.locator(".msg-row.user").count() == 0, "placeholder 문구가 그대로 메시지로 전송됨"
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 0


def test_example_placeholder_disappears_once_user_types(agent_page: Page):
    chat_input = agent_page.locator("#chatInput")
    chat_input.type("실제 입력 중")
    assert chat_input.input_value() == "실제 입력 중"


def test_loaded_conversation_does_not_show_new_conversation_placeholder(agent_page: Page, mock_api):
    """기존 대화를 불러왔을 때(메시지가 1개 이상) placeholder는 원래 안내
    문구로 돌아가야 하고, 그 대화의 내역/상태에는 영향을 주지 않아야 한다."""
    _send(agent_page)
    placeholder = agent_page.locator("#chatInput").get_attribute("placeholder")
    assert NEW_CONVERSATION_PLACEHOLDER_SNIPPET not in placeholder
    assert QUESTION in agent_page.locator("#messages").inner_text()


def test_new_chat_button_restores_example_placeholder(agent_page: Page, mock_api):
    _send(agent_page)
    agent_page.click("#newChatBtn")
    placeholder = agent_page.locator("#chatInput").get_attribute("placeholder")
    assert NEW_CONVERSATION_PLACEHOLDER_SNIPPET in placeholder


# ---------------------------------------------------------------
# 대화 관리(⋯) 메뉴 — 열기/닫기
# ---------------------------------------------------------------
def test_menu_button_opens_dropdown_with_rename_and_delete(agent_page: Page, mock_api):
    _send(agent_page)
    agent_page.click(".conv-item-menu-btn")
    dropdown = agent_page.locator(".conv-item-dropdown")
    expect(dropdown).to_be_visible()
    expect(agent_page.locator(".conv-menu-rename")).to_contain_text("이름 변경")
    expect(agent_page.locator(".conv-menu-delete")).to_contain_text("대화 삭제")


def test_menu_closes_on_outside_click(agent_page: Page, mock_api):
    _send(agent_page)
    agent_page.click(".conv-item-menu-btn")
    expect(agent_page.locator(".conv-item-dropdown")).to_be_visible()
    agent_page.click("#messages")
    assert agent_page.locator(".conv-item-dropdown").count() == 0


def test_menu_closes_on_escape(agent_page: Page, mock_api):
    _send(agent_page)
    agent_page.click(".conv-item-menu-btn")
    expect(agent_page.locator(".conv-item-dropdown")).to_be_visible()
    agent_page.keyboard.press("Escape")
    assert agent_page.locator(".conv-item-dropdown").count() == 0


def test_only_one_conversation_menu_open_at_a_time(agent_page: Page):
    """state.convMenuOpenId는 값 하나만 가질 수 있으므로 두 메뉴가 동시에 열리는
    것은 애초에 불가능하다 — 다만 열려있는 드롭다운이 바로 아래 행의 "⋯" 버튼을
    시각적으로 덮을 수 있으므로(다른 많은 채팅 UI의 드롭다운과 동일한 흔한
    동작), 실제 사용자처럼 먼저 바깥을 클릭해 A의 메뉴를 닫은 뒤 B의 메뉴를
    연다."""
    conversations = [_conv("c-a", "대화 A", updated_offset_ms=1000), _conv("c-b", "대화 B", updated_offset_ms=2000)]
    _seed_conversations(agent_page, conversations)
    assert agent_page.locator(".conv-item-row").count() == 2

    menu_btns = agent_page.locator(".conv-item-menu-btn")
    menu_btns.nth(0).click()
    expect(agent_page.locator(".conv-item-dropdown")).to_have_count(1)

    agent_page.keyboard.press("Escape")
    assert agent_page.locator(".conv-item-dropdown").count() == 0

    menu_btns.nth(1).click()
    assert agent_page.locator(".conv-item-dropdown").count() == 1, "두 번째 메뉴를 열었는데 이전 메뉴가 함께 열려있음"
