"""
UX 개선 4-1절 — 대화 이름 변경(Rename): 취소/복원, 데이터 보존, 레이아웃.

저장 경로(Enter/버튼, 빈 값/공백 검증)는 tests/e2e/test_conversation_rename.py
참고. 이 파일은 취소(버튼/ESC) 시 원래대로 복원되는지, 이름 변경이 대화
id/메시지/생성 시각을 건드리지 않는지, 긴 제목이 레이아웃을 깨지 않는지를
다룬다.
"""
import json

from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

STORAGE_KEY = "electrode_ai_conversations_v1"
QUESTION = "두께 검사기 찾아줘."


def _send(page: Page, text: str = QUESTION):
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _stored_conversations(page: Page):
    raw = page.evaluate(f"() => sessionStorage.getItem('{STORAGE_KEY}')")
    return json.loads(raw) if raw else []


def _open_rename(page: Page):
    page.click(".conv-item-menu-btn")
    page.click(".conv-menu-rename")


def test_rename_cancel_button_reverts_without_saving(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "저장되면 안 되는 제목")
    agent_page.click(".conv-rename-cancel")

    expect(agent_page.locator(".conv-rename-input")).to_have_count(0)
    expect(agent_page.locator(".conv-item").first).to_have_text(QUESTION)
    stored = _stored_conversations(agent_page)
    assert stored[0]["title"] == QUESTION


def test_rename_escape_reverts_without_saving(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "ESC로 취소될 제목")
    agent_page.locator(".conv-rename-input").press("Escape")

    expect(agent_page.locator(".conv-rename-input")).to_have_count(0)
    stored = _stored_conversations(agent_page)
    assert stored[0]["title"] == QUESTION


def test_rename_does_not_change_conversation_id_or_messages(agent_page: Page, mock_api):
    _send(agent_page)
    before = _stored_conversations(agent_page)[0]

    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "새 이름")
    agent_page.click(".conv-rename-save")

    after = _stored_conversations(agent_page)[0]
    assert after["id"] == before["id"]
    assert after["messages"] == before["messages"]
    assert after["createdAt"] == before["createdAt"]


def test_rename_long_title_does_not_break_layout(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    long_title = "가" * 200
    agent_page.fill(".conv-rename-input", long_title)
    agent_page.click(".conv-rename-save")

    body_scroll_width = agent_page.evaluate("document.documentElement.scrollWidth")
    viewport_width = agent_page.evaluate("window.innerWidth")
    assert body_scroll_width <= viewport_width + 1, "긴 대화 제목으로 인해 가로 스크롤 발생(레이아웃 깨짐)"
    # 저장 자체는 maxlength(60)까지만 반영된다(입력 단계에서부터 브라우저가 제한).
    stored = _stored_conversations(agent_page)
    assert len(stored[0]["title"]) <= 60
