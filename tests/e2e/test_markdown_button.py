"""
요청서 3절 섹션 7 — "마크다운 사양서 생성" 버튼.

이 버튼이 클릭해도 아무 동작을 하지 않던 것이 이번 세션 직전 작업(PR #33)의 수정
대상이었다 — 그래서 여기서는 버튼 element 존재 여부가 아니라 "클릭 → 눈에 보이는
상태 변화(생성 중... → 다운로드 버튼/오류) → 실제 다운로드 가능한 파일"까지
실제로 검증한다.

/api/agent/build-candidate-markdown은 LLM/RAG 없이 결정론적으로 동작하는 순수
라우트이므로(renderers.markdown_renderer.render_candidate_markdown), 첫 테스트는
그 호출만 실제 백엔드로 흘려보내고(검색 자체(/generate-spec)는 여전히 mock으로
채운 chosenCandidate를 그대로 씀) 실제 파일 생성/다운로드까지 종단으로 검증한다.

기술 노트: 이 실제 백엔드 호출은 수 ms 안에 끝나는 매우 빠른 라우트라, click()
이후 Python 쪽에서 "생성 중..." 텍스트를 순차 polling으로 잡으려 하면 그 찰나의
중간 상태를 완전히 놓칠 수 있다(관찰 시점에 이미 지나가 있음). 또한 Playwright
Python 동기 API는 route 핸들러를 포함한 모든 호출을 하나의 그린렛/스레드로
처리하므로, route 핸들러 안에서 그냥 time.sleep()으로 지연을 주면 그동안 테스트
코드 쪽의 다른 Playwright 호출(expect 폴링 등)까지 함께 멈춰버려 같은 문제를
일으키고, 반대로 별도 OS 스레드에서 sleep 후 fulfill()을 부르면 그린렛이 다른
스레드로 전환될 수 없어 아예 깨진다. 그래서 이 파일의 모든 "찰나의 상태" 검증은
Python 쪽 polling 타이밍에 의존하지 않는 방식 — 클릭 전에 브라우저 안에
MutationObserver를 심어 그 상태가 한 번이라도 나타났는지를 기록해두는 방식 —
을 쓴다.
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response

QUESTION = "두께 검사기 찾아줘."


def _send_and_get_equipment_card(page: Page, mock_api):
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    page.fill("#chatInput", QUESTION)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _arm_generating_observer(page: Page):
    """"생성 중..." 문구가 #messages 안에 한 번이라도 나타나면 window.__sawGenerating을
    true로 남긴다 — 실제 응답이 몇 ms 만에 끝나든 Python 쪽 polling 타이밍과
    무관하게 신뢰할 수 있다."""
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


def test_markdown_button_click_triggers_real_api_call_and_download_link(agent_page: Page, mock_api, live_server: str):
    """build-candidate-markdown은 실제 백엔드로 보낸다(마크다운 렌더링 자체를 검증하기 위함)."""
    _send_and_get_equipment_card(agent_page, mock_api)

    btn = agent_page.locator(".build-markdown-btn")
    expect(btn).to_be_visible()
    expect(btn).to_be_enabled()

    request_seen = []
    agent_page.on(
        "request",
        lambda req: request_seen.append(req.url) if "/api/agent/build-candidate-markdown" in req.url else None,
    )
    _arm_generating_observer(agent_page)

    btn.click()

    # 완료 후에는 실제 다운로드 링크로 바뀌어야 한다(silent failure 없음) — 이 자체가
    # "idle 버튼 -> 생성 중 -> 다운로드 링크"라는 관찰 가능한 상태 변화의 최종 증거다.
    download_link = agent_page.locator("a.download-btn")
    expect(download_link).to_be_visible(timeout=10000)
    expect(download_link).to_have_text("📄 Markdown 파일 다운로드")
    expect(agent_page.locator("button.build-markdown-btn")).to_have_count(0)

    assert _saw_generating(agent_page), "\"생성 중...\" 로딩 상태가 화면에 한 번도 표시되지 않음"
    assert any("/api/agent/build-candidate-markdown" in u for u in request_seen), "버튼 클릭이 실제 네트워크 요청으로 이어지지 않음"

    href = download_link.get_attribute("href")
    assert href and href.startswith("/api/download/")

    # 실제로 다운로드 가능한 결과물인지 파일 내용까지 확인한다.
    resp = agent_page.request.get(f"{live_server}{href}")
    assert resp.status == 200
    assert resp.headers.get("content-type", "").startswith("text/markdown")
    body = resp.text()
    assert body.startswith("# Equipment Specification")
    assert "## General" in body
    assert "## Inspection Performance" in body


def test_markdown_button_disabled_state_is_not_permanent(agent_page: Page, mock_api):
    """"생성 중..." 상태가 실제로 존재했다가(MutationObserver로 확인) 영구히 남지
    않고 다운로드 링크로 풀리는지 검증한다."""
    _send_and_get_equipment_card(agent_page, mock_api)
    _arm_generating_observer(agent_page)

    agent_page.locator(".build-markdown-btn").click()

    expect(agent_page.locator("a.download-btn")).to_be_visible(timeout=10000)
    assert _saw_generating(agent_page), "\"생성 중...\" 상태가 한 번도 관찰되지 않음"
    # 최종 상태에는 "생성 중..." 문구가 남아있지 않아야 한다(영구 고착 없음).
    assert "생성 중..." not in agent_page.locator("#messages").inner_text()


def test_markdown_button_shows_error_on_api_failure_not_silent(agent_page: Page, mock_api):
    """API가 실패하면(500) 사용자에게 오류가 보여야 한다 — 버튼만 사라지고 아무 반응
    없이 끝나는 silent failure가 없어야 한다."""
    _send_and_get_equipment_card(agent_page, mock_api)
    mock_api.mock(
        "**/api/agent/build-candidate-markdown",
        {"detail": "Markdown 생성 실패(테스트로 주입한 오류)"},
        status=500,
    )
    agent_page.locator(".build-markdown-btn").click()

    error_banner = agent_page.locator(".bubble.ai .banner-fail")
    expect(error_banner).to_be_visible(timeout=5000)
    expect(error_banner).to_contain_text("Markdown 사양서 생성 중 오류가 발생했습니다")

    # 오류 후에도 아무 반응 없이 끝나지 않는다 — 다시 시도할 수 있도록 버튼이 되돌아온다.
    retry_btn = agent_page.locator(".build-markdown-btn")
    expect(retry_btn).to_be_visible(timeout=3000)
    expect(retry_btn).to_be_enabled()


def test_markdown_button_rapid_clicks_do_not_duplicate_requests(agent_page: Page, mock_api):
    """클릭 즉시(동기적으로) 버튼이 DOM에서 사라지므로, 뒤이은 클릭 시도는 이미
    존재하지 않는 요소를 찾다가 실패해야 한다 — 중복 클릭이 물리적으로 막힌다.
    이 테스트는 실제 백엔드를 그대로 쓰므로(mock을 걸지 않음) 요청 횟수는
    mock_api가 아니라 실제 네트워크 이벤트로 센다."""
    _send_and_get_equipment_card(agent_page, mock_api)

    requests_seen = []
    agent_page.on(
        "request",
        lambda req: requests_seen.append(req.url) if "/api/agent/build-candidate-markdown" in req.url else None,
    )

    btn = agent_page.locator(".build-markdown-btn")
    btn.click()

    for _ in range(5):
        try:
            agent_page.locator(".build-markdown-btn").click(timeout=100, force=True)
        except Exception:
            pass  # 버튼이 이미 사라져 클릭 대상이 없다 — 기대한 동작.

    expect(agent_page.locator("a.download-btn")).to_be_visible(timeout=10000)
    assert len(requests_seen) == 1, f"빠른 연속 클릭으로 마크다운 생성 요청이 중복 발생함: {requests_seen}"
    assert agent_page.locator("a.download-btn").count() == 1, "다운로드 링크가 중복 생성됨"


def test_markdown_button_single_click_generates_and_downloads_immediately(agent_page: Page, mock_api):
    """
    버그 리포트: 예전에는 버튼을 한 번 눌러야 사양서가 "생성"되고, 화면에 나타난
    다운로드 링크를 다시(두 번째로) 눌러야 실제 파일 다운로드가 시작됐다. 이제는
    "생성" 버튼 클릭 한 번으로 생성과 다운로드가 모두 끝나야 한다 —
    Playwright의 page.expect_download()로 같은 클릭 안에서 실제 다운로드
    이벤트가 발생하는지 직접 검증한다(두 번째 클릭 없이).
    """
    _send_and_get_equipment_card(agent_page, mock_api)

    with agent_page.expect_download(timeout=10000) as download_info:
        agent_page.locator(".build-markdown-btn").click()
    download = download_info.value
    assert download.url.startswith("http") and "/api/download/" in download.url

    # 다운로드가 끝난 뒤에는 버튼이 이미 완료 상태(ready 링크)로 바뀌어 있어야
    # 한다 — "생성 중..."에 머물러 있거나 여전히 클릭을 기다리는 상태가 아니다.
    expect(agent_page.locator("a.download-btn")).to_be_visible()
    assert "생성 중..." not in agent_page.locator("#messages").inner_text()


def test_markdown_ready_link_redownloads_without_regenerating(agent_page: Page, mock_api):
    """한 번 생성된 뒤 완료 링크를 다시 클릭하면(예: 파일을 재차 저장하고 싶은 경우)
    API를 다시 호출하지 않고 이미 만들어진 파일을 그대로 재다운로드해야 한다 —
    "한 번 생성되면 그 다음부터는 생성 없이 다운로드만" 정책."""
    _send_and_get_equipment_card(agent_page, mock_api)

    requests_seen = []
    agent_page.on(
        "request",
        lambda req: requests_seen.append(req.url) if "/api/agent/build-candidate-markdown" in req.url else None,
    )

    with agent_page.expect_download(timeout=10000):
        agent_page.locator(".build-markdown-btn").click()
    assert len(requests_seen) == 1

    with agent_page.expect_download(timeout=10000):
        agent_page.locator("a.download-btn").click()
    assert len(requests_seen) == 1, "완료된 링크를 다시 눌렀는데 생성 API가 또 호출됨(재생성 발생)"
