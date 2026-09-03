"""
"Word 다운로드" 버튼 — 마크다운 다운로드 버튼([📄 마크다운 사양서 생성])이
[📄 Markdown 다운로드]/[📝 Word 다운로드] 두 버튼으로 바뀐 뒤 실제로 두 형식 모두
정상 동작하는지 검증한다. 개별 시나리오는 tests/e2e/test_markdown_button.py의
패턴(MutationObserver로 찰나의 "생성 중..." 상태를 잡는 방식)을 그대로 따른다.

build-candidate-docx는 build-candidate-markdown과 마찬가지로 LLM/RAG 없이
결정론적으로 동작하는 순수 라우트이므로, 검색 자체(/generate-spec)만 mock하고
다운로드 라우트는 실제 백엔드로 흘려보내 진짜 파일 생성/다운로드까지 검증한다.
"""
import pytest
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

pytestmark = pytest.mark.download

QUESTION = "두께 검사기 찾아줘."


def _send_and_get_equipment_card(page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _arm_generating_observer(page: Page):
    page.evaluate(
        """
        () => {
            window.__sawGenerating = false;
            const target = document.getElementById('messages');
            const check = () => {
                if (target.innerText.includes('생성 중...')) window.__sawGenerating = true;
            };
            check();
            window.__generatingObserver = new MutationObserver(check);
            window.__generatingObserver.observe(target, { childList: true, subtree: true, characterData: true });
        }
        """
    )


def _saw_generating(page: Page) -> bool:
    return page.evaluate("() => window.__sawGenerating")


def test_both_download_buttons_are_visible_and_distinct(agent_page: Page, mock_api):
    """요청서 2절: 사용자가 어떤 형식으로 다운로드하는지 명확히 알 수 있어야 한다."""
    _send_and_get_equipment_card(agent_page, mock_api)

    md_btn = agent_page.locator(".build-markdown-btn")
    docx_btn = agent_page.locator(".build-docx-btn")
    expect(md_btn).to_be_visible()
    expect(docx_btn).to_be_visible()
    assert md_btn.text_content() != docx_btn.text_content()
    assert "Markdown" in md_btn.text_content()
    assert "Word" in docx_btn.text_content()


def test_word_button_click_triggers_real_api_call_and_download_link(agent_page: Page, mock_api, live_server: str):
    """build-candidate-docx는 실제 백엔드로 보낸다(Word 렌더링 자체를 검증하기 위함)."""
    _send_and_get_equipment_card(agent_page, mock_api)

    btn = agent_page.locator(".build-docx-btn")
    expect(btn).to_be_visible()
    expect(btn).to_be_enabled()

    request_seen = []
    agent_page.on(
        "request",
        lambda req: request_seen.append(req.url) if "/api/agent/build-candidate-docx" in req.url else None,
    )
    _arm_generating_observer(agent_page)

    btn.click()

    download_link = agent_page.locator("a.build-docx-btn-ready")
    expect(download_link).to_be_visible(timeout=10000)
    expect(download_link).to_have_text("📝 Word 파일 다운로드")
    expect(agent_page.locator("button.build-docx-btn")).to_have_count(0)

    assert _saw_generating(agent_page), "Word 생성 중 \"생성 중...\" 로딩 상태가 화면에 한 번도 표시되지 않음"
    assert any("/api/agent/build-candidate-docx" in u for u in request_seen), "Word 버튼 클릭이 실제 네트워크 요청으로 이어지지 않음"

    href = download_link.get_attribute("href")
    assert href and href.startswith("/api/download/") and href.endswith(".docx")

    resp = agent_page.request.get(f"{live_server}{href}")
    assert resp.status == 200
    assert resp.headers.get("content-type", "").startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    body = resp.body()
    assert len(body) > 0, "다운로드된 .docx 파일이 비어있음"


def test_markdown_and_word_can_both_be_downloaded_independently(agent_page: Page, mock_api, live_server: str):
    """두 버튼이 서로 간섭하지 않고 각자 독립적으로 다운로드까지 완료되어야 한다."""
    _send_and_get_equipment_card(agent_page, mock_api)

    agent_page.locator(".build-markdown-btn").click()
    md_link = agent_page.locator("a.build-markdown-btn-ready")
    expect(md_link).to_be_visible(timeout=10000)

    agent_page.locator(".build-docx-btn").click()
    docx_link = agent_page.locator("a.build-docx-btn-ready")
    expect(docx_link).to_be_visible(timeout=10000)

    md_href = md_link.get_attribute("href")
    docx_href = docx_link.get_attribute("href")
    assert md_href.endswith(".md")
    assert docx_href.endswith(".docx")
    # 같은 장비(같은 후보)에서 만들었으므로 파일명 stem은 같고 확장자만 달라야 한다.
    assert md_href.rsplit(".", 1)[0] == docx_href.rsplit(".", 1)[0]

    md_resp = agent_page.request.get(f"{live_server}{md_href}")
    docx_resp = agent_page.request.get(f"{live_server}{docx_href}")
    assert md_resp.status == 200
    assert docx_resp.status == 200


def test_word_button_shows_error_on_api_failure_not_silent(agent_page: Page, mock_api):
    """API가 실패하면(500) 사용자에게 오류가 보여야 한다 — silent failure 없음."""
    _send_and_get_equipment_card(agent_page, mock_api)
    mock_api.mock(
        "**/api/agent/build-candidate-docx",
        {"detail": "Word 생성 실패(테스트로 주입한 오류)"},
        status=500,
    )
    agent_page.locator(".build-docx-btn").click()

    error_banner = agent_page.locator(".bubble.ai .banner-fail")
    expect(error_banner).to_be_visible(timeout=5000)
    expect(error_banner).to_contain_text("Word 사양서 생성 중 오류가 발생했습니다")

    retry_btn = agent_page.locator(".build-docx-btn")
    expect(retry_btn).to_be_visible(timeout=3000)
    expect(retry_btn).to_be_enabled()


def test_word_button_error_does_not_affect_markdown_button(agent_page: Page, mock_api):
    """Word 생성이 실패해도 Markdown 버튼은 독립적으로 정상 동작해야 한다(두 상태가
    서로 섞이지 않음)."""
    _send_and_get_equipment_card(agent_page, mock_api)
    mock_api.mock("**/api/agent/build-candidate-docx", {"detail": "오류"}, status=500)
    agent_page.locator(".build-docx-btn").click()
    expect(agent_page.locator(".bubble.ai .banner-fail")).to_be_visible(timeout=5000)

    agent_page.locator(".build-markdown-btn").click()
    expect(agent_page.locator("a.build-markdown-btn-ready")).to_be_visible(timeout=10000)


def test_word_button_rapid_clicks_do_not_duplicate_requests(agent_page: Page, mock_api):
    """클릭 즉시(동기적으로) 버튼이 DOM에서 사라지므로, 뒤이은 클릭 시도는 이미
    존재하지 않는 요소를 찾다가 실패해야 한다 — 중복 클릭이 물리적으로 막힌다."""
    _send_and_get_equipment_card(agent_page, mock_api)

    requests_seen = []
    agent_page.on(
        "request",
        lambda req: requests_seen.append(req.url) if "/api/agent/build-candidate-docx" in req.url else None,
    )

    btn = agent_page.locator(".build-docx-btn")
    btn.click()

    for _ in range(5):
        try:
            agent_page.locator(".build-docx-btn").click(timeout=100, force=True)
        except Exception:
            pass  # 버튼이 이미 사라져 클릭 대상이 없다 — 기대한 동작.

    expect(agent_page.locator("a.build-docx-btn-ready")).to_be_visible(timeout=10000)
    assert len(requests_seen) == 1, f"빠른 연속 클릭으로 Word 생성 요청이 중복 발생함: {requests_seen}"
    assert agent_page.locator("a.build-docx-btn-ready").count() == 1, "다운로드 링크가 중복 생성됨"


def test_word_button_single_click_generates_and_downloads_immediately(agent_page: Page, mock_api):
    """마크다운 버튼과 동일한 버그 리포트/수정 — Word 버튼도 클릭 한 번으로
    생성과 다운로드가 모두 끝나야 한다(두 번째 클릭 불필요)."""
    _send_and_get_equipment_card(agent_page, mock_api)

    with agent_page.expect_download(timeout=10000) as download_info:
        agent_page.locator(".build-docx-btn").click()
    download = download_info.value
    assert download.url.startswith("http") and "/api/download/" in download.url

    expect(agent_page.locator("a.build-docx-btn-ready")).to_be_visible()
    assert "생성 중..." not in agent_page.locator("#messages").inner_text()


def test_download_buttons_do_not_overflow_on_mobile(page: Page, live_server: str, mock_api):
    """375px에서 두 다운로드 버튼이 가로 스크롤 없이 표시되어야 한다."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    _send_and_get_equipment_card(page, mock_api)

    expect(page.locator(".build-markdown-btn")).to_be_visible()
    expect(page.locator(".build-docx-btn")).to_be_visible()
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= 375 + 1, f"다운로드 버튼 2개 추가 후 가로 스크롤 발생: scrollWidth={scroll_width}"
