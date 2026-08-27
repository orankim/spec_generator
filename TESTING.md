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
모순된 문구와 함께 뜨는 문제는 Level 6에서만 잡힌다. 실제로 이 계층에서 발견해
함께 고친 실제 버그들:

- 마크다운 사양서 생성 실패 후 재시도 버튼이 영구히 사라지는 문제
- 추가 질문 제안을 빠르게 여러 번 클릭하면 동일 질문이 중복 전송되는 문제
- 모바일 화면(375px 등)에서 전송 버튼이 뷰포트 밖으로 밀려나는 문제
- 모바일 Overlay Drawer 도입 과정에서 발견된 3건 — 열림 상태에서 폭이 0으로
  붕괴, Backdrop/Drawer 패널이 아이콘 레일 위 햄버거 버튼 클릭을 가로챔,
  Drawer를 연 직후 포커스 이동이 Playwright의 클릭 시뮬레이션 특유의 타이밍과
  충돌
- `#sendBtn`/`.download-btn`/`.badge-pass`/`.badge-verified`/`.card-row .label`의
  WCAG AA 명도 대비 미달(아래 Color System 섹션 참고)

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
    test_accessibility.py          # axe-core 스캔 + 키보드/이름 접근성 + WCAG AA 명도 대비 실측
    test_dead_ui.py                # 주요 클릭 요소의 "클릭 → 실제 동작" 종합 점검
    test_mobile_drawer.py          # 모바일(640px 이하) Overlay Drawer: 열림/닫힘/Backdrop/Escape/Focus 관리
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

## Color System / Text 토큰 (WCAG AA 개선)

기존 브랜드 컬러(Primary-600 #2D9BB2 등)는 로고/링크/활성 아이콘 역할로 그대로
유지하면서, 흰 텍스트가 올라가는 버튼과 opacity 기반 회색 텍스트만 아래 토큰으로
교체해 WCAG AA(4.5:1) 대비를 확보했다.

| Token | 값 | 역할 | 비고 |
|---|---|---|---|
| `--primary-600` | #2D9BB2 | 로고/링크/활성 아이콘/Focus Border | 브랜드 컬러 — 변경 없음 |
| `--primary-500` | #3EC2CF | Sidebar 선택 강조 | 변경 없음 |
| `--primary-100` | #D9FCF4 | Quick Start/강조 Background | 변경 없음 |
| `--primary-action` | #237C90 (신규) | 흰 텍스트/아이콘이 올라가는 버튼(전송/마크다운 생성) | 흰색 대비 4.82:1 |
| `--text-primary` | #1F1F1F (=grey-900) | 배지 등 진한 텍스트 | Primary-100 배경 대비 15:1 |
| `--text-secondary` | #595959 (신규) | 설명/사이드바 보조 텍스트/카드 라벨 | 흰 배경 7.0:1, grey-50 배경 6.2:1 |
| `--text-tertiary` | #686868 (신규, 요청 예시 #767676에서 조정) | 날짜/메타 정보 | grey-50 배경 기준 예시값이 4.02:1로 미달해 4.93:1로 조정 |

## 알려진 제한 사항 / 후속 과제

- **모바일 Overlay Drawer는 "접기"이지 완전한 모달 드로어는 아니다.** 640px
  이하에서 사이드바는 `position:fixed` + `transform`으로 본문 위에 오버레이되어
  열려도 본문 폭이 줄지 않는다(핵심 요구사항 충족). 다만 완전한 Focus Trap(Tab
  키가 Drawer 밖으로 못 나가게 가두는 것)까지는 구현하지 않았다 — 열 때 Drawer
  안으로, 닫을 때 햄버거로 포커스를 옮기는 최소 요구사항만 구현했다(요청서
  11절에서 완전한 Trap은 선택 사항으로 명시).
- **RAG/Ollama 의존 경로는 실제로 붙여서 돌리는 통합 테스트가 없다.** 이번
  E2E 테스트는 전부 `/api/agent/*` 응답을 mock하거나(대부분) 순수 결정론적
  라우트만 실서버로 호출한다(마크다운 버튼). 실제 Ollama + ChromaDB가 붙은
  상태에서의 종단 시나리오는 기존 `tests/test_regression.py` 등 Level 4
  테스트가 검증한다.
- **다른 배지(.badge-fail/.badge-unknown/.badge-inferred 등)의 명도 대비는
  이번 범위 밖.** 이번 작업은 요청서에서 명시적으로 지목한 요소(#sendBtn/
  .download-btn/.badge-pass/.badge-verified/.card-row .label)만 검증·수정했다
  — 다른 배지 색상도 실측해보면 좋겠지만, 별도 요청 없이 임의로 손대지 않았다.
