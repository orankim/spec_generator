"""
UX 개선 4-2절 — 대화 삭제(Delete).

main.py의 requestDeleteConversation()이 확인 모달(#convDeleteModalRoot >
.modal-box)을 띄우고, confirmDeleteConversation()이 실제로 state.conversations
에서 제거 + sessionStorage 반영을 한다. 지금 보고 있는 대화를 삭제하면 화면이
깨지지 않고 새로운 빈 대화(welcome-block) 화면으로 안전하게 전환되어야 한다.
"""
import json

from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

STORAGE_KEY = "electrode_ai_conversations_v1"
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
        {"key": STORAGE_KEY, "conversations": conversations},
    )
    page.reload()
    page.wait_for_selector("#chatInput")


def _conv(conv_id: str, title: str, updated_offset_ms: int = 0):
    now_ms = 1_800_000_000_000
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


def _stored_conversations(page: Page):
    raw = page.evaluate(f"() => sessionStorage.getItem('{STORAGE_KEY}')")
    return json.loads(raw) if raw else []


def _open_delete(page: Page):
    page.click(".conv-item-menu-btn")
    page.click(".conv-menu-delete")


def test_delete_shows_confirm_modal_with_title(agent_page: Page, mock_api):
    _send(agent_page)
    _open_delete(agent_page)

    modal = agent_page.locator(".modal-box")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text(QUESTION)
    # 삭제 확인 전에는 대화가 그대로 남아있어야 한다.
    assert len(_stored_conversations(agent_page)) == 1


def test_delete_cancel_button_keeps_conversation(agent_page: Page, mock_api):
    _send(agent_page)
    _open_delete(agent_page)
    agent_page.click("#convDeleteCancelBtn")

    assert agent_page.locator(".modal-box").count() == 0
    assert agent_page.locator(".conv-item").count() == 1
    assert len(_stored_conversations(agent_page)) == 1


def test_delete_backdrop_click_cancels(agent_page: Page, mock_api):
    _send(agent_page)
    _open_delete(agent_page)
    # backdrop 자기 자신(모달 바깥의 어두운 영역)을 클릭 — 좌상단 모서리를 지정한다.
    agent_page.locator("#convDeleteBackdrop").click(position={"x": 5, "y": 5})

    assert agent_page.locator(".modal-box").count() == 0
    assert agent_page.locator(".conv-item").count() == 1


def test_delete_confirm_removes_conversation_from_list_and_storage(agent_page: Page, mock_api):
    _send(agent_page)
    _open_delete(agent_page)
    agent_page.click("#convDeleteConfirmBtn")

    assert agent_page.locator(".modal-box").count() == 0
    assert agent_page.locator(".conv-item").count() == 0
    assert _stored_conversations(agent_page) == []


def test_deleting_active_conversation_resets_to_welcome_screen_not_broken(agent_page: Page, mock_api):
    """현재 보고 있는 대화를 삭제하면 404/깨진 화면이 아니라 새로운 빈 대화
    화면(welcome-block)으로 안전하게 전환되어야 한다."""
    _send(agent_page)
    assert QUESTION in agent_page.locator("#messages").inner_text()

    _open_delete(agent_page)
    agent_page.click("#convDeleteConfirmBtn")

    expect(agent_page.locator(".welcome-block")).to_be_visible()
    assert QUESTION not in agent_page.locator("#messages").inner_text(), "삭제된 대화 내용이 메시지 뷰에 잔존함"
    assert agent_page.page_errors == [], f"대화 삭제 후 uncaught exception 발생: {agent_page.page_errors}"
    # 삭제 후에도 정상적으로 새 대화를 시작할 수 있어야 한다(화면이 죽지 않음).
    placeholder = agent_page.locator("#chatInput").get_attribute("placeholder")
    assert NEW_CONVERSATION_PLACEHOLDER_SNIPPET in placeholder


def test_deleting_non_active_conversation_does_not_affect_current_view(agent_page: Page):
    # updated_offset_ms가 작을수록 updatedAt이 "지금"에 더 가깝다(더 최근) —
    # 즉 대화 A(offset=1000)가 대화 B(offset=2000)보다 최근이라 기본 활성
    # 대화가 된다(boot()가 updatedAt 최신순으로 고른다).
    conversations = [_conv("c-a", "대화 A", updated_offset_ms=1000), _conv("c-b", "대화 B", updated_offset_ms=2000)]
    _seed_conversations(agent_page, conversations)
    assert "대화 A" in agent_page.locator("#messages").inner_text()

    rows = agent_page.locator(".conv-item-row")
    # 활성 대화(대화 A)가 아닌 "대화 B" 행을 찾아 그 행의 메뉴만 연다.
    target_row = rows.filter(has_text="대화 B")
    target_row.locator(".conv-item-menu-btn").click()
    agent_page.locator(".conv-item-dropdown .conv-menu-delete").click()
    agent_page.click("#convDeleteConfirmBtn")

    assert agent_page.locator(".conv-item").count() == 1
    assert "대화 A" in agent_page.locator("#messages").inner_text(), "관련 없는 대화를 삭제했는데 현재 보던 대화가 바뀜"
    stored = _stored_conversations(agent_page)
    assert [c["id"] for c in stored] == ["c-a"]
