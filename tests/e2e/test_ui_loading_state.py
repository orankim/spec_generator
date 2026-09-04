"""
UX 개선 A — "답변을 생성하고 있습니다..." 로딩 상태.

이번 작업의 배경: 새 대화창에서 첫 질문을 보내면 Requirement Parsing(LLM 호출,
/api/agent/analyze-requirement)이 끝날 때까지 화면에 아무 변화가 없었다(입력창이
비활성화되는 것 외에는 눈에 띄는 피드백이 없음) — 사용자가 "버튼이 눌리지
않았다"거나 "시스템이 멈췄다"고 오해할 수 있는 지점이었다. main.py의
handleUserMessage()는 메시지 전송 즉시(첫 API 호출을 걸기 전에) type: 'thinking'
메시지를 추가해 이 공백을 정직하게 메운다 — 실제 진행 단계와 무관한 가짜 다단계
문구("검색 중...", "분석 중..." 등 시간 기반 연출)는 쓰지 않고, "답변을 생성하고
있습니다..." 하나의 문구만 표시하며, 첫 응답(성공/실패 모두)이 오면 즉시 지워진다.

Ollama 없이도 실행 가능하다(mock_api로 /api/agent/* 응답을 가로챈다 — Level 1).

기술 노트(찰나의 상태 관찰 — tests/e2e/conftest.py의 ApiMocker.mock() 문서화 참고):
이 로딩 메시지는 나타났다가 사라지는 진짜 "찰나"의 상태라서, Python 쪽에서
delay_ms + expect()/evaluate() 폴링으로 잡으려 하면 안 된다 — mock 라우트
핸들러의 time.sleep()이 Playwright Python 동기 드라이버 전체를 그 지연 동안
멈춰버려서, 지연이 끝나는 순간에는 이미 다음 API 호출까지 끝나버린 "최종 상태"만
보게 될 수 있다(실제로 이 파일 초안에서 이 방식으로 작성했다가 재현/확인함).
그래서 이 파일은 tests/e2e/test_markdown_button.py와 동일한 기법 — 전송 전에
브라우저 안에 MutationObserver를 심어 상태가 실제로 나타났는지(그리고 필요하면
언제/어떤 순서로 나타났는지)를 기록 — 을 쓴다. 유일한 예외는 "여러 API 호출에
걸쳐 계속 유지되는 상태"(예: 로딩 중 input/button disabled)로, 이런 종류는
tests/e2e/test_chat_flow.py의 test_loading_indicator_shown_then_input_disabled_
then_reenabled와 동일하게 두 API 모두에 delay_ms를 준 뒤 읽어도 안전하다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."
LOADING_TEXT = "답변을 생성하고 있습니다"


def _arm_thinking_observer(page: Page):
    """".thinking-indicator"가 #messages 안에 처음 나타난 순간의 텍스트를 기록하고,
    그 시점에 ".progress-list"(SearchProgressCard)가 아직 없었는지도 함께 남긴다 —
    실제 응답이 몇 ms 만에 끝나든 Python 쪽 polling 타이밍과 무관하게 신뢰할 수
    있다(test_markdown_button.py와 동일 기법)."""
    page.evaluate(
        """
        () => {
            window.__sawThinking = false;
            window.__thinkingText = null;
            window.__thinkingBeforeProgress = null;
            const target = document.getElementById('messages');
            const check = () => {
                const el = target.querySelector('.thinking-indicator');
                if (el && !window.__sawThinking) {
                    window.__sawThinking = true;
                    window.__thinkingText = el.textContent;
                    window.__thinkingBeforeProgress = !target.querySelector('.progress-list');
                }
            };
            check();
            window.__thinkingObserver = new MutationObserver(check);
            window.__thinkingObserver.observe(target, { childList: true, subtree: true, characterData: true });
        }
        """
    )


def _saw_thinking(page: Page) -> bool:
    return page.evaluate("() => window.__sawThinking")


def _thinking_text(page: Page) -> str:
    return page.evaluate("() => window.__thinkingText") or ""


def _thinking_before_progress(page: Page):
    return page.evaluate("() => window.__thinkingBeforeProgress")


# ---------------------------------------------------------------
# Case A — 정상 응답: 전송 즉시 로딩 표시 → 응답 수신 → 로딩 제거 → 실제 답변 표시
# ---------------------------------------------------------------
def test_loading_shown_immediately_on_send_with_correct_text(agent_page: Page, mock_api):
    """메시지 전송 즉시(첫 API 호출이 끝나기 전부터) "답변을 생성하고 있습니다..."가
    나타나야 한다 — 정확한 등장 여부/문구를 MutationObserver로 확정적으로 잡는다."""
    _arm_thinking_observer(agent_page)
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    assert _saw_thinking(agent_page), "로딩 상태('답변을 생성하고 있습니다...')가 한 번도 나타나지 않음"
    assert LOADING_TEXT in _thinking_text(agent_page)


def test_loading_removed_once_response_arrives_then_real_answer_shown(agent_page: Page, mock_api):
    _arm_thinking_observer(agent_page)
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    assert _saw_thinking(agent_page), "로딩 상태('답변을 생성하고 있습니다...')가 한 번도 나타나지 않음"
    # 응답이 온 뒤에는 로딩 메시지가 남아있지 않아야 한다(영구 고착 금지).
    assert agent_page.locator(".thinking-indicator").count() == 0
    full_text = agent_page.locator("#messages").inner_text()
    assert "AI가 이해한 요구사항" in full_text


def test_only_one_loading_state_shown_no_fake_multi_step_progress_before_first_response(agent_page: Page, mock_api):
    """요청서 3절: 첫 응답 전에는 "검색 중...", "분석 중..." 같은 가짜 다단계 문구를
    시간 기반으로 보여주면 안 된다 — 로딩 메시지가 화면에 처음 나타난 시점에는
    아직 SearchProgressCard(.progress-list, 실제 두 번째 API 호출의 in-flight
    여부에만 연결됨)가 존재하지 않아야 한다."""
    _arm_thinking_observer(agent_page)
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    assert _saw_thinking(agent_page)
    assert _thinking_before_progress(agent_page) is True, (
        "로딩 문구가 나타난 시점에 이미 검색 진행 카드(.progress-list)가 함께 있었음"
        " — 가짜 다단계 진행 표시처럼 보일 수 있음"
    )


# ---------------------------------------------------------------
# Case B — API 오류: 로딩 표시 → API 오류 → 로딩 제거 → 오류 메시지 표시
# ---------------------------------------------------------------
def test_loading_removed_and_error_shown_on_api_failure(agent_page: Page, mock_api):
    _arm_thinking_observer(agent_page)
    mock_api.mock("**/api/agent/analyze-requirement", {"detail": "테스트 주입 오류"}, status=500)

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".bubble.error")).to_be_visible(timeout=10000)
    assert _saw_thinking(agent_page), "오류 시나리오에서도 로딩 상태가 먼저 보였어야 함"
    assert agent_page.locator(".thinking-indicator").count() == 0, "오류 후에도 로딩 메시지가 남아있음"
    expect(agent_page.locator("#chatInput")).to_be_enabled()
    expect(agent_page.locator("#sendBtn")).to_be_enabled()


def test_loading_removed_on_network_abort(agent_page: Page, mock_api):
    _arm_thinking_observer(agent_page)
    mock_api.abort("**/api/agent/analyze-requirement")

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    expect(agent_page.locator(".bubble.error")).to_be_visible(timeout=10000)
    assert _saw_thinking(agent_page)
    assert agent_page.locator(".thinking-indicator").count() == 0


# ---------------------------------------------------------------
# Case C — 연속 전송: 로딩 중(=요청이 진행 중인 동안)에는 입력창/버튼이 계속
# 비활성화되어 있어야 한다. 이 상태는 두 API 호출에 걸쳐 계속 유지되는 상태이므로
# (test_chat_flow.py::test_loading_indicator_shown_then_input_disabled_then_reenabled
# 와 동일한 근거로) delay_ms 기반으로 안전하게 관찰할 수 있다. Shift+Enter
# 줄바꿈/연속 클릭 방지 자체는 tests/e2e/test_chat_flow.py에서 이미 검증하므로
# 여기서는 반복하지 않는다.
# ---------------------------------------------------------------
def test_input_and_send_button_disabled_for_whole_request_duration(agent_page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response(), delay_ms=400)
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"), delay_ms=400)

    agent_page.fill("#chatInput", QUESTION)
    agent_page.click("#sendBtn")

    disabled_state = agent_page.evaluate(
        "() => ({input: document.getElementById('chatInput').disabled, "
        "btn: document.getElementById('sendBtn').disabled})"
    )
    assert disabled_state["input"] is True, "로딩 중 입력창이 비활성화되지 않음(중복 전송 위험)"
    assert disabled_state["btn"] is True, "로딩 중 전송 버튼이 비활성화되지 않음(중복 전송 위험)"

    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    expect(agent_page.locator("#chatInput")).to_be_enabled()
    expect(agent_page.locator("#sendBtn")).to_be_enabled()
    assert agent_page.locator(".msg-row.user").count() == 1
