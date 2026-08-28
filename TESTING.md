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
    test_focus_trap.py             # Drawer 내부 Tab 순환(Focus Trap), inert 배경, 데스크톱 비활성화 회귀
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

## Mobile Drawer Focus Trap

`main.py`의 `getFocusableElements(container)`가 Drawer 내부에서 실제로 화면에
보이는 포커스 가능 요소를 그때그때 동적으로 찾는다(첫/마지막 요소 하드코딩
없음 — 대화 목록이 늘어나거나 검색창이 열려도 그대로 맞는다). `document`의
`keydown` 리스너 하나가 Escape 처리와 Tab 순환을 함께 담당하며, "모바일 Drawer
모드 + 열림" 조건일 때만 개입한다 — 그 외(데스크톱, 닫힌 상태)에는 아무 것도
하지 않아 데스크톱의 기존 키보드 탐색을 그대로 둔다. Drawer가 열려 있는 동안
`.main-chat`에 `inert` 속성을 걸어 배경 콘텐츠를 키보드/포인터/스크린리더
탐색 대상에서 제외한다(지원 브라우저에서만 동작하는 progressive enhancement —
폴리필 없음). `#convSidebar`에는 `role="navigation"` + `aria-label`을 부여했다
(모달이 아닌 실제 역할에 맞게 — `dialog`를 임의로 쓰지 않았다).

## 전체 Badge/상태 표시 UI 명도 대비 실측

| Badge/상태 | Background | Text | Contrast | 결과 |
|---|---|---|---:|---|
| `.badge-pass` / `.badge-verified` | Primary-100 | text-primary | 15.06:1 | PASS |
| `.badge-fail` (RESULT_BADGE) | #fff5f5 | #9b2c2c | 7.04:1 | PASS (기존 값 유지) |
| `.badge-unknown` (RESULT_BADGE/STATUS_BADGE) | #fffaf0 | #9c4221 | 6.28:1 | PASS (기존 값 유지) |
| `.badge-inferred` (STATUS_BADGE) | #f4f2fa | Secondary-500 | 7.07:1 | PASS (기존 값 유지) |
| `.badge-userdefined` (STATUS_BADGE) | Grey-200 | Grey-900 | 14.12:1 | PASS (기존 값 유지) |
| `.badge-unset` | Grey-50 | opacity 기반 Grey-900(.5) | 3.14:1 → 6.2:1 | **수정**: opacity 제거, text-secondary로 교체 |
| `'N/A'`(인라인 override) | #e0e0e0 | #555 | 5.65:1 | PASS (기존 값 유지) |
| `.banner-pass` / `.confirm-pass` | Primary-100 | #1c6e7d | 5.36:1 | PASS (기존 값 유지) |
| `.banner-fail` / `.confirm-fail` | #fff5f5 | #822727 / #9b2c2c | 8.65:1 / 7.04:1 | PASS (기존 값 유지) |
| `.banner-unknown` / `.confirm-unknown` | #fffaf0 | #7b341e / #9c4221 | 8.58:1 | PASS (기존 값 유지) |

`.badge-unset`은 CSS 규칙만 존재하고 JS 어디에서도 실제로 쓰이지 않는 dead
클래스라(현재 화면에 나타나지 않음) `tests/e2e/test_accessibility.py`가 마크업을
직접 주입해 규칙 자체만 검증한다.

## 알려진 제한 사항 / 후속 과제

- **RAG/Ollama 의존 경로는 실제로 붙여서 돌리는 통합 테스트가 없다.** 이번
  E2E 테스트는 전부 `/api/agent/*` 응답을 mock하거나(대부분) 순수 결정론적
  라우트만 실서버로 호출한다(마크다운 버튼). 실제 Ollama + ChromaDB가 붙은
  상태에서의 종단 시나리오는 기존 `tests/test_regression.py` 등 Level 4
  테스트가 검증한다.
- **`tests/test_sample_specs_full_coverage.py::test_chat_ui_regression_baseline_multisense_ms600`의
  1회성 flaky 실패(이전 작업에서 전체 실행 3회 중 1회 관찰)에 대해 원인 분석을
  진행했으나, 재현에는 실패했고 원인도 확정하지 못했다.** 이번 작업에서 다음을
  실제로 재현·코드 분석으로 확인했다(추측이 아님):
  - **재현 시도**: 대상 테스트 단독 20회, 대상 파일 10회, 전체 스위트 3회 —
    모두 통과(추가로 별도 fresh-process 재구축 스크립트로 20회 추가 재현
    시도, 전부 통과). 총 58회 이상의 반복 실행에서 단 한 번도 실패를
    재현하지 못했다.
  - **배제한 가설(코드 근거 확인됨)**: (1) `set()` 순회 순서에 의존하는 hash
    randomization — `spec_retriever.py`/`candidate_matcher.py`/
    `spec_generator.py`의 모든 `set` 사용은 멤버십 검사 전용이거나 완전히
    명시된 `sorted()` 키를 쓰는 안정 정렬이라 해당 없음. (2) ChromaDB HNSW
    재구축 시의 근사 인덱스 비결정성 — 동일 corpus로 20회 독립 프로세스에서
    벡터 DB를 새로 빌드해 비교했으나 결과가 100% 동일. (3) pytest 실행
    순서/플러그인 — randomly/xdist/rerun류 플러그인 미설치, 수집 순서
    알파벳순으로 결정적. (4) 실제 timeout/sleep 코드 — 이 테스트는
    `ollama_client.parse_structured`를 직접 mock하므로 재시도/타임아웃
    코드 경로 자체가 실행되지 않음(테스트명의 "ms600"은 시간(ms)이 아니라
    장비 모델명 "MultiSense MS-600"). (5) 전역 상태 오염 — 모든
    `fake_embeddings` fixture가 `with mock.patch.object(...): yield`
    컨텍스트 매니저 패턴으로 module 종료 시 확실히 해제되고,
    `get_embeddings()`에는 캐시(`lru_cache` 등)가 없어 파일 간 누수 경로가
    없음. (6) 유력하게 의심했던 가설 — `sample_specs/SPEC-044.md`와
    `SPEC-051.md`가 동일하게 "MultiInspect MI-800"이라는 장비명을 쓰는 것을
    발견(52개 corpus 문서 중 유일한 이름 중복)하고, 이 둘 사이의 RAG 유사도
    근소 차이로 인한 흔들림이 원인일 수 있다고 의심했으나, 직접 후보 랭킹을
    출력해 확인한 결과 SPEC-051 후보는 `status=PASS`(pass=6, unknown=0),
    SPEC-044/MS-600 후보는 `status=PASS`가 아닌 `PARTIAL`(unknown=1)로—
    점수 차이가 아니라 등급(Status Tier) 자체가 달라 결정적으로 SPEC-051이
    이기는 구조임을 확인했다. 즉 이 중복은 실제 데이터 위생 문제이긴 하지만
    (별도로 `tests/regression_lib.py`의 `by_name` 딕셔너리 구성 시 이론상
    이름 충돌 가능성이 있음) 이번 flaky 실패의 원인은 아님이 확인되어
    코드/데이터 수정은 진행하지 않았다(원인이 아닌 것으로 확인된 부분을
    범위 밖에서 임의로 고치지 않는다는 원칙에 따름).
  - **확인하지 못한 사실**: 최초 1회 실패 당시의 정확한 assertion/traceback이
    기록되어 있지 않아, 이번에 배제한 가설 외의 원인(예: 최초 실패 당시의
    환경에 고유했던 일회성 이슈)을 완전히 배제할 수는 없다. 근거 없이
    코드를 추측성으로 수정하지 않는다는 원칙에 따라 이번에는 코드를
    수정하지 않았고, 대신 재발 시 정확한 assertion 실패 내용과 traceback을
    반드시 기록해 다음 조사가 이어질 수 있게 한다.

## Sample Specs Corpus 데이터 무결성

위 flaky test 조사 중 발견된 `sample_specs/SPEC-044.md`/`SPEC-051.md`의 중복
장비명("MultiInspect MI-800")을 계기로, corpus 전체의 데이터 무결성을 검사했다.

**구조 분석(수정 전 확인한 사실)**:
- Equipment Name(Manufacturer + Model)은 corpus 내에서 Unique하다고 보장되지
  않는다 — 실제로 52개 문서 중 이 한 쌍만 중복(`scripts/audit_sample_specs.py`
  실행 결과, 아래 참고).
- SPEC 파일명(`source_document`, 예: `"SPEC-051.md"`)은 파일시스템이 보장하는
  유일 식별자이며, **운영 코드(`agent/candidate_matcher.py`의
  `build_candidates`가 만드는 `by_source` 딕셔너리, `CandidateEquipment.
  candidate_id`/`source_document`)는 이미 이 값을 Key로 쓴다** — 즉 RAG/후보
  매칭 엔진 자체는 이름 중복에 영향받지 않는다.
- Equipment Name을 Dictionary Key로 쓰는 코드는 저장소 전체에서
  `tests/regression_lib.py`의 `RegressionRunResult.by_name` 단 한 곳뿐이었다
  (`grep`으로 전수 확인). 이 딕셔너리는 `{candidate_name(c): c for c in
  candidates}` 형태로, 이름이 중복되면 나중 후보가 앞의 후보를 조용히
  overwrite했다 — 우연히 SPEC-044.md < SPEC-051.md 알파벳 순서 덕분에 지금까지
  항상 의도한(SPEC-051) 후보로 덮였을 뿐, 설계상 보장된 동작은 아니었다.
- SPEC-044.md(정확도 ±0.8μm, Measurement Principle "Multi-sensor", Defect
  Types "Surface Defect")와 SPEC-051.md(정확도 ±1.0μm, Measurement Principle
  "3D Laser Profilometry", Defect Types "Scratch, Crack, Particle, Coating
  Defect", Classification/Safety 섹션 추가 보유)를 직접 비교한 결과, 두 문서는
  서로 다른 실측 스펙을 가진 **서로 다른 장비**이며 이름만 우연히 겹친
  것으로 판단된다(원본 데이터를 추측 없이 그대로 비교한 결과).

**결정한 정책**: 새 Database나 ID 마이그레이션을 추가하지 않고, 이미 운영
코드가 쓰고 있는 **SPEC 파일명(`source_document`)을 Unique Identifier**로
채택했다 — 가장 적은 변경으로 충돌을 방지할 수 있는 기존 구조이기 때문이다.

**변경 사항**:
- `scripts/audit_sample_specs.py` 추가 — SPEC ID/Equipment Name/Manufacturer+
  Model 중복, 완전 동일 문서, 핵심 Metadata·Spec 필드 동일, 필수 필드
  (Manufacturer/Model) 누락을 검사하는 독립 Audit 도구(`python
  scripts/audit_sample_specs.py`로 직접 실행 가능). 새 유사도 엔진을 만들지
  않고 이미 운영 코드가 쓰는 `build_rag_ollama.parse_markdown_file`/
  `agent.candidate_matcher._extract_candidate_fact`를 그대로 재사용한다.
- `tests/test_sample_specs_integrity.py` 추가 — 위 Audit을 pytest로 감싸,
  (1) Manufacturer/Model 누락, (2) SPEC ID 중복, (3) 완전 동일 문서는 항상
  실패시키고, (4) 새로 발견된(리뷰되지 않은) 중복 장비명이 있으면 실패시켜
  앞으로 SPEC 파일을 추가할 때 기존 이름과 우연히 겹치는 실수를 자동으로
  잡는다. 이미 검토된 "MultiInspect MI-800" 중복은 허용 목록에 등록해뒀다.
- `tests/regression_lib.py`: `RegressionRunResult.by_name`을 이름 -> 단일
  후보에서 이름 -> 후보 목록(`Dict[str, List[CandidateEquipment]]`)으로 바꿔
  중복 시에도 데이터가 사라지지 않게 했다. `.candidate(name, spec_id=None)`에
  `spec_id`(예: `"SPEC-051.md"`) 인자를 추가해 이름이 중복될 때 어느 문서를
  가리키는지 명시할 수 있게 했고, 명시하지 않았는데 중복이면 조용히 아무
  후보나 고르는 대신 `AmbiguousCandidateNameError`를 던져 문제를 드러낸다.
  기존처럼 이름이 유일한 경우는 동작이 전혀 바뀌지 않는다.
- `tests/ground_truth/regression_cases.json`: "MultiInspect MI-800"을 참조하는
  4개 케이스(T001/T002/T005/T021)에 `"candidate_spec_ids": {"MultiInspect
  MI-800": "SPEC-051.md"}`를 추가해, 그동안 알파벳 순서 우연에 의존하던 것을
  명시적으로 고정했다. 검증 강도는 그대로 유지했다(이름 존재 여부만 보던 것을
  느슨하게 만들지 않았고, 오히려 어느 문서인지까지 명시하도록 강화했다).
- `tests/test_regression.py`: `AmbiguousCandidateNameError`를 잡아 기존
  리포트 포맷(`format_case_failure`)으로 사람이 읽을 수 있게 표시하도록
  `_lookup` 헬퍼를 추가했다.

**Audit 결과**(`python scripts/audit_sample_specs.py`, 2026-08-28 기준):
```
Total Documents: 52
Unique Equipment Names: 51
Duplicate Equipment Names: MultiInspect MI-800 (SPEC-044.md, SPEC-051.md) — 검토 완료, 허용 목록 등록
Result: WARNING
```
참고로 SPEC-030.md/SPEC-049.md는 Range/Accuracy/Resolution/Speed가 전부
`UNKNOWN`이고 Width(800mm)만 같아 "Same Core Spec Fields" 검사에 함께
걸리지만, Manufacturer(EdgeScan Pro vs VisionFlex)·Model·Equipment Type이
전부 달라 실제로는 다른 장비다 — 우연의 일치이며 조치가 필요 없다.

`Result: WARNING`은 의도된 상태다 — SPEC-044/051 중복은 삭제 대상이 아니라
(서로 다른 실제 장비이므로) 안전하게 처리하도록 만든 것이 이번 작업의
목표였다. 새로운 미검토 중복이 생기면 `tests/test_sample_specs_integrity.py`가
실패로 잡아낸다.

## 중복 Equipment Name의 화면 표시(Disambiguation UX)

위 Corpus 무결성 작업으로 "Backend/RAG 계층"의 데이터 충돌은 해결됐지만, 별도로
"사용자에게 보이는 화면"에서도 같은 이름의 서로 다른 장비가 구분되는지는
검증되지 않았다. 이번 작업에서 실제 코드 흐름을 추적하고 재현했다.

**분석(수정 전 확인한 사실)**:
- `agent/candidate_matcher.build_candidates()`는 `retrieved_docs`를
  `source_document`(SPEC 파일명) 단위로 그룹화하므로, SPEC-044와 SPEC-051은
  이름이 같아도 항상 별개의 `CandidateEquipment`로 남는다 — 하나가 다른
  하나를 지우거나 병합하는 코드 경로는 없다.
- 그러나 `agent/routes.py`의 `/api/agent/generate-spec`은 `candidates`(복수)를
  프론트엔드에 내려주지 않는다 — `select_best_candidate()`가 고른 **후보 1개**
  (`chosen_candidate`)만 반환한다. 즉 한 번의 검색 결과 화면(EquipmentCard)에는
  항상 장비가 하나만 보인다 — "추천 결과 목록에 같은 이름이 두 줄 나열되는"
  화면 자체가 지금 구조에는 없다.
- 실제 위험은 **대화가 이어지는 동안(후속 질문으로 요구사항이 바뀌는 경우)**
  발생한다: `main.py`는 각 검색마다 새 `equipment_result` 메시지를 대화에
  추가해 쌓아 두므로(`renderAll()`이 전체 메시지를 다시 그림), 같은 대화 안에서
  턴이 바뀌며 다른 `chosen_candidate`가 선택되면 이름이 같은 EquipmentCard
  두 개가 같은 화면에 함께 나타날 수 있다.
- 실제 파이프라인(fake-embedding, 실제 sample_specs corpus)으로 재현한 결과,
  "폭 600mm, 두께+표면결함, 정확도 <=1.0μm" 질의는 SPEC-051.md를,
  "폭 800mm, Multi-sensor, 정확도 <=0.8μm" 질의는 SPEC-044.md를
  `chosen_candidate`로 선택했다 — 즉 한 대화에서 후속 질문만으로 이 상황이
  실제로 발생할 수 있음을 코드 추측이 아니라 실행으로 확인했다.
- `chosen_candidate`(전체 `CandidateEquipment`, `equipment_fact` 포함:
  measurement_method/principle/range/accuracy/defect_types 등)는 이미 각
  `equipment_result` 메시지에 저장되어 localStorage까지 그대로 보존된다 —
  구분에 필요한 데이터가 이미 Frontend에 있으므로 Backend/API 변경이 필요
  없었다.

**개선(필요한 경우에만 조건부로 적용)**: `main.py`에 대화 전체의
`equipment_result` 메시지를 Equipment Name으로 묶고, 실제로 `source_document`가
서로 다른 그룹에서만(즉 진짜 다른 장비일 때만) 우선순위 기반으로 구분 정보를
표시하는 로직을 추가했다(`computeEquipmentDisambiguation`/
`pickDisambiguationLabels`, 요청서 우선순위: Manufacturer → Measurement
Method/Principle → Inspection Item(Defect Types) → Width → Range → Accuracy →
Source Document). 이름은 같지만 `source_document`까지 같으면(진짜 같은 추천이
반복된 경우) 아무것도 표시하지 않는다. 새 Backend 데이터나 새 색상 체계를
추가하지 않았고, RAG/Ranking/Candidate Filtering은 전혀 건드리지 않았다.

**적용 화면**:

| 화면 | 적용 여부 | 방식 |
|---|---|---|
| Chat Result / Candidate Card (EquipmentCard) | 적용 | 카드 헤더 바로 아래 `.card-subtitle`(12px, `--text-secondary`, `--grey-50` 배경 위 6.2:1 대비)로 조건부 표시 |
| Comparison Result | 해당 없음 | 이 카드는 애초에 장비 이름 자체를 표시하지 않음(Hard Requirement 항목/배지만 표시) |
| Conversation Restore(새로고침/localStorage 복원) | 자동 적용 | `renderAll()`이 호출될 때마다 저장된 메시지로부터 다시 계산 — 별도 상태 저장 없이 항상 결정론적 |
| Markdown 생성 | 해당 없음(구조상 미해당) | `build-candidate-markdown`은 candidate 1개만 받아 문서 1개를 만든다(여러 후보를 한 문서에 나열하는 기능 자체가 없음). 각 문서의 "## General" 절에는 이미 Manufacturer/Model/Measurement Principle/Type이 전부 들어있어 파일을 열면 그 자체로 구분된다 |
| MS Word 다운로드 | 기능 없음 | 이 프로젝트에는 Word(.docx) 출력 기능이 없다(Markdown만 지원) |
| Mobile(375px) | 회귀 없음 확인 | Disambiguation Label 추가 후에도 가로 스크롤/버튼 밀림 없음(E2E로 검증) |

**수정 파일**:

| 파일 | 수정 내용 |
|---|---|
| `main.py` | `computeEquipmentDisambiguation`/`pickDisambiguationLabels`/`disambiguationFieldMap` 추가, `renderAll`/`renderMessageContent`/`renderEquipmentCard`가 이를 사용하도록 연결, `.card-subtitle` CSS 추가 |
| `tests/e2e/fixtures.py` | `make_candidate()`에 manufacturer/model/source_document/measurement_method/measurement_principle/defect_types 등 선택적 override 추가(기존 호출부는 영향 없음), `make_generate_spec_response()`에 `specification`/`candidate` 직접 지정 옵션 추가 |
| `tests/e2e/test_duplicate_equipment_disambiguation.py` | 신규 — Normal/Duplicate/Deterministic/Fallback/Persistence/Markdown/Accessibility/Mobile 테스트 9개 |

**검증**: `pytest tests/e2e/test_duplicate_equipment_disambiguation.py` 9개
전부 PASS, 기존 `tests/e2e/*` 111개 전부 PASS(회귀 없음), 전체 스위트 2회 연속
635 passed / 0 failed / 0 xfailed.

## 동일 장비명 재등장 시 대화 UX 검증 (Conditional Disambiguation 충분성 재검토)

위 Disambiguation Label(Card Subtitle) 하나만으로 사용자가 "같은 이름의 서로
다른 장비"를 충분히 이해할 수 있는지, 실제 브라우저로 재현해 검증했다.

**분석 결과**:
- `computeEquipmentDisambiguation()`은 `renderAll()`이 호출될 때마다(새 메시지
  추가 포함) 대화 전체를 다시 계산한다 — 실제로 재현한 결과, 두 번째 동일 이름
  후보가 등장하면 **이미 그려져 있던 첫 번째 카드도 Subtitle을 새로 얻는다**
  (재현: 1턴 후 Subtitle 0개 → 2턴 후 Subtitle 2개, 첫 카드 포함).
- Subtitle만으로는 "이 값 차이가 서로 다른 장비를 가리킨다"는 사실 자체가
  명확히 전달되지 않았다 — 예를 들어 "검사 항목: Surface Defect"와 "검사 항목:
  Scratch, Crack, Particle, Coating Defect"는 같은 장비를 다른 맥락에서 요약한
  결과로도 읽힐 수 있다(문제 A 해당).
- 반대로 첫 카드가 Subtitle을 소급해서 얻는 것 자체는 문제로 보지 않았다 —
  오히려 두 카드가 비대칭으로(한쪽만 구분 정보를 가짐) 표시되는 쪽이 더
  혼란스럽다고 판단했다(§ 과거 메시지 처리 방식 참고).

**UX 개선 결정: 최소 UX 개선 적용(Option B, Contextual Hint)**
- 적용 방식: 같은 이름 그룹 안에서 **새로 등장해 기존 그룹과 처음으로 다른
  `source_document`를 도입하는 메시지에만** "ℹ️ 이전 추천과 이름은 같지만,
  서로 다른 장비입니다."를 카드 본문 맨 위에 표시(`pickContextualHints`,
  문구는 후속 검토에서 "다른 사양의 장비" → "서로 다른 장비"로 수정됨 — 아래
  참고). 이미 표시된 과거 카드에는 Hint를 소급 삽입하지 않는다.
- 적용 조건(4가지 모두 충족해야 함): (1) 서로 다른 `source_document`, (2) 동일
  Equipment Name, (3) 같은 Conversation 안, (4) 새로 등장하는 후보가 기존
  동일 이름 후보와 실제로 다름(그룹 내에서 그 `source_document`가 처음 등장).
- 왜 이 방식이 적절한가: Subtitle은 그룹 구성이 바뀔 때마다 다시 계산돼야
  올바른 구분 필드를 유지할 수 있으므로(예: 세 번째 후보가 등장하면 구분
  기준 필드 자체가 바뀔 수 있음) 대칭적 재계산을 유지하는 것이 맞다. 반면
  Hint는 "왜 지금 이 카드가 다른가"를 그 카드가 등장하는 시점에 설명하는
  용도이므로, 과거 카드에 두 번째 변경(Hint)까지 추가하면 오히려 문제 C를
  키운다 — 새로 등장하는 카드에만 붙이는 것이 대화의 시간 순서와 자연스럽게
  맞아떨어진다.

**과거 메시지 처리 방식**:
- **동적 계산을 유지했다**(Message State에 저장하지 않음). 이유: 세 번째
  동일 이름 후보가 나중에 등장하면 그룹을 구분하는 기준 필드 자체가 바뀔 수
  있다 — 이때 과거에 저장해 둔 Disambiguation을 그대로 두면 "더 이상 실제로
  구분되지 않는 필드"가 화면에 남아 오히려 잘못된 정보가 된다. 동적 계산은
  이런 상황에서도 항상 현재 대화 전체 기준으로 올바른 구분 필드를 재선택한다.
  구현 복잡도(State 추가, localStorage Migration)도 동적 계산 쪽이 훨씬 낮다.
- Persistence와의 관계: 상태를 저장하지 않으므로 `localStorage`에는
  `chosen_candidate`(계산에 필요한 원본 데이터)만 그대로 저장되고,
  Disambiguation Label/Hint는 페이지 로드 시 `renderAll()`이 매번 다시
  계산한다 — 새로고침 전후 정확히 같은 입력이므로 항상 같은 결과가 나온다
  (E2E로 재현/검증 완료).

**수정 파일**:

| 파일 | 수정 내용 |
|---|---|
| `main.py` | `pickContextualHints()` 추가, `computeEquipmentDisambiguation()`이 `{labels, hints}`를 함께 반환하도록 변경, `renderEquipmentCard`/`renderMessageContent`가 Hint를 받아 조건부로 렌더링, `.card-hint` CSS 추가(새 색상 없이 `--text-secondary`/`--font-body-sm-size` 재사용) |
| `tests/e2e/test_duplicate_equipment_disambiguation.py` | Hint 관련 검증 추가 + 신규 테스트 2개(첫 카드는 Hint를 소급으로 얻지 않음, 새 Conversation 격리) |

**테스트**: 신규 포함 총 11개 전부 PASS, 기존 `tests/e2e/*` 111개 회귀 없음
(총 113개), 전체 스위트 2회 연속 637 passed / 0 failed / 0 xfailed.

## 동일 장비명 재등장 UX 재검증 (Hint 문구 검토 + 순서/확장성 검증)

Conditional Disambiguation(Subtitle) + Contextual Hint 조합이 실제로 충분한지
다시 검증했다. 코드를 먼저 바꾸지 않고, 실제 브라우저로 정순/역순/3자 시나리오를
재현한 뒤 문제가 확인된 부분만 최소로 수정했다.

**분석 결과**:
- 재현한 화면(Card 1: "MultiInspect MI-800 / 검사 항목: Surface Defect", Card 2:
  같은 이름 + 다른 Subtitle + Hint)에서, **Subtitle과 Hint를 함께 보면 두 카드가
  실제로 다른 장비라는 것은 충분히 전달된다** — Hint가 "다르다"는 사실 자체를
  직접 언급하기 때문이다.
- 다만 기존 Hint 문구 "동일한 장비명이지만 이전 추천과 다른 사양의 장비입니다."의
  **"다른 사양"이라는 표현을 재검토한 결과 문제를 확인했다**: 한국어에서 "다른
  사양"은 "같은 제품의 다른 구성/옵션"을 가리킬 때도 매우 흔히 쓰인다(예: "다른
  사양의 노트북" = 같은 모델의 RAM/SSD 구성 차이). 즉 기존 문구가 오히려 "같은
  장비의 다른 옵션"으로 오해될 여지를 남겼다(Question 2에서 지적된 위험이 실제로
  존재함을 확인).
- "동일한 장비명이지만"이라는 도입부 자체는 사용자가 화면에서 이미 보고 있는
  사실(이름이 같다)을 그대로 서술한 것이라 내부 데이터 문제처럼 보이지 않는다고
  판단했다 — 이 부분은 유지했다.

**UX 결정: Hint 문구만 최소 수정(Option A)** — Option B(시각적 강조)/Option
C(별도 라벨)는 적용하지 않았다. 재현 결과 카드 간 시각적 구분(각자 별도의 AI
답변 버블 + 그 위의 "AI가 이해한 요구사항"/"검색 완료" 카드가 매 턴마다 새로
붙는 구조)이 이미 "새로운 검색 결과"라는 것을 알려주고 있어, 추가 시각 요소나
별도 라벨 없이 문구 수정만으로 문제가 해소된다고 판단했다.

- Before: `이전 추천과 다른 사양의 장비입니다.`
- After: `이전 추천과 이름은 같지만, 서로 다른 장비입니다.`

"다른 사양"(같은 제품의 다른 구성으로 오해 가능) 대신 "서로 다른 장비"(다른
제품 자체)를 명사구로 직접 명시해 모호성을 없앴다.

**정순/역순/확장성 재현(실제 fixture 기반, corpus 미변경)**:
- SPEC-051 → SPEC-044 순서와 SPEC-044 → SPEC-051 역순 모두, Hint는 항상 **나중에
  등장한 카드에만** 붙었다 — 어느 물리적 SPEC 파일이 먼저인지와 무관하게 대칭적
  으로 동작함을 확인했다.
- 동일 이름을 가진 가상의 3개 후보(A/B/C, synthetic fixture)로 확장 검증한 결과,
  Subtitle은 3개 후보 모두에서 일관되게(같은 필드 기준으로) 구분되었고, Hint는
  두 번째/세 번째 카드에만(각 1회) 나타났으며 첫 카드에는 나타나지 않았다 — 그룹
  크기가 늘어나도 로직이 그대로 일반화됨을 확인했다. 안내 문구가 두 번 나타나도
  내용이 항상 동일해 대화가 산만해지지 않았다.

**수정 파일**:

| 파일 | 수정 내용 |
|---|---|
| `main.py` | `pickContextualHints()`의 Hint 문구를 "다른 사양의 장비" → "서로 다른 장비"로 수정(로직/조건은 변경 없음) |
| `tests/e2e/test_duplicate_equipment_disambiguation.py` | 새 문구로 assertion 갱신 + "다른 사양" 문구가 다시 나타나지 않는지 확인하는 회귀 검사 추가, 신규 테스트 2개(역순 재현, 3자 확장성) |

**테스트**: 신규 포함 총 13개 전부 PASS, 기존 `tests/e2e/*` 113개 회귀 없음
(총 115개), 전체 스위트 2회 연속 639 passed / 0 failed / 0 xfailed.

## Word(.docx) 사양서 다운로드

기존 "마크다운 사양서 생성" 버튼(`/api/agent/build-candidate-markdown`,
`renderers.markdown_renderer.render_candidate_markdown`)을 분석한 뒤, 같은
데이터(`CandidateEquipment`/`RequirementSchema`/Hard Requirement 결과)로 Word
(.docx) 문서도 만들 수 있도록 확장했다.

**분석(수정 전 확인한 사실)**:
- 프론트엔드 "마크다운 사양서 생성" 버튼은 검색 시점에 계산된 `chosen_candidate`
  (CandidateEquipment, LLM을 거치지 않고 사양서 원문에서 결정론적으로 추출한 값)
  와 `requirement`만 `/api/agent/build-candidate-markdown`에 보내고 있었다 —
  Hard Requirement 비교 결과(`hardRequirementReport`)는 화면에는 표시되지만
  Markdown 문서에는 포함되지 않았다.
- `renderers/common.py`에는 이미 `SpecificationSchema`(LLM이 채운 최종 사양서)
  기반의 12섹션 공통 구조(`build_sections()`)가 있고 `pptx_renderer.py`가 이를
  재사용하고 있었다 — 하지만 이 프로젝트의 실제 "마크다운 사양서 생성" 버튼은
  의도적으로 이 경로를 쓰지 않는다(`tests/test_candidate_markdown_route.py`
  상단 docstring: LLM이 채운 값과 섞이지 않는, 근거가 명확한 문서를 만들기
  위함). 따라서 Word도 같은 이유로 `CandidateEquipment` 기반으로 만들었다 —
  `SpecificationSchema` 경로로 갈아타면 기존에 의도적으로 배제한 LLM 값이
  다시 섞여 들어가는 더 큰(그리고 불필요한) 변경이 된다.

**공통 Structured Data**: `renderers/candidate_specification.py`
(`build_candidate_specification_data()`)를 새로 만들어, Markdown과 Word
렌더러가 candidate/requirement/hard_requirement_report를 각자 재해석하지 않고
정확히 같은 계산 결과(`SpecSection`/`SpecRow`/`ComplianceRow`)를 공유하도록
했다. 값이 원본 사양서에 없으면 "UNKNOWN"으로 정직하게 남기고(요청서 9절),
CandidateEquipmentFact가 아예 추출하지 않는 영역(Spatial Performance/Optical
System/System Configuration/Interfaces/Environment/Safety)도 섹션 자체는 항상
포함하되 전부 UNKNOWN으로 표시한다 — 요청서가 명시한 13개 섹션 구조를 항상
일관되게 유지하기 위함이다.

**기존 Markdown 출력 보존**: `render_candidate_markdown()`의 General/Inspection
Performance/Inspection Items/Defect Inspection/Sources 절은 기존 형식(문자열
그대로)을 전혀 바꾸지 않았다 — `tests/test_candidate_markdown_route.py`가 계속
그대로 통과한다. 새 13-섹션 구조(Inspection Target/Requirements/Measurement
Performance/Spatial Performance/Optical System/System Configuration/
Interfaces/Environment/Safety/Requirement Compliance)는 그 뒤에 이어 붙였다.

**Word 문서**: `renderers/docx_renderer.py`(`render_candidate_docx()`,
python-docx)가 같은 Structured Data로 Title(장비명) + 섹션별 표(Item/
Specification/Status) + Requirement Compliance 표(Requirement/Required/
Equipment/Result) + Sources/Notes를 만든다. 값과 상태(VERIFIED/UNKNOWN)는
표의 별도 컬럼에 들어가므로 "0~300umVERIFIED"처럼 붙어 보이는 문제가 없다
(python-docx로 재확인: 각 셀이 별도 텍스트).

**API**: 기존 명명 규칙(`/api/agent/build-candidate-markdown`)에 맞춰
`/api/agent/build-candidate-docx`를 추가했다(요청서가 제안한 `POST /api/
specification/download?format=` 대신 기존 라우트 네이밍을 그대로 확장 — "기존
구조를 최대한 재사용"). 두 라우트 모두 이제 `hard_requirement_report`(선택,
프론트엔드가 검색 시점에 이미 계산해 저장해 둔 값)를 받는다.

**파일명**: 기존 `electrode_inspection_candidate_{uuid}.md`(무작위) 대신 추천
장비명 기반 `{Manufacturer}_{Model}_specification.{md|docx}`로 바꿨다. Windows
금지 문자(`\ / : * ? " < > |`)는 정규식으로 `_`치환하고, 장비명이 전혀 없으면
`equipment_specification.{md|docx}`로 fallback한다(`agent/routes.py:
_safe_filename_stem`). 다운로드 시점에 기존부터 있던 `/api/download/{file_name}`
라우트가 모든 다운로드에 "설비사양서_" 접두어를 붙이는 동작(이번 작업 이전부터
있던, 이 기능과 무관한 공통 동작)은 그대로 두었다 — 실제 브라우저 다운로드
파일명은 `설비사양서_{Manufacturer}_{Model}_specification.docx`가 된다.

**UI**: 기존 "[📄 마크다운 사양서 생성]" 버튼 1개를 "[📄 Markdown 다운로드]
[📝 Word 다운로드]" 2개로 나눴다(`DOWNLOAD_FORMATS` 표 하나로 두 버튼의 렌더링/
생성 로직을 공유 — 세 번째 포맷이 추가돼도 표만 늘리면 됨). 각 버튼은 독립적인
상태(생성 중/완료/오류)를 가지며, 하나가 실패해도 다른 하나는 정상 동작한다.
중복 클릭 방지는 기존 마크다운 버튼과 동일한 패턴(클릭 시 동기적으로 버튼을
DOM에서 제거)을 그대로 재사용했다. 새 색상은 추가하지 않고 기존
`.download-btn` 스타일을 그대로 썼다.

**수정/추가 파일**:

| 파일 | 내용 |
|---|---|
| `renderers/candidate_specification.py` | 신규 — Markdown/Word 공통 Structured Data 빌더 |
| `renderers/docx_renderer.py` | 신규 — python-docx 기반 Word 렌더러 |
| `renderers/markdown_renderer.py` | `render_candidate_markdown()`이 공통 데이터로 새 섹션들을 추가 렌더링(기존 섹션은 그대로) |
| `agent/routes.py` | `/api/agent/build-candidate-docx` 신규 라우트, 파일명 sanitize 헬퍼, 두 라우트가 `hard_requirement_report` 수신 |
| `main.py` | 버튼 2개로 분리, `DOWNLOAD_FORMATS` 테이블 기반 공통 렌더링/생성 로직, `.download-actions`/`.card-hint` 등 CSS, `_DOWNLOAD_MEDIA_TYPES`에 `.docx` 추가 |
| `requirements.txt` | `python-docx>=1.1.0` 추가 |
| `pytest.ini` | `specification`/`download` 마커 추가 |
| `tests/test_candidate_docx_route.py` | 신규 — Word 렌더링/라우트/파일명 테스트 8개 |
| `tests/test_specification_consistency.py` | 신규 — Markdown/Word 핵심 정보 일치 테스트 5개 |
| `tests/e2e/test_docx_download_button.py` | 신규 — Word 버튼 E2E 테스트 7개 |
| `tests/e2e/test_markdown_button.py` | 새 버튼 라벨에 맞춰 텍스트 assertion 2곳 갱신(동작 자체는 동일) |
| `tests/e2e/test_accessibility.py` | 다운로드 버튼이 2개가 됐으므로 대비 검사를 두 버튼 모두에 적용 |

**검증**: 신규 테스트(백엔드 13개 + E2E 7개) 전부 PASS, 기존 `tests/e2e/*`
115개 중 텍스트 문구 2곳만 의도적으로 갱신하고 전부 PASS, 실제 브라우저에서
질문 전송 → 두 버튼 모두 클릭 → 실제 `.md`/`.docx` 파일 다운로드 → python-docx로
재확인까지 수동으로도 확인했다. 전체 스위트 2회 연속 659 passed / 0 failed /
0 xfailed.
