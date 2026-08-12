# IMPLEMENTATION_PLAN.md
## 전극 검사기 사양서 자동 생성 AI Agent

> SpecificationSchema/RequirementSchema 필드 상세, Status/Source/Confidence 정의,
> Markdown/HTML/PPTX 포맷은 이 문서가 아니라 `docs/SPECIFICATION_SCHEMA.md`,
> `docs/SPECIFICATION_MARKDOWN_FORMAT.md`, `docs/PPT_SLIDE_STRUCTURE.md`를 참고한다.
> 이 문서는 최초 설계 시점의 분석/의사결정 기록이다.

## 1. 기존 Repository 분석

### 1.1 현재 LLM 호출 방식
- `generator.py`의 `SpecGenerator`가 `langchain_community.llms.Ollama`를 통해 Ollama를 호출한다.
- `format="json"`, `num_ctx=8192`, `num_predict=2048`을 지정해 잡텍스트 없이 순수 JSON을 강제하고, 컨텍스트 초과로 응답이 잘리는 문제를 완화해 두었다. (이번 세션에서 실제 배포 중 발견/수정된 부분)
- `format="json"`은 Ollama의 "아무 JSON이나" 모드이며, 필드 이름/타입까지 강제하는 **JSON Schema 기반 구조화 출력**은 아직 쓰지 않고 있다. Ollama는 `format`에 문자열 `"json"` 대신 **JSON Schema 객체**를 전달하면 그 스키마를 만족하는 JSON만 생성하도록 강제할 수 있다 (Ollama `/api/generate`, `/api/chat`의 네이티브 기능). 이번 Agent는 이 기능을 직접 사용한다.

### 1.2 현재 Ollama 모델
- LLM: `qwen2.5:14b` (하드코딩)
- Embedding: `bge-m3` (하드코딩)
- 서버 주소: `http://localhost:11434` (하드코딩, 일부는 생성자 인자로 노출)

### 1.3 현재 RAG 구조
- `build_rag_ollama.py`: `sample_specs/*.pptx`를 슬라이드 단위로 파싱 → 슬라이드 1개 = Document 1개(텍스트+표를 마크다운으로 이어붙인 덩어리) → Chroma에 임베딩 저장.
- `generator.py`의 `_retrieve_context`: 사용자 질문 텍스트로 `similarity_search(k=3)` 한 번 실행 → 슬라이드 3개를 통째로 프롬프트에 붙여넣음.
- 즉 현재는 **슬라이드(문서) 단위 검색**이며, "정확도", "Scan Speed" 같은 **개별 사양 항목 단위 검색**은 아니다. 항목 단위로 검색하려면 인덱싱 시점에 표의 각 행(구분/항목/사양값/비고)을 별도 chunk로도 저장해야 한다.

### 1.4 Embedding 모델
- `OllamaEmbeddings(model="bge-m3", base_url=...)` — 다국어/한국어 지원, 표 데이터에도 비교적 강함. 그대로 재사용.

### 1.5 Chroma 사용 방식
- 로컬 파일 기반 영속 저장 (`persist_directory="./chroma_db_specs"`), 컬렉션 분리 없이 단일 컬렉션.
- 메타데이터: `source`(파일명), `file_path`, `slide_number` 만 저장 — 항목 단위 메타데이터(카테고리/항목명 등)는 없음.

### 1.6 입력 데이터 형식
- 사용자 입력: 자유 자연어 1개 문자열(`SpecRequest.prompt`) 뿐. 구조화된 요구사항 개념이 없고, 필수 정보 누락 여부를 검증하지도 않는다 — LLM이 그냥 알아서 채워 넣는 구조.

### 1.7 PPTX 생성 방식
- `PPTXBuilder`: `template.pptx`를 열어 `{{TAG}}` 텍스트 치환 + 표가 있는 슬라이드에 행을 늘려가며 `spec_table` 데이터를 채운다.
- 표에 행을 추가하는 공개 API가 python-pptx에 없어서, 마지막 `<a:tr>` XML을 복제하는 방식으로 구현되어 있다 (`_add_table_row`) — 이번 세션에 발견/수정된 버그. **이 저수준 유틸리티는 그대로 재사용 가능**하다.
- 현재 템플릿은 2슬라이드(표지+개요 / 상세 표 1개)뿐이라, 이번 요구사항의 9개 섹션(Cover/General/Inspection Target/Measurement Performance/Inspection Performance/System/Interface/Environment/Notes)에는 부족하다.

### 1.8 현재 API 구조
- `POST /api/generate-spec` — 자연어 → RAG → JSON → PPTX 저장 → 다운로드 URL 반환 (동기, 1회 왕복)
- `POST /api/upload-specs` — PPTX 업로드 → `sample_specs/` 저장
- `GET /api/download/{file_name}`
- 전부 **1턴 completion형** API이고, "요구사항 확인 → 추가 질문 → 사용자 응답 → 최종 생성"처럼 여러 턴에 걸친 대화형 흐름은 없다.

### 1.9 현재 Frontend 구조
- FastAPI가 문자열로 HTML/CSS/JS를 직접 응답하는 방식 (템플릿 엔진 없음, React 등 없음).
- `main.py`에 `render_page(title, active_tab, body_html)` 공통 레이아웃 헬퍼가 있고, 상단 탭 네비게이션으로 페이지를 전환하는 구조가 이미 있다 (`/` 사양서 제작하기, `/upload` 사양서 업로드하기). **이번 Agent UI도 세 번째 탭으로 자연스럽게 추가 가능.**

### 1.10 기존 코드에서 재사용 가능한 부분
| 구성요소 | 재사용 방식 |
| --- | --- |
| `PPTXBuilder._replace_text_in_shape` / `_add_table_row` / `_populate_spec_table` | 그대로 호출. 새 Electrode 전용 빌더가 이 메서드들을 그대로 사용(상속)한다. |
| `build_rag_ollama.parse_pptx_file` | 그대로 재사용. 항목 단위 인덱싱 시 표 파싱 결과(행 단위)를 추가로 활용한다. |
| Chroma 연결/임베딩 설정 (`OllamaEmbeddings`, `Chroma(persist_directory=...)`) | 동일 DB(`chroma_db_specs`)를 그대로 사용. 새 컬렉션을 추가하지 않고 기존 컬렉션에 항목 단위 chunk를 추가로 넣는다. |
| `main.py`의 `render_page()` 공통 레이아웃/네비게이션 | 세 번째 탭(`/agent`)을 추가하는 형태로 확장. |
| `_clean_and_parse_json`의 마크다운 코드펜스 제거/trailing comma 보정 | 새 Agent의 구조화 출력 파서에도 동일하게 필요 (JSON Schema 강제 모드에서도 안전망으로 유지). |
| `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` 폐쇄망 설정 | 새 모듈 진입점에도 동일 적용. |
| 기존 `/`, `/upload`, `/api/generate-spec`, `/api/upload-specs` 라우트와 `SpecGenerator`/`PPTXBuilder` | **삭제/변경하지 않는다.** 새 Agent는 완전히 별도 모듈+라우트로 추가한다 (요구사항 19: 기존 기능 보존). |

## 2. 설계 결정 및 기존 계획서 대비 조정 사항

요구사항 문서의 Specification Schema는 필드가 매우 많다(9개 대분류, 각 5~10개 소분류). 모든 필드에 개별 `source/confidence`를 붙이면 스키마가 지나치게 비대해지고, 실제 RAG 데이터(현재 10개 샘플 사양서, PPTX 표 4열: 구분/항목/사양값/비고)의 정보 밀도와도 맞지 않는다. 따라서:

- **수치/성능 계열 필드**(measurement_performance, spatial_performance, inspection_performance, defect_detection)만 `SourcedValue[T]`(`value`, `unit`, `source_type`, `source`, `confidence`)로 감싸 근거 추적을 적용한다. 요구사항 문서 11절이 예로 든 필드들과 정확히 일치한다.
- **서술/분류 계열 필드**(equipment, inspection_target 일부, optical_system, system, interfaces, environment, safety)는 일반 값으로 두되, 사양서 최상위에 `sources: List[str]`(이번 생성에 참고한 문서 파일명 목록)를 별도로 남겨 "이 사양서가 어떤 문서들을 참고했는지"는 항상 추적 가능하게 한다.
- 이 결정은 요구사항 23절("근거를 추적할 수 있는가")의 핵심 취지—**수치가 어디서 왔는지 알 수 있어야 한다**—를 만족시키면서, 스키마를 실제로 유지보수 가능한 크기로 유지하기 위함이다.

Requirement 단계에서는 값이 없으면 반드시 `null`으로 유지하고(요구사항 8절), Specification 단계에서 `inferred`/`default`로 채워진 필드는 API 응답에 `needs_confirmation: List[str]`로 별도 안내해 UI가 "확인이 필요합니다" 배지를 띄울 수 있게 한다.

## 3. 신규 모듈 구조 (요청된 함수 기반 Pipeline)

```
agent/
├── __init__.py
├── schemas.py              # RequirementSchema, SpecificationSchema, SourcedValue, ValidationResult 등 Pydantic 모델
├── ollama_client.py         # Ollama 네이티브 REST API(JSON Schema structured output) 클라이언트. env var 기반 설정
├── requirement_parser.py    # 자연어/조건선택 → RequirementSchema  (RequirementParser)
├── requirement_validator.py # 누락 필드 탐지 + 확인 질문 생성       (RequirementValidator)
├── spec_retriever.py        # 항목 단위 RAG 검색                    (SpecRetriever)
├── spec_generator.py        # Requirement + 검색결과 → SpecificationSchema (SpecificationGenerator)
├── spec_validator.py        # Schema/Unit/Range/Logical/Source/Requirement 검증 (SpecificationValidator)
├── pptx_electrode_builder.py# SpecificationSchema → PPTX (기존 PPTXBuilder 유틸 재사용/상속)
└── pipeline.py               # 위 모듈을 순서대로 호출하는 오케스트레이션 함수
```

기존 `generator.py`, `pptx_builder.py`, `main.py`, `build_rag_ollama.py`는 **삭제/치환하지 않고 그대로 둔 채** 위 `agent/` 패키지를 새로 추가하고, `main.py`에는 새 라우트(`/agent`, `/api/agent/*`)만 추가한다.

## 4. Ollama 모델 설정

`.env` (신규, `.env.example`로 커밋):
```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
EMBEDDING_MODEL=bge-m3
AGENT_PORT=8000
```
RTX 4080 16GB 기준으로 `qwen2.5:14b`(4bit, ~9GB VRAM)는 이미 적정 크기이며 기존 기획안에서도 채택된 값이므로 **모델을 바꿀 이유가 없다** — 다만 하드코딩을 없애고 `OLLAMA_MODEL` 환경변수로 뺀다. 더 빠른 응답이 필요하면 `qwen2.5:7b`로, 더 높은 품질이 필요하면 서버 메모리가 허용하는 한 `qwen2.5:32b`(4bit, ~20GB)까지 환경변수만 바꿔 테스트해볼 수 있음을 README에 안내한다.

## 5. 테스트 전략 (Ollama가 없는 환경)

이 개발 환경에는 Ollama가 없으므로, 각 Phase마다:
1. `ollama_client`의 HTTP 호출부만 모킹해 나머지 로직(파싱/검증/검색/PPTX)을 실제로 실행·검증한다.
2. 요청서 18절의 테스트 케이스 3종을 고정 스텁 응답으로 파이프라인에 통과시켜 end-to-end 배선을 검증한다.
3. 실제 Ollama 응답 품질(모델이 스키마를 얼마나 잘 지키는지)은 사내 서버에서 최종 확인이 필요하다는 점을 README/요약에 명시한다.

## 6. 작업 순서

Phase 1(본 문서) → Phase 2(Schema) → Phase 3(Parser) → Phase 4(Validator) → Phase 5(Retriever) → Phase 6(Generator) → Phase 7(Validator) → Phase 8(PPTX) → Phase 9(UI) → Phase 10(통합 테스트) → Phase 11(README). 각 Phase 종료 시 실행 결과를 요약한다.

## 7. Phase별 실행 결과 요약 (실제 진행 기록)

| Phase | 산출물 | 검증 방법 | 결과 |
| --- | --- | --- | --- |
| 2. Schema | `agent/schemas.py` | `model_json_schema()` 생성, 인스턴스 생성/직렬화 | ✅ |
| 3. Parser | `agent/ollama_client.py`, `agent/requirement_parser.py` | `langchain_community.llms.Ollama.format`이 문자열만 지원함을 실제로 확인 후, Ollama REST `/api/generate`에 JSON Schema를 직접 전달하는 방식으로 구현 | ✅ (LLM 자체 응답 품질은 미검증 — 아래 8절 참고) |
| 4. Requirement Validator | `agent/requirement_validator.py` | 값 미채움/필드 누락 탐지, 요청서 8절 예시 재현 | ✅ |
| 5. Retriever | `agent/spec_retriever.py` | 실제 `sample_specs/` 10개 파일을 행 단위(40개 chunk)로 인덱싱 → 다중 질의 검색까지 실제 Chroma로 실행 (임베딩 계산만 가짜 벡터로 대체) | ✅ |
| 6. Generator | `agent/spec_generator.py` | 사용자값 사전 채움이 LLM 결과로 덮어써지지 않는지, needs_confirmation/sources 자동 계산 확인 | ✅ |
| 7. Specification Validator | `agent/spec_validator.py` | 반복성>정확도, 요구사항 미충족 등 위반 케이스가 실제로 issue로 잡히는지 확인 | ✅ |
| 8. PPTX | `make_electrode_template.py`, `agent/pptx_electrode_builder.py` | 생성된 PPTX를 다시 열어 9개 슬라이드 전부 올바른 섹션에 올바른 값이 들어갔는지 셀 단위로 확인 | ✅ |
| 9. UI | `main.py`(`/agent` 라우트), `agent/routes.py` | Playwright로 자연어 입력 → 추가 질문 응답 → 사양서 생성 → PPTX 다운로드까지 실제 브라우저 조작으로 스크린샷 확인 | ✅ |
| 10. 통합 테스트 | `tests/test_agent_pipeline.py` | 요청서 18절 테스트 케이스 3종 포함 8개 pytest 케이스 | ✅ 전부 통과 |
| 11. README | `README.md` | 환경변수/실행 순서/테스트 방법 문서화 | ✅ |

## 8. 이 환경에서 검증하지 못한 것 (사내 서버에서 확인 필요)

Ollama가 설치되어 있지 않은 개발 환경이라 아래는 실제로 돌려보지 못했다. `agent.ollama_client.parse_structured` 호출부만 스텁으로 대체하고 나머지 로직은 전부 실제로 실행/검증했지만, 다음은 사내 서버(Ollama + qwen2.5:14b + bge-m3)에서 반드시 재확인해야 한다:

1. **JSON Schema 구조화 출력의 실제 정확도** — `qwen2.5:14b`가 복잡한 중첩 스키마(SpecificationSchema)를 얼마나 정확히, 얼마나 빠르게 채우는지.
2. **응답 속도** — 사양서 1건 생성에 실제로 몇 초가 걸리는지 (RAG 검색 다중 질의 + 구조화 출력 특성상 기존 단일 질의 방식보다 느려질 수 있음).
3. **RAG 검색 품질** — `bge-m3` 실제 임베딩으로 항목 단위 검색이 실제로 관련 있는 결과를 얼마나 잘 찾아내는지 (이 환경에서는 결정론적 가짜 벡터로 "배선"만 검증했다).
4. **소스 문서가 적을 때의 동작** — 현재 `sample_specs/`에는 전극 검사 관련 샘플 10개뿐이라, 실제 사내 축적 문서가 많아졌을 때의 검색 품질/속도는 별도 확인이 필요하다.
