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
