"""
E2E(UX) 테스트 공통 fixture.

기존 tests/*.py(pytest + FastAPI TestClient, HTTP 계층까지만 검증)와 달리, 이
디렉터리는 실제 Chromium 브라우저로 main.py가 렌더링하는 페이지를 열어 "사용자가
브라우저에서 클릭/타이핑했을 때 화면이 실제로 어떻게 바뀌는가"를 검증한다.

설계 결정:
- pytest-playwright 플러그인 대신 fixture를 직접 만든다 — 이 환경의 Playwright
  pip 패키지(1.6x)가 기대하는 브라우저 리비전과 사전 설치된 Chromium(/opt/
  pw-browsers/chromium-1194)이 어긋나 있어(headless_shell 리비전 불일치),
  `executable_path`를 명시적으로 지정해야 한다 — pytest-playwright의 기본
  브라우저 탐색 로직은 이를 지원하지 않는다.
- Ollama/RAG는 이 환경에 없다(실제 사내 배포 환경에만 있음). 그래서 대부분의
  시나리오는 `mock_api` fixture로 프론트엔드가 호출하는 /api/agent/* 응답을
  가로채 결정론적으로 채운다 — main.py의 fetch() 호출은 항상 같은 오리진의
  상대경로이므로 Playwright의 page.route()로 온전히 가로챌 수 있다. 단
  "마크다운 사양서 생성" 버튼 테스트처럼 LLM 없이도 실제로 동작하는 경로는
  실제 백엔드를 그대로 쓴다(진짜 파일 생성/다운로드까지 검증하기 위함).
- 실제 uvicorn 서버를 서브프로세스로 띄운다 — Playwright는 실제 HTTP 오리진이
  있어야 브라우저로 접속할 수 있고(TestClient는 브라우저와 연결할 수 없다),
  실 서버라야 정적 폰트/JS/CSS 로딩까지 포함해 진짜 사용자 환경과 같다.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_RESULTS_DIR = Path(__file__).resolve().parent / "test-results"
TEST_RESULTS_DIR.mkdir(exist_ok=True)

_CHROMIUM_CANDIDATES = [
    os.environ.get("E2E_CHROMIUM_PATH", ""),
    "/opt/pw-browsers/chromium",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
]


def _resolve_chromium_executable() -> str | None:
    for candidate in _CHROMIUM_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None  # Playwright 기본 탐색(정상 설치된 환경)에 맡긴다.


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """
    main.py를 실제 uvicorn 서브프로세스로 띄우고 base_url을 돌려준다. 세션 전체에서
    하나만 띄운다 — Chroma/모델 로딩이 없어 기동은 빠르지만, 테스트마다 새로 띄우면
    포트 경합/기동 대기 시간이 누적된다.
    """
    port = _find_free_port()
    env = dict(os.environ)
    env["AGENT_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    last_error = None
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"live_server 프로세스가 조기 종료됨:\n{output}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError as e:
            last_error = e
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError(f"live_server가 {deadline}초 내에 기동하지 않음: {last_error}")

    # 소켓이 열려도 FastAPI startup이 아직 안 끝났을 수 있어 실제 페이지 응답을 확인한다.
    import urllib.request

    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{base_url}/agent", timeout=2) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("live_server가 /agent에 200을 반환하지 않음")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    executable_path = _resolve_chromium_executable()
    with sync_playwright() as p:
        launch_kwargs = {"headless": True}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        b = p.chromium.launch(**launch_kwargs)
        yield b
        b.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    """테스트마다 완전히 새 브라우저 컨텍스트(=쿠키/localStorage 없는 새 사용자)를 준다."""
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
    ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext, request: pytest.FixtureRequest) -> Iterator[Page]:
    """
    console 오류/uncaught exception을 수집해두고(요청서 3절 Scenario 1: "콘솔 오류가
    없는가"), 테스트 실패 시 스크린샷 + trace를 tests/e2e/test-results/에 저장한다.
    """
    p = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    p.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    p.on("pageerror", lambda exc: page_errors.append(str(exc)))
    p.console_errors = console_errors  # type: ignore[attr-defined]
    p.page_errors = page_errors  # type: ignore[attr-defined]

    yield p

    test_failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    safe_name = request.node.name.replace("/", "_")
    if test_failed:
        try:
            p.screenshot(path=str(TEST_RESULTS_DIR / f"{safe_name}.png"), full_page=True)
        except Exception:
            pass
        try:
            context.tracing.stop(path=str(TEST_RESULTS_DIR / f"{safe_name}-trace.zip"))
        except Exception:
            pass
    else:
        try:
            context.tracing.stop()
        except Exception:
            pass
    p.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """page fixture가 실패 여부를 알 수 있도록 각 테스트 phase의 결과를 item에 붙여둔다."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def pytest_collection_modifyitems(items):
    """tests/e2e/ 아래 모든 테스트에 자동으로 `e2e` 마커를 붙인다 — 파일마다
    `pytestmark = pytest.mark.e2e`를 반복해서 적을 필요 없이 `pytest -m e2e`로
    이 디렉터리 전체를 선택할 수 있게 한다."""
    for item in items:
        if "tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


class ApiMocker:
    """
    page.route()로 /api/agent/* 응답을 가로채는 얇은 헬퍼. 실제 호출된 payload를
    기록해두므로(section 4: "실제로 accuracy 조건만 제거되었는지 payload로 확인"),
    테스트가 프론트가 보낸 요청 본문까지 검증할 수 있다.
    """

    def __init__(self, page: Page):
        self.page = page
        self.calls: dict[str, list[dict]] = {}

    def mock(self, url_glob: str, json_body, status: int = 200, delay_ms: int = 0):
        """
        주의(delay_ms): Playwright Python sync API는 route 핸들러를 포함한 모든 동기
        호출을 하나의 그린렛/스레드로 처리한다 — 핸들러 안에서 그냥 time.sleep()을
        부르면 그 지연 동안 테스트 코드가 거는 다른 모든 Playwright 호출(expect()
        폴링 등)까지 함께 멈춘다. 반대로 진짜 별도 OS 스레드에서 sleep 후 fulfill()을
        부르는 방식은 더 나쁘다 — Playwright 동기 API의 그린렛이 스레드 하나에
        고정되어 있어 "cannot switch to a different thread" 오류로 아예 깨진다.
        따라서 delay_ms는 (a) 여러 API 호출에 걸쳐 상태가 계속 유지되는 경우
        (예: 로딩 중 disabled)에는 안전하게 쓰되, (b) "생성 중..." 같은 찰나의
        중간 상태를 잡아야 하는 테스트는 delay_ms에 의존하지 말고 브라우저 안에
        MutationObserver를 심어(client-side로) 그 상태가 한 번이라도 나타났는지
        기록하는 방식을 쓴다(test_markdown_button.py 참고) — 어느 쪽이든 Python
        쪽 폴링 타이밍에 좌우되지 않는다.
        """
        def handler(route, request):
            self.calls.setdefault(url_glob, []).append(
                json.loads(request.post_data) if request.post_data else {}
            )
            body = json.dumps(json_body)
            if delay_ms:
                time.sleep(delay_ms / 1000)
            route.fulfill(status=status, content_type="application/json", body=body)

        self.page.route(url_glob, handler)

    def mock_raw(self, url_glob: str, body: str, status: int = 200, content_type: str = "application/json"):
        def handler(route, request):
            self.calls.setdefault(url_glob, []).append({})
            route.fulfill(status=status, content_type=content_type, body=body)

        self.page.route(url_glob, handler)

    def abort(self, url_glob: str, error_code: str = "failed"):
        def handler(route, request):
            self.calls.setdefault(url_glob, []).append({})
            route.abort(error_code)

        self.page.route(url_glob, handler)

    def last_payload(self, url_glob: str) -> dict:
        return self.calls[url_glob][-1]

    def call_count(self, url_glob: str) -> int:
        return len(self.calls.get(url_glob, []))


@pytest.fixture
def mock_api(page: Page) -> ApiMocker:
    return ApiMocker(page)


@pytest.fixture
def agent_page(page: Page, live_server: str) -> Page:
    """/agent 페이지로 이동한 뒤(부팅 완료까지 대기) page를 그대로 돌려준다."""
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")
    return page
