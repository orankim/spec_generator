"""
UX 개선 4-1절 — 대화 이름 변경(Rename): 저장 경로(Enter/버튼, 빈 값/공백 검증).

main.py의 startRenameConversation()/commitRenameConversation()이 인라인
폼(.conv-rename-form/.conv-rename-input)으로 동작한다. 저장은
sessionStorage(conv.title)에 반영된다. 빈 문자열/공백만 입력하면 저장하지
않고 기존 제목을 유지한다.

취소/복원, ID·메시지 보존, 긴 제목 레이아웃 케이스는
tests/e2e/test_conversation_rename_revert.py에서 다룬다(한 파일에 8개를
모두 몰아넣었더니 이 환경에서 순차 실행 시 뒤쪽 테스트가 간헐적으로 timeout —
기존 프로젝트 관례대로 관심사별 작은 파일로 나눈다).
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


def test_rename_via_enter_updates_title_and_persists(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)

    rename_input = agent_page.locator(".conv-rename-input")
    expect(rename_input).to_be_visible()
    assert rename_input.input_value() == QUESTION  # 기존 제목이 미리 채워짐

    rename_input.fill("나만의 저장 이름")
    rename_input.press("Enter")

    expect(agent_page.locator(".conv-rename-input")).to_have_count(0)
    expect(agent_page.locator(".conv-item").first).to_have_text("나만의 저장 이름")

    stored = _stored_conversations(agent_page)
    assert stored[0]["title"] == "나만의 저장 이름"


def test_rename_via_save_button_updates_title(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "버튼으로 저장")
    agent_page.click(".conv-rename-save")

    expect(agent_page.locator(".conv-item").first).to_have_text("버튼으로 저장")


def test_rename_empty_input_keeps_old_title(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "")
    agent_page.click(".conv-rename-save")

    expect(agent_page.locator(".conv-item").first).to_have_text(QUESTION)
    stored = _stored_conversations(agent_page)
    assert stored[0]["title"] == QUESTION


def test_rename_whitespace_only_input_keeps_old_title(agent_page: Page, mock_api):
    _send(agent_page)
    _open_rename(agent_page)
    agent_page.fill(".conv-rename-input", "    ")
    agent_page.click(".conv-rename-save")

    stored = _stored_conversations(agent_page)
    assert stored[0]["title"] == QUESTION, "공백만 입력했는데 제목이 바뀜"
