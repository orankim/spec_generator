# ⚙️ 사내망 설비 사양서 자동 생성 시스템 (Spec PPTX Generator)

로컬 LLM과 RAG(검색 증강 생성) 기술을 활용하여, 기존 사내 PPT 사양서 데이터를 기반으로 자연어 요구사항에 맞는 표준 PPTX 사양서를 자동 생성해 주는 폐쇄망 전용 웹 애플리케이션입니다.

## 📌 주요 특징

- **100% On-Premise / 폐쇄망 지원**: 외부 인터넷 연결 및 데이터 유출 없이 사내 서버 PC에서 독자 구동
- **RAG 기반 사양 정교화**: 기존 PPT 사양서(표/텍스트)를 Vector DB에 저장하여 전문 엔지니어링 용어 및 수치 반영
- **Structured JSON-to-PPTX**: LLM 환각(Hallucination) 및 레이아웃 깨짐 방지를 위해 JSON 구조화 데이터 추출 후 python-pptx 백엔드로 파워포인트 자동 합성
- **웹 UI 제공**: 사내 사용자 누구나 웹 브라우저 접속을 통해 사양서 생성 및 다운로드 가능
- **전극 검사기 사양서 AI Agent**: 자연어(또는 조건 선택)로 요구사항을 입력하면, 부족한 정보를 먼저 되물어 확인한 뒤 사내 사양서를 검색해 근거를 추적할 수 있는 표준 Specification JSON을 만들고, 자동 검증을 거쳐 9섹션 PPTX 사양서를 생성한다 (`/agent`, 자세한 설계는 아래 "전극 검사기 AI Agent" 절과 `IMPLEMENTATION_PLAN.md` 참고)

## 🏗️ 시스템 아키텍처

```
[사내 사용자 PC (Web Browser)]
         │
         ▼ (사내 LAN 접속: http://<서버_IP>:8000)
┌────────────────────────────────────────────────────────┐
│                      사내 서버 PC                       │
│                                                        │
│   [FastAPI Web Server (main.py)]                       │
│         │                                              │
│         ├──► [SpecGenerator (generator.py)]            │
│         │         │                                    │
│         │         ├─► [Chroma DB (chroma_db_specs)]    │
│         │         └─► [Ollama (qwen2.5:14b / bge-m3)]  │
│         │                                              │
│         └──► [PPTXBuilder (pptx_builder.py)]           │
│                   │                                    │
│                   └─► [Template Engine (template.pptx)]│
└────────────────────────────────────────────────────────┘
```

## 🖥️ 권장 서버 하드웨어 사양

| 항목 | 사양 |
| --- | --- |
| CPU | AMD Threadripper Pro 5965WX (24 Cores) 이상 권장 |
| GPU | NVIDIA GeForce RTX 4080 (VRAM 16GB) 이상 필수 |
| RAM | 64GB 이상 |
| OS | Windows 11 / Windows Server / Ubuntu Linux |
| Python | 3.11 이상 |

## 📂 프로젝트 폴더 구조

```
spec-generator/
├── sample_specs/              # [입력] RAG 원본 사양서 폴더. 기본 형식은 Markdown(.md) — PPTX(.pptx)가 섞여 있어도 함께 인덱싱됨
├── sample_specs_normalized/   # [생성] 전처리를 거쳐 표준 템플릿 형식으로 정규화된 PPTX 저장 폴더 (PPTX 원본을 쓸 때만 필요)
├── chroma_db_specs/           # [생성] RAG용 Vector DB 저장 폴더
├── generated_files/           # [생성] 사용자가 다운로드할 완성된 PPTX 저장 폴더
├── .venv/                     # Python 가상환경 폴더
├── template.pptx              # 마스터 PPTX 템플릿 파일 (범용 2슬라이드)
├── template_electrode.pptx    # 전극 검사기 Agent 전용 9섹션 마스터 템플릿
├── preprocess_specs.py        # 0단계: 형식이 제각각인 기존 사양서를 표준 템플릿으로 정규화(전처리)
├── build_rag_ollama.py        # 1단계: 사양서 Markdown(기본)/PPTX(레거시) 파싱 및 Vector DB 구축 스크립트
├── generator.py                # 2단계: RAG 검색 및 Ollama 기반 사양서 JSON 생성/추출 모듈
├── pptx_builder.py             # 3단계: JSON 데이터를 PPTX 템플릿에 채워넣는 모듈
├── make_template.py            # [보조] 테스트용 template.pptx 자동 생성 스크립트
├── make_electrode_template.py  # [보조] template_electrode.pptx 자동 생성 스크립트
├── main.py                     # 4단계: FastAPI 웹 서버 및 UI 메인 실행 파일 (탭 3개: 제작/업로드/전극검사기AI)
├── agent/                      # 전극 검사기 사양서 자동 생성 AI Agent (신규, 함수 기반 파이프라인)
│   ├── schemas.py               # RequirementSchema / SpecificationSchema (Pydantic) — 변경 없음
│   ├── ollama_client.py         # Ollama JSON Schema 구조화 출력 REST 클라이언트
│   ├── requirement_parser.py    # 자연어/조건선택 -> RequirementSchema
│   ├── requirement_validator.py # 누락 필드 탐지 + 확인 질문 생성 (추측 금지)
│   ├── spec_retriever.py        # 항목(행) 단위 RAG 검색 + 인덱서
│   ├── spec_generator.py        # Requirement + 검색결과 -> SpecificationSchema
│   ├── spec_validator.py        # Schema/Unit/Range/Logical/Source/Requirement 검증
│   ├── pptx_electrode_builder.py# (기존 PPTX Generator, 변경 없음) 템플릿 있을 때 renderers/pptx_renderer.py가 재사용
│   ├── pipeline.py              # 위 모듈을 순서대로 호출하는 오케스트레이션
│   └── routes.py                 # /api/agent/* FastAPI 라우트
├── renderers/                   # [신규] Specification JSON -> {Markdown, HTML, PPTX} (Single Source of Truth)
│   ├── common.py                 # 세 포맷이 공유하는 섹션/필드 모델 (라벨-필드 매핑의 유일한 소스)
│   ├── markdown_renderer.py      # render_markdown(spec) -> specification.md
│   ├── html_renderer.py          # render_html(spec) -> specification.html (외부 CDN 미사용)
│   └── pptx_renderer.py          # render_pptx(spec) -> PPTX (템플릿 있으면 재사용, 없으면 코드로 기본 생성)
├── converters/                   # [신규] PPTX <-> Markdown/Specification 변환
│   ├── document_ir.py             # PPTX 파싱용 중간 표현 (Document/Slide/Table)
│   ├── pptx_to_markdown.py        # 임의 PPTX -> Markdown (문서 보존용, Specification과 무관)
│   └── markdown_to_spec.py        # 표준 Specification Markdown -> SpecificationSchema
├── templates/adapters/           # [신규] 회사별 PPT 템플릿 연결 확장점 (실제 템플릿 파일은 git에 넣지 않음)
│   ├── base.py                    # TemplateAdapter 인터페이스
│   └── env_path_adapter.py        # PPT_TEMPLATE_PATH 환경변수로 템플릿 경로를 주는 기본 어댑터
├── docs/
│   └── SPECIFICATION_MARKDOWN_FORMAT.md  # 표준 Markdown 포맷 문서
├── cli_commands.py               # [신규] `python main.py render-md/render-html/render-pptx/pptx-to-md/md-to-spec` 구현
├── tests/
│   ├── test_agent_pipeline.py   # Agent 파이프라인 pytest 테스트 (기존, 변경 없음 — 계속 통과해야 함)
│   └── test_renderers.py         # [신규] 렌더러/변환기 테스트 (Test 1~10 + 회귀 테스트)
├── IMPLEMENTATION_PLAN.md      # 기존 코드 분석 + Agent 설계 문서 (작업 시작 전 필독)
├── .env.example                 # 환경변수 설정 예시 (복사해서 .env로 사용, PPT_TEMPLATE_PATH 포함)
├── requirements.txt             # 의존성 패키지 목록
└── README.md                    # 프로젝트 안내 문서
```

## 🚀 빠른 시작 가이드 (Quick Start)

### 1. VS Code PowerShell 가상환경 세팅 및 패키지 설치

**A. PowerShell 스크립트 실행 권한 허용 (최초 1회)**

VS Code 터미널(PowerShell)에서 가상환경 활성화 스크립트가 막히지 않도록 권한을 허용합니다.

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**B. 가상환경 생성 및 활성화**

```powershell
# 프로젝트 폴더 이동 후 가상환경 생성
python -m venv .venv

# 가상환경 활성화 (PowerShell)
.\.venv\Scripts\Activate.ps1
```

(성공 시 터미널 입력창 맨 앞에 `(.venv)` 표시가 생깁니다.)

> 💡 **VS Code 자동 연동 팁**: `Ctrl + Shift + P` → `Python: Select Interpreter` 검색 → `.\.venv\Scripts\python.exe`를 선택해 두면 이후 터미널을 열 때마다 가상환경이 자동 활성화됩니다.

**C. 필수 라이브러리 설치**

`Fatal error in launcher` 같은 실행 파일 경로 오류를 방지하기 위해 `python -m pip` 형태로 설치합니다.

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Ollama 모델 확인 (로컬 실행 중이어야 함)

터미널에서 Ollama에 필수 모델이 들어있는지 확인합니다.

```powershell
ollama list
```

필수 모델: `qwen2.5:14b` (LLM 추론용), `bge-m3` (임베딩용)

### 3. 테스트용 마스터 템플릿 생성

```powershell
python make_template.py
```

(실제 운영 시에는 디자인된 사내 표준 `template.pptx` 파일로 교체하세요.)

전극 검사기 AI Agent(`/agent`)를 쓰려면 9섹션 전용 템플릿도 한 번 생성해야 합니다.

```powershell
python make_electrode_template.py
```

### 4. (필요 시) 기존 PPTX 사양서 전처리 — 표준 템플릿으로 정규화

이 단계는 **원본 사양서가 PPTX일 때만** 필요합니다. Markdown 원본(권장, 아래 5번 참고)을
쓴다면 건너뛰어도 됩니다. 사내에 흩어져 있던 기존 사양서 PPTX들은 레이아웃이 표준 양식과
다른 경우가 대부분입니다. `sample_specs/`에 그 원본 파일들을 넣고 아래를 실행하면, 각
파일의 내용을 LLM으로 읽어 표준 `template.pptx` 형식에 맞춰 재작성한 뒤
`sample_specs_normalized/`에 저장합니다. (원본은 그대로 보존되며, 추출에 실패한 파일은
건너뛰고 마지막에 실패 목록으로 안내합니다.)

```powershell
python preprocess_specs.py
```

- `--input` : 원본 PPTX 폴더 (기본값 `./sample_specs`)
- `--output` : 정규화 결과 저장 폴더 (기본값 `./sample_specs_normalized`)

### 5. RAG 데이터 준비

RAG 원본 데이터는 **Markdown(.md)을 기본 형식**으로 한다. `sample_specs/` 폴더에 사양서
Markdown 파일을 넣는다 (파일명은 자유 — `spec_01.md`처럼 번호를 매기거나
`spec_electrode_coating_thickness.md`처럼 내용을 알 수 있는 이름을 써도 된다. `*.md`를
전부 스캔하므로 이름 규칙에 의존하지 않는다).

```
sample_specs/
├── spec_01.md
├── spec_02.md
├── ...
└── spec_10.md
```

각 Markdown 파일은 heading으로 섹션/항목을 구분해서 작성한다 — `#`(H1)는 구분(카테고리),
`##`(H2)는 개별 항목이며, `build_rag_ollama.py`가 이 구조를 그대로 chunk 경계로 사용한다
(파일 전체를 하나의 chunk로 넣지 않는다).

```markdown
# 기본 정보
## 설비명
전극 두께 검사기 XYZ-100
## 제조사
ACME Metrology

# 측정 성능
## 측정 범위
0 ~ 200 μm
## 정확도
±0.5 μm

# 검사 성능
## 검출 속도
...
```

PPTX 원본을 계속 쓰고 싶다면 `sample_specs/`에 `.md`와 `.pptx`를 함께 두어도 된다 —
`build_rag_ollama.py`는 두 형식을 모두 스캔해서 함께 인덱싱한다. 단, RAG 구축이 PPTX
파일의 존재를 더 이상 요구하지 않는다 — `.md`만 있어도 정상 동작한다.

### 6. RAG Vector DB 구축

```powershell
python build_rag_ollama.py --input-dir sample_specs
```

기존 DB를 지우고 완전히 새로 만들려면(예: PPTX를 삭제하고 Markdown만 남긴 뒤 재구축할 때):

```powershell
python build_rag_ollama.py --input-dir sample_specs --db-path ./chroma_db_specs --rebuild
```

- `--input-dir` : 사양서 폴더 (`.md`/`.pptx` 모두 스캔, 기본값 `./sample_specs`)
- `--db-path` : Vector DB 저장 폴더 (기본값 `./chroma_db_specs`)
- `--rebuild` : 실행 전 기존 Vector DB를 삭제하고 새로 구축 (예: 오래된 `.pptx` 기반 인덱스가 섞여 있을 때)

임베딩 모델/Ollama 서버 주소는 `.env`의 `EMBEDDING_MODEL`/`OLLAMA_HOST`를 따르며,
`agent/spec_retriever.py`(검색 쪽)와 반드시 같은 값을 공유한다 — 두 곳에 각자 하드코딩된
값을 두지 않는다.

### 7. Agent 실행 (사내망 서비스 개방)

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

(또는 기존 방식대로 `python main.py`도 동일하게 동작합니다.)

- 서버 PC 접속: http://localhost:8000
- 사내망 접속: http://<서버PC_IP_주소>:8000

웹 화면 상단 탭으로 세 페이지를 오갈 수 있습니다.
- **사양서 제작하기** (`/`): 자연어 요구사항으로 새 사양서 PPTX 생성 (기존 기능)
- **사양서 업로드하기** (`/upload`): 클라이언트 PC에서 기존 사양서 PPTX를 서버로 업로드 → `sample_specs/`에 저장. 업로드만으로는 검색에 바로 반영되지 않으며, 서버 관리자가 `python preprocess_specs.py` → `python build_rag_ollama.py`를 실행해야 RAG 검색에 반영됩니다.
- **전극 검사기 AI** (`/agent`, 신규): 아래 절 참고

## 🔬 전극 검사기 사양서 자동 생성 AI Agent

`/agent` 페이지에서 아래 순서로 동작합니다.

```
자연어 입력 또는 조건 선택
        ↓
Requirement 확인 (AI가 이해한 내용을 먼저 보여줌)
        ↓
정보가 부족하면 추가 질문 → 답변 입력 → 재검증 (반복)
        ↓
사내 사양서 RAG 검색 + Specification 생성
        ↓
자동 검증 결과 + "AI 추정값" 확인 항목 표시
        ↓
PPTX 사양서 생성 (generated_files/electrode_inspection_spec_*.pptx)
```

핵심 설계는 `IMPLEMENTATION_PLAN.md`에 자세히 기록되어 있으며, 요약하면:

- **Agent Framework 미사용**: LangChain/LangGraph 없이 `agent/` 아래 평범한 Python 함수 파이프라인(`RequirementParser → RequirementValidator → SpecRetriever → SpecificationGenerator → SpecificationValidator → PPTXBuilder`)으로 구현했습니다.
- **LLM은 JSON만, PPTX는 파이썬이 생성**: `agent/ollama_client.py`가 Ollama의 네이티브 구조화 출력(JSON Schema 기반 `format`)을 사용해 Pydantic 스키마를 그대로 강제합니다. PPTX 생성은 `agent/pptx_electrode_builder.py`(순수 python-pptx)가 담당합니다.
- **값을 추측하지 않음**: 사용자가 말하지 않은 값은 `null`로 남기고, 정보가 부족하면 화면에서 추가 질문을 먼저 던집니다. 사용자가 명시한 값은 이후 LLM이 절대 덮어쓰지 않습니다(코드로 강제).
- **근거 추적**: 수치 성능 필드(정확도/분해능/결함크기 등)는 `{value, unit, source_type, source, confidence}` 구조로, 어떤 문서에서 가져왔는지 또는 AI가 추정한 값인지(`inferred`/`default`)를 함께 저장합니다. 추정값은 `needs_confirmation` 목록으로 모아 화면에서 확인을 요구합니다.
- **자동 검증**: Schema/단위/범위/논리/근거/요구사항 충족 여부를 `agent/spec_validator.py`가 검사해 결과를 화면에 색상별로 보여줍니다 (막지는 않고, 사용자가 판단할 수 있게 보여주기만 합니다).

### 환경변수 설정

`.env.example`을 복사해 `.env`로 만들고 필요한 값을 채우세요 (없어도 아래 기본값으로 동작합니다).

```powershell
copy .env.example .env
```

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
EMBEDDING_MODEL=bge-m3
AGENT_PORT=8000
```

RTX 4080 16GB 기준 `qwen2.5:14b`(4bit, ~9GB VRAM)가 기본값이며, 다른 모델로 바꾸려면 `.env`의 `OLLAMA_MODEL`만 수정하면 됩니다(코드 변경 불필요).

### 항목 단위 RAG 검색 보강 (선택)

기존 `build_rag_ollama.py`는 PPTX 슬라이드 전체를 1개 chunk로 인덱싱합니다. 전극 검사기 Agent는 "정확도가 얼마인가" 같은 **항목 단위 검색**이 더 정확하도록, 표의 각 행(구분/항목/사양값/비고)을 별도 chunk로도 색인하는 보강 인덱서를 제공합니다 (기존 슬라이드 단위 색인은 그대로 두고 "추가"만 합니다).

```powershell
python -c "from agent.spec_retriever import index_spec_rows_from_folder; index_spec_rows_from_folder('sample_specs_normalized', db_path='./chroma_db_specs')"
```

### 테스트

이 개발 환경에는 Ollama가 없어 LLM 추론 자체는 검증하지 못했습니다. `agent.ollama_client`의 구조화 출력 호출만 스텁으로 대체하고, 나머지(요구사항 검증 규칙, RAG 인덱싱/검색, 사용자값 보존 병합 로직, 사양서 검증 규칙, PPTX 생성)는 실제 코드 경로로 테스트했습니다. 요청서 18절의 테스트 케이스 3종도 포함되어 있습니다.

```powershell
python -m pip install pytest numpy
python -m pytest tests/ -v
```

**사내 서버에서 반드시 추가로 확인할 것**: `qwen2.5:14b`가 실제로 JSON Schema 구조화 출력 요청 시 얼마나 정확하게 필드를 채우는지, 그리고 응답 속도(사양서 1건 생성에 걸리는 시간)는 이 환경에서 검증할 수 없었습니다.

## 🧩 Specification JSON 중심 아키텍처 (Markdown / HTML / PPTX)

**PPTX 템플릿 파일은 회사 기밀정보를 포함할 수 있어 이 저장소에 커밋하지 않습니다.**
그래서 PPTX를 "Specification의 원본 포맷"이 아니라 "여러 출력 포맷 중 하나"로 바꿨습니다. 시스템의
Single Source of Truth는 항상 **Specification JSON**이고, Markdown/HTML/PPTX는 전부 거기서
파생되는 독립적인 렌더러입니다.

```
Requirement Parser → Specification Generator → Specification Validator → Specification JSON
                                                                                │
                                                          ┌─────────────────────┼─────────────────────┐
                                                          ▼                     ▼                     ▼
                                                       Markdown                HTML                 PPTX
                                                  (renderers/          (renderers/          (renderers/
                                                 markdown_renderer)    html_renderer)      pptx_renderer)
```

**PPTX ↔ AI ↔ PPTX 처럼 포맷을 반복 변환해서 데이터를 유지하는 구조는 의도적으로 만들지 않았습니다.**
항상 Specification JSON을 중심에 두고 각 포맷이 거기서 한 방향으로 파생됩니다.

### 언제든 템플릿 없이도 전체가 동작합니다

`renderers/pptx_renderer.py`는 `PPT_TEMPLATE_PATH`(또는 `.env`)가 가리키는 파일이 있으면 기존
`agent/pptx_electrode_builder.py`(변경 없음)를 그대로 써서 회사 양식대로 PPTX를 만들고, 없으면
코드로 즉석에서 기본 PPTX를 생성합니다. **Schema 검증 / Markdown 생성 / HTML 생성 / Agent
파이프라인 전체는 템플릿 파일의 존재 여부와 무관하게 항상 정상 동작합니다.**

> **PPTX template files may contain company confidential information.**
> **Do not commit company templates to the repository.**
> **Configure the template path locally using `PPT_TEMPLATE_PATH`.**

```env
# .env (커밋하지 않음)
PPT_TEMPLATE_PATH=C:\Company\Templates\electrode_spec.pptx
```

여러 회사/여러 템플릿을 구분해서 연결해야 한다면 `templates/adapters/`에 `TemplateAdapter`를
구현해서 확장할 수 있습니다 (`templates/adapters/env_path_adapter.py`가 가장 단순한 예시).

### CLI

웹 UI 없이 터미널에서 Specification JSON을 바로 렌더링/변환할 수 있습니다. `python main.py`를
인자 없이 실행하면 기존과 동일하게 웹 서버가 뜨고, 아래 서브커맨드를 붙이면 그 명령만 실행하고
종료합니다 (서버는 뜨지 않습니다).

```powershell
python main.py render-md specification.json        # -> specification.md
python main.py render-html specification.json      # -> specification.html
python main.py render-pptx specification.json      # -> specification.pptx (템플릿 있으면 사용)
python main.py render-pptx specification.json --template C:\Company\Templates\electrode_spec.pptx
python main.py pptx-to-md sample_specs/some_file.pptx   # 임의 PPTX 내용을 마크다운으로 보존
python main.py md-to-spec specification.md          # 표준 포맷 마크다운 -> specification.json
```

### 표준 Markdown 포맷

`renderers/markdown_renderer.py`가 만들고 `converters/markdown_to_spec.py`가 되돌리는 포맷은
`docs/SPECIFICATION_MARKDOWN_FORMAT.md`에 문서화되어 있습니다. **임의의 마크다운을 일반적으로
파싱하지 않고, 우리가 정의한 이 표준 포맷만 대상으로 합니다.**

### PPTX → Markdown (문서 보존용, Specification과는 별개)

기존에 흩어져 있는 임의 형식의 PPTX를 읽어보기 좋은 텍스트로 보존하고 싶을 때 씁니다 (제목/텍스트/표/
슬라이드 노트/슬라이드 번호를 보존하고, 이미지는 메타데이터만 남깁니다 — OCR/의미분석은 범위 밖).
`preprocess_specs.py`(기존, LLM으로 Specification을 추출)와는 다른 목적입니다 — 이건 LLM 없이
순수 파싱만 합니다.

```powershell
python main.py pptx-to-md sample_specs/spec_electrode_coating_thickness.pptx
```

## 🛠️ 자주 발생하는 오류 및 해결 방법

### 1. `Fatal error in launcher` 오류 발생 시

파이썬 경로 변경이나 가상환경 손상 시 발생합니다. `pip` 대신 `python -m pip`을 사용해 설치하거나 가상환경을 재생성합니다.

```powershell
# 우회 설치
python -m pip install -r requirements.txt

# 가상환경 재생성 (필요시)
deactivate
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. `스크립트를 실행할 수 없으므로...` 에러 발생 시

PowerShell 보안 정책 에러입니다. 권한 변경 명령을 실행해 주세요.

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 🛡️ 사내 방화벽 설정 안내

사내 다른 직원 PC에서 웹 접속이 안 될 경우, 서버 PC의 윈도우 방화벽 인바운드 규칙에서 8000번 포트(TCP)를 허용하도록 설정하세요.

## 🔒 폐쇄망(완전 오프라인) 환경 설치 가이드

인터넷이 연결된 외부 PC에서 아래 자료를 미리 준비한 뒤, USB 등으로 사내 폐쇄망 서버 PC에 이관합니다.

### 1. Python 패키지 오프라인 이관

```powershell
# (외부 PC) 프로젝트에 필요한 wheel 파일을 모두 다운로드
python -m pip download -r requirements.txt -d ./offline_wheels

# (폐쇄망 서버 PC) 네트워크 접속 없이 wheel 폴더에서 설치
python -m pip install --no-index --find-links=./offline_wheels -r requirements.txt
```

### 2. Ollama 모델 오프라인 이관

외부 PC에서 `ollama pull qwen2.5:14b`, `ollama pull bge-m3` 실행 후 생성되는 모델 데이터 폴더(`blobs`, `manifests`)를 통째로 복사하여 폐쇄망 서버 PC의 동일 Ollama 데이터 경로에 붙여넣습니다.

### 3. 외부 네트워크 통신 완전 차단

본 프로젝트는 `main.py`, `build_rag_ollama.py` 실행 시 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` 환경변수를 자동으로 설정하여, LangChain/ChromaDB 관련 라이브러리가 HuggingFace Hub 등 외부로 통신을 시도하지 않도록 원천 차단합니다. 필요 시 시스템 환경변수로도 동일하게 설정해 이중으로 보안을 강화할 수 있습니다.
