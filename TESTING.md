# 테스트 가이드

이 프로젝트는 두 종류의 테스트를 함께 쓴다.

1. **`tests/*.py`** — 기존 pytest 단위/통합/회귀 테스트. FastAPI `TestClient`와
   순수 함수 호출만 쓰며, 브라우저나 실제 Ollama 서버가 없어도 전부 실행된다.
2. **`tests/e2e/*.py`** — 이번에 새로 추가한 E2E(UX) 테스트. 실제 Chromium
   브라우저로 `main.py`가 렌더링하는 `/agent` 페이지를 열어, 사용자가 클릭/
   타이핑했을 때 화면이 실제로 어떻게 바뀌는지 검증한다.

두 종류 모두 같은 `pytest` 실행기로 돌아가지만(같은 `pytest.ini`, 같은
`pytest tests -v` 한 번으로 전부 실행 가능), 목적이 다르므로 디렉터리를
분리했다.

## 검증 체계 (Level 1~6)

| Level | 목적 | 위치 |
|---|---|---|
| 1 | Requirement Parser 단위 테스트 — 자연어 → RequirementSchema 파싱/후속 패치 | `tests/test_requirements.py`, `tests/test_conversational_patch.py`, `tests/test_requirement_structuring.py` 등 |
| 2 | Candidate Fact Extraction — 사양서 원문에서 사실을 결정론적으로 뽑아내는지 | `tests/test_candidate_extraction.py`, `tests/test_candidate_matcher.py` |
| 3 | Hard Requirement Validation — PASS/FAIL/UNKNOWN 판정 로직 | `tests/test_hard_requirements.py`, `tests/test_hard_requirement_pipeline_fixes.py`, `tests/test_item_independence.py` |
| 4 | Regression / Ground Truth — SPEC-011~050 코퍼스 기준 종단 회귀 | `tests/test_regression.py`, `tests/test_sample_specs_ground_truth.py` |
| 5 | Frontend Component / API 계약 테스트 — 라우트가 올바른 JSON을 반환하는지 (브라우저 없이) | `tests/test_build_markdown_route.py`, `tests/test_candidate_markdown_route.py`, `tests/test_main_ui_routes.py` |
| 6 | **E2E User Experience 테스트** — 실제 브라우저로 사용자 흐름 전체를 검증 | `tests/e2e/*.py` (이번에 추가) |

Level 1~5는 "로직이 옳은가"를 검증하고, Level 6은 "그 로직이 실제 화면에서
사용자에게 올바르게 도달하는가"를 검증한다 — 예를 들어 Level 3이
`hard_requirement_report`의 `UNKNOWN` 판정 자체가 옳다는 걸 보장해도, 그 값이
화면에서 `"0 ~ 300 μmVERIFIED"`처럼 깨져 보이거나 "모든 조건 충족"이라는
모순된 문구와 함께 뜨는 문제는 Level 6에서만 잡힌다(실제로 이번 작업에서
비슷한 실제 버그 세 건 — 마크다운 재시도 버튼 소실, 추가 질문 제안 중복 전송,
모바일 화면에서 전송 버튼이 뷰포트 밖으로 밀려나는 문제 — 를 이 계층에서
발견해 함께 고쳤다).

## E2E 테스트 구조

```
tests/e2e/
    conftest.py                    # live_server(uvicorn 서브프로세스)/browser/page/mock_api fixture
    fixtures.py                    # agent.schemas 기반 canned API 응답 빌더
    test_first_visit.py            # 시나리오 1: 최초 접속
    test_chat_flow.py              # 시나리오 2~5: 질문 전송/Enter·버튼/연속 클릭/긴 입력
    test_followup_state.py         # 후속 질문·조건 부분 삭제(payload 검증 포함)
    test_new_conversation.py       # "새로운 대화 시작"
    test_history_persistence.py    # 대화 이력 유지 정책(8시간 비활성 초기화)
    test_markdown_button.py        # "마크다운 사양서 생성" 버튼 종단 검증
    test_related_questions.py      # 추가 질문 제안
    test_unknown_and_hardreq_ui.py # UNKNOWN 표시, PASS/FAIL/UNKNOWN 배지, 논리 일관성
    test_scroll_and_responsive.py  # 자동 스크롤, 4개 뷰포트 반응형
    test_error_handling.py         # 네트워크/API 오류 6종
    test_accessibility.py          # axe-core 스캔 + 키보드/이름 접근성
    test_dead_ui.py                # 주요 클릭 요소의 "클릭 → 실제 동작" 종합 점검
```

### 설계 원칙

- **DOM 존재 여부가 아니라 행동 기반 검증.** 모든 테스트는 "사용자 행동 →
  화면 변화 → 관찰 가능한 결과"를 확인한다. 버튼이 있는지가 아니라, 클릭했을
  때 네트워크 요청이 나가고 화면이 실제로 바뀌는지를 본다.
- **Ollama/RAG 없이도 결정론적으로 실행된다.** 이 환경(그리고 CI)에는 Ollama가
  없다. `mock_api`(`conftest.ApiMocker`)가 Playwright의 `page.route()`로
  `/api/agent/*` 호출을 가로채, `fixtures.py`가 실제 `agent.schemas` Pydantic
  모델로 만든 canned 응답을 대신 돌려준다 — 스키마가 바뀌면 fixture도 즉시
  깨지므로 존재하지 않는 필드로 프론트엔드를 속이는 일이 없다.
- **"진짜로 파일이 만들어지는가"가 중요한 경로는 실제 백엔드를 그대로 쓴다.**
  `/api/agent/build-candidate-markdown`은 LLM 없이 결정론적으로 동작하는 순수
  라우트라, `test_markdown_button.py`·`test_dead_ui.py`는 이 호출만 mock하지
  않고 실제 서버로 보내 파일 생성 → 다운로드까지 종단으로 확인한다.
- **찰나의 로딩 상태는 Python 쪽 polling이 아니라 브라우저 쪽 MutationObserver로
  잡는다.** 실제 백엔드 호출은 수 ms 안에 끝날 수 있어, Python에서 순차적으로
  `expect()`를 걸면 그 사이 상태를 놓친다(자세한 이유는
  `test_markdown_button.py`의 모듈 docstring 참고). 클릭 전에 페이지 안에
  관찰자를 심어두는 방식으로 타이밍에 관계없이 신뢰성 있게 검증한다.
- **"빠른 연속 클릭"은 동기 JS로 재현한다.** Python에서 여러 번 `.click()`을
  호출하면 그 사이에 mock 응답이 이미 끝나버려 진짜 중복 클릭을 재현하지
  못할 수 있다. `page.evaluate()` 안에서 동기적으로 여러 번 `.click()`을
  호출해 네트워크 지연과 무관하게 실제로 겹치는 클릭을 만든다
  (`test_related_questions.py` 참고).

## 실행 방법

이 프로젝트는 Python/pytest 기반이라(별도 Node.js 프런트엔드 빌드가 없음),
`npm run test:e2e` 같은 명령 대신 아래 pytest 명령을 쓴다.

```bash
# 의존성 설치(최초 1회) — E2E 전용 패키지는 런타임 requirements.txt와 분리했다.
pip install -r requirements.txt -r requirements-e2e.txt

# 기존 pytest 전체(Level 1~5, 브라우저 불필요)
pytest tests -v --ignore=tests/e2e

# E2E(UX) 테스트만(Level 6, Chromium 필요)
pytest tests/e2e -v
# 또는 마커로:
pytest -m e2e -v

# 전체(Level 1~6) 한 번에
pytest tests -v

# 특정 E2E 시나리오 파일만
pytest tests/e2e/test_chat_flow.py -v

# 특정 테스트 하나만
pytest tests/e2e/test_markdown_button.py::test_markdown_button_click_triggers_real_api_call_and_download_link -v

# 실패 시 스크린샷/trace 확인
# (tests/e2e/conftest.py의 page fixture가 실패한 테스트마다 아래 경로에 자동 저장한다)
ls tests/e2e/test-results/
# trace 파일은 Playwright의 트레이스 뷰어로 연다:
playwright show-trace tests/e2e/test-results/<테스트이름>-trace.zip
```

### 브라우저 준비

`conftest.py`는 `PLAYWRIGHT_BROWSERS_PATH` 환경변수 또는
`/opt/pw-browsers/chromium`(심볼릭 링크) 경로에서 Chromium을 찾는다. 이
저장소를 다른 환경(CI 등)에서 처음 실행한다면:

```bash
playwright install chromium
# 또는 이미 별도로 관리되는 Chromium 경로가 있다면:
export E2E_CHROMIUM_PATH=/path/to/chromium
```

## 실패 시 리포트되는 정보

E2E 테스트가 실패하면 pytest의 표준 assert 메시지에 다음이 포함된다.

1. 어떤 시나리오/함수인지 (`tests/e2e/test_xxx.py::test_yyy`)
2. 무엇을 기대했는지와 실제로 무엇을 관찰했는지(assert 메시지에 한국어로 명시)
3. 실패 시점의 접근성 트리 스냅샷(Playwright가 자동 첨부)
4. `tests/e2e/test-results/<테스트이름>.png` — 실패 시점 전체 페이지 스크린샷
5. `tests/e2e/test-results/<테스트이름>-trace.zip` — DOM 스냅샷·네트워크·콘솔
   로그가 모두 담긴 Playwright trace(성공한 테스트는 저장하지 않는다)

## 알려진 제한 사항 / 후속 과제

- **명도 대비(WCAG AA) 미달 — Color System 자체에서 비롯됨.** `#sendBtn`/
  `.download-btn`(흰 글자 on Primary-600 #2D9BB2, 실측 3.25:1)과
  `.badge-pass`/`.badge-verified`(Primary-100 계열 배지, 실측 ~3.3:1),
  `.card-row .label`(opacity 기반 회색, 실측 ~3.7:1)이 axe-core 기준
  4.5:1을 만족하지 못한다. 이는 이전 세션에서 사용자가 명시적으로 확정한
  Color System 토큰/opacity 위계 표현 자체에서 비롯되므로 이번 작업에서는
  브랜드 색상을 임의로 바꾸지 않았다 — `tests/e2e/test_accessibility.py`가
  이 항목들을 알려진 이슈로 조건부 `xfail` 처리해두었으니, 디자인 토큰을
  조정하면(또는 텍스트 크기를 키우면) 자동으로 일반 PASS로 전환된다.
- **모바일 사이드바는 "접기"이지 "오버레이"가 아니다.** 640px 이하에서
  대화 목록 사이드바를 기본으로 접어(이번에 고친 버그) 본문 폭을 확보했지만,
  햄버거로 펼치면 여전히 폭을 나눠 쓰는 방식이다(모달처럼 위에 덮이지 않음).
  화면이 아주 좁을 때 펼친 상태에서는 본문이 다시 좁아진다 — 진짜 모바일
  드로어(배경 dim + 오버레이)로 만들려면 별도 UI/UX 설계 결정이 필요하다.
- **RAG/Ollama 의존 경로는 실제로 붙여서 돌리는 통합 테스트가 없다.** 이번
  E2E 테스트는 전부 `/api/agent/*` 응답을 mock하거나(대부분) 순수 결정론적
  라우트만 실서버로 호출한다(마크다운 버튼). 실제 Ollama + ChromaDB가 붙은
  상태에서의 종단 시나리오는 기존 `tests/test_regression.py` 등 Level 4
  테스트가 검증한다.
