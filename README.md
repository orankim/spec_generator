# ⚙️ 전극 검사기 사양서 자동 생성 AI Agent
UI 참고주소 : https://www.figma.com/design/QRNWDbhr13LFWet7fjMW6f/260623_ChatBot_Templet?node-id=0-1&t=uLadrg4OEaRCoV7w-1
로컬 LLM(Ollama)과 RAG(검색 증강 생성)를 활용해, 자연어(또는 조건 선택)로 전극 검사기
요구사항을 입력하면 사내 사양 데이터(Markdown 기반)를 검색하고, 후보 장비의 hard
requirement(측정 범위/정확도/검사 모드/측정 방식/측정 원리) 충족 여부를 **Python
코드로 결정론적으로 판정**한 뒤, 근거(source)를 추적할 수 있는 표준 Specification을
생성해 Markdown 문서로 출력해 주는 폐쇄망 전용 웹 애플리케이션입니다.

사용자에게 노출되는 기능은 **전극 검사기 AI**(`/agent`) 하나뿐입니다. 예전에 있었던
"사양서 제작하기"(`/`)/"사양서 업로드하기"(`/upload`) 탭은 제거되었습니다 — 아래
"📂 프로젝트 폴더 구조" 절의 레거시 모듈 안내 참고.

## 📌 주요 특징

- **100% On-Premise / 폐쇄망 지원**: 외부 인터넷 연결 없이 사내 서버 PC(Ollama)에서 독자 구동. `agent/chroma_store.py`가 `chromadb`를 직접 사용해(`langchain_chroma` 미사용) Windows 사내 PC의 애플리케이션 제어 정책이 차단하는 `xxhash` 네이티브 DLL 의존성을 원천적으로 회피합니다 (아래 "폐쇄망 Windows PC에서 xxhash DLL 차단 문제" 절 참고).
- **Markdown 기반 RAG**: 사내 사양서 원본은 `sample_specs/*.md` — heading(`#`/`##`) 구조를 그대로 chunk 경계로 사용해 항목 단위 검색 정확도를 높입니다. PPTX 원본도 함께 스캔할 수 있습니다(레거시 지원).
- **결정론적 요구사항 구조화**: "0~200 μm 측정 범위와 ±1 μm 이하 정확도" 같은 표현을 LLM 품질에 의존하지 않고 정규식/단위 파싱(`agent/units.py`)으로 직접 구조화합니다(`agent/requirement_parser.py`). 소형 LLM이 이 값을 놓쳐도 코드가 보강합니다.
- **LLM 환각(hallucination) 방지**: 최초 자연어 파싱 직후에는 raw_text에 실제 근거가 있는 값이 항상 LLM의 결과를 덮어씁니다 — 근거가 없으면 LLM이 뭘 채웠든 지웁니다(`apply_deterministic_extraction(trust_llm_guess=False)`). 예: "1~500 μm"를 LLM이 "0~500000"으로 잘못 채워도 원문 재검증으로 교정되고, 사용자가 언급하지 않은 정확도를 LLM이 지어내면 삭제됩니다. 반면 추가 질문에 대한 사용자의 직접 답변(팔로우업)은 절대 덮어쓰지 않습니다.
- **한글 텍스트 정규화(NFC/NFD) 안정성**: 자연어 키워드 매칭(양극/음극/분리막 등)이 Unicode 정규화 형태 차이(다른 앱에서 복사한 텍스트가 자모 분해형으로 들어오는 경우 등)에 흔들리지 않도록, 매칭 전에 항상 NFC로 정규화합니다.
- **Hard Requirement PASS/FAIL을 LLM이 아니라 Python 코드로 판정**: `agent/candidate_matcher.py`가 RAG 검색 결과를 문서(장비) 단위로 그룹화하고, 각 후보의 측정 범위/정확도뿐 아니라 검사 모드(Inline/Offline)·측정 방식(Contact/Non-contact)·측정 원리(OCT/Laser/Interferometry/Vision/Spectral Reflectometry 등)까지 원문에서 직접 추출해 요구 조건을 만족하는지(`agent/units.py`/`agent/categorical_match.py`의 순수 함수) 판정합니다. PASS 후보가 최종 사양 생성에 우선 반영되고, 하나라도 FAIL이면 화면에 "조건을 모두 충족하는 장비를 찾지 못했습니다" 경고가 표시됩니다.
- **Requirement/Specification 분리 + Source 추적**: 사용자가 원하는 조건(Requirement)과 장비가 실제 제공하는 사양(Specification)을 분리 유지하고, 값마다 `USER_DEFINED`/`VERIFIED`/`INFERRED`/`UNKNOWN` 상태와 근거 문서(`source.document`/`chunk_id`)를 남깁니다. LLM이 `VERIFIED`라고 주장해도 실제 검색 문서와 대조해 근거가 없으면 자동으로 `INFERRED`로 강등합니다.
- **요구값 vs 장비 실측값 구분 표시**: 사용자가 요구한 정확도(`accuracy_um`, 보호됨)와 후보 장비에서 실제로 확인된 정확도(`equipment_accuracy_um`)를 별도 필드로 분리해, 화면에 "요구 정확도"/"장비 정확도"/"판정(PASS/FAIL)"을 명확히 구분해서 보여줍니다.
- **자동 검증**: Schema/단위/범위/논리/근거/요구사항 충족 여부를 `agent/spec_validator.py`가 검사해 결과를 화면에 보여줍니다 (파이프라인을 막지 않고 사용자가 판단하도록 보여주기만 합니다).
- **불필요한 LLM context 최소화**: 사양서 생성 시 후보 장비 판정(`candidate_matcher`)을 LLM 호출보다 먼저 수행해, 선택된 후보 문서의 chunk만 프롬프트에 실어 보냅니다 — 관련 없는 문서까지 매번 전부 보내던 이전 방식보다 응답 속도가 빠르고 timeout이 덜 발생합니다.

## 🏗️ 시스템 아키텍처 / 파이프라인

```
[사내 사용자 PC (Web Browser)]
         │  http://<서버_IP>:8000  (접속 시 자동으로 /agent 로 이동)
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                          사내 서버 PC                              │
│  [FastAPI Web Server (main.py)] ──► [/agent 페이지 + /api/agent/*]  │
│                                          │                         │
│   1. RequirementParser   (agent/requirement_parser.py)             │
│        └ 자연어(LLM) + 결정론적 정규식 추출, LLM 환각은 원문 재검증으로 교정 │
│   2. RequirementValidator (agent/requirement_validator.py)         │
│        └ 부족한 정보는 화면에서 먼저 되물음 (추측 금지)                │
│   3. SpecRetriever        (agent/spec_retriever.py)                 │
│        └ 의미 검색 + raw_text 질의 + range_boost + identity_chunk    │
│   4. CandidateMatcher     (agent/candidate_matcher.py)               │
│        └ 후보 장비 그룹화 + Range/Accuracy/Inspection Mode/Method/   │
│          Principle 등 hard requirement PASS/FAIL 판정(Python)        │
│   5. SpecificationGenerator (agent/spec_generator.py)                │
│        └ 선택된 후보의 chunk만 LLM에 전달(context 최소화) + 후보     │
│          실측값 반영 + source 검증/강등                              │
│   6. SpecificationValidator (agent/spec_validator.py)                │
│        └ 자동 검증 + Hard Requirement Report(요구 vs 실측 PASS/FAIL) │
│   7. Markdown Renderer    (renderers/markdown_renderer.py)           │
│        └ 표준 Markdown 사양서 생성 (generated_files/*.md)            │
│                                                                      │
│   [Chroma DB (chroma_db_specs, agent/chroma_store.py)]               │
│   [Ollama (LLM 추론 + bge-m3 임베딩)]                                │
└──────────────────────────────────────────────────────────────────┘
```

> `generator.py`(SpecGenerator)/`pptx_builder.py`(PPTXBuilder)/`preprocess_specs.py`는
> 예전 "사양서 제작하기"/"사양서 업로드하기" 기능이 쓰던 레거시 모듈입니다. 사용자
> 화면에서는 제거됐지만 파일은 삭제하지 않았습니다. `agent/pptx_electrode_builder.py`
> (PPTX 출력, 회사 템플릿 지원)와 `renderers/`/`converters/`(범용 Specification JSON
> ↔ Markdown/HTML/PPTX 변환 도구)도 코드베이스에는 그대로 남아 있으며, 회사 표준
> 사양서 양식이 정해지면 Markdown 결과를 PPTX로 자동 변환하는 기능을 추가할 예정입니다
> — 현재 웹 UI의 기본 출력 형식은 **Markdown**입니다(PPTX 템플릿 파일은 회사 기밀정보를
> 포함할 수 있어 저장소에 커밋할 수 없고, 템플릿 없이도 항상 안정적으로 결과를 만들고
> 검증하기 쉬운 Markdown을 우선 채택했습니다).

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
spec_generator/
├── sample_specs/               # [입력] RAG 원본 사양서 폴더. 기본 형식은 Markdown(.md) — heading(#/##) 구조를 chunk 경계로 사용
├── chroma_db_specs/            # [생성] RAG용 Vector DB 저장 폴더 (agent/paths.py 기준 저장소 루트 절대경로)
├── generated_files/            # [생성] 사용자가 다운로드할 완성된 사양서 저장 폴더 (기본: Markdown *.md, 필요 시 PPTX도 가능)
├── template_electrode.pptx     # (선택) 전극 검사기 Agent 전용 마스터 템플릿 — 없어도 python-pptx로 기본 생성됨
├── build_rag_ollama.py         # RAG Vector DB 구축 스크립트 (Markdown 우선, PPTX도 함께 스캔)
├── debug_rag.py                # RAG 검색 문제(0개 검색 등) 독립 진단 스크립트
├── scripts/
│   └── rag_diagnostics.py      # RAG 빌드↔검색 설정 일치 여부 진단 CLI
├── main.py                     # FastAPI 웹 서버 + UI (/agent 단일 기능)
├── agent/                      # 전극 검사기 사양서 자동 생성 AI Agent (함수 기반 파이프라인, LangChain Agent 미사용)
│   ├── schemas.py                 # RequirementSchema / SpecificationSchema (Pydantic) — SourcedNumber/SourcedRange로 근거 추적
│   ├── units.py                   # 단위 변환/파싱/수치형 hard requirement PASS·FAIL 판정 (순수 함수, LLM 미사용)
│   ├── categorical_match.py       # Inline/Offline·Contact/Non-contact·측정 원리 등 범주형 값 키워드 정규화/매칭 (순수 함수, LLM 미사용)
│   ├── paths.py                   # cwd 무관 저장소 루트 기준 경로 상수 (DB 경로 불일치 버그 방지)
│   ├── chroma_store.py            # chromadb 직접 래핑 (langchain_chroma 미사용 — xxhash DLL 문제 회피)
│   ├── ollama_client.py           # Ollama JSON Schema 구조화 출력 REST 클라이언트 (설정 가능한 timeout, 제한된 재시도, 상세 디버그 로그)
│   ├── requirement_parser.py      # 자연어/조건선택 -> RequirementSchema (LLM + 결정론적 수치/범주형 추출 + hallucination 필터 + NFC 정규화)
│   ├── requirement_validator.py   # 누락 필드 탐지 + 확인 질문 생성 (추측 금지)
│   ├── spec_retriever.py          # 다중 질의 RAG 검색 + range_boost + identity_chunk 보강
│   ├── candidate_matcher.py       # 후보 장비 그룹화 + Range/Accuracy/Inspection Mode/Measurement Method/Principle hard requirement PASS/FAIL 판정 (Python 코드, LLM 미개입)
│   ├── spec_generator.py          # Requirement + 검색결과 + 후보 판정 -> SpecificationSchema (선택된 후보로 LLM context 축소, source 검증/강등 포함)
│   ├── spec_validator.py          # Schema/Unit/Range/Logical/Source 검증 + Hard/Compliance Report
│   ├── pptx_electrode_builder.py  # SpecificationSchema -> PPTX (템플릿 있으면 사용, 없으면 기본 생성; 현재 웹 UI에서는 미사용, 코드는 유지)
│   ├── pipeline.py                # 위 모듈을 순서대로 호출하는 오케스트레이션
│   └── routes.py                  # /api/agent/* FastAPI 라우트 (analyze-requirement / generate-spec / build-markdown)
├── renderers/ , converters/ , templates/adapters/   # [범용, CLI 전용] Specification JSON ↔ Markdown/HTML/PPTX (renderers/markdown_renderer.py는 웹 UI의 build-markdown이 재사용)
├── docs/
│   ├── SPECIFICATION_SCHEMA.md            # Requirement/Specification 스키마 문서
│   └── SPECIFICATION_MARKDOWN_FORMAT.md   # 표준 Markdown 포맷 문서 (renderers/converters용)
├── tests/                       # pytest 테스트 (Ollama 없이 임베딩/LLM 응답만 스텁, 나머지는 실제 코드 경로 실행) — 210개
├── generator.py / pptx_builder.py / preprocess_specs.py   # [레거시] 예전 "사양서 제작하기/업로드하기"가 쓰던 모듈, 삭제하지 않고 유지
├── .env.example                 # 환경변수 설정 예시
├── requirements.txt             # 의존성 패키지 목록
└── README.md
```

## 🚀 빠른 시작 가이드 (Quick Start)

### 1. 가상환경 세팅 및 패키지 설치 (Windows PowerShell 기준)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser   # 최초 1회

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> 💡 `Fatal error in launcher` 오류가 나면 `pip` 대신 `python -m pip` 형태로 설치하세요.

### 2. Ollama 모델 확인

```powershell
ollama list
```

필수 모델: LLM 추론용 1개(예: `qwen2.5:14b`, 사내 PC 성능에 맞춰 `.env`의 `OLLAMA_MODEL`로 교체 가능) + 임베딩용 `bge-m3`.

### 3. RAG 데이터 준비 (`sample_specs/*.md`)

RAG 원본 데이터는 **Markdown(.md)이 기본 형식**입니다. `sample_specs/` 폴더에 사양서
Markdown 파일을 넣습니다(파일명 자유, `*.md`를 전부 스캔). 각 파일은 `#`(H1, 구분)과
`##`(H2, 개별 항목)로 섹션을 나눠 작성하면 `build_rag_ollama.py`가 그 구조를 그대로
chunk 경계로 사용합니다(파일 전체를 한 chunk로 넣지 않습니다). 수치 성능은 표
(`| Item | Specification |`) 형식으로, 제조사/모델/검사 모드/측정 방식/측정 원리는
`## General` 절의 불릿 목록(`- Manufacturer: ...`)으로 적으면 `agent/candidate_matcher.py`가
hard requirement 판정 시 이를 직접 파싱합니다.

```markdown
# Equipment Specification

## General
- Manufacturer: OptiScan
- Model: ES-200
- Equipment Type: Electrode 3D Inspection System
- Measurement Principle: 3D Laser Profilometry
- Inspection Mode: Inline
- Measurement Type: Non-contact

## Measurement Performance

| Item | Specification |
|---|---|
| Measurement Range (Z) | 0 ~ 200 μm |
| Accuracy | ±1.0 μm |
```

PPTX 원본을 계속 쓰고 싶다면 `sample_specs/`에 `.md`와 `.pptx`를 함께 두어도 됩니다 —
`build_rag_ollama.py`는 두 형식을 모두 스캔해서 함께 인덱싱합니다(단, RAG 구축이 더는
PPTX 파일의 존재를 요구하지 않습니다).

### 4. RAG Vector DB 구축

```powershell
python build_rag_ollama.py --input-dir sample_specs
```

기존 DB를 지우고 새로 만들려면:

```powershell
python build_rag_ollama.py --input-dir sample_specs --db-path ./chroma_db_specs --rebuild
```

- `--input-dir` : 사양서 폴더 (`.md`/`.pptx` 모두 스캔, 기본값 `./sample_specs`)
- `--db-path` : Vector DB 저장 폴더 (기본값 `./chroma_db_specs`, `agent/paths.py` 기준 저장소 루트 절대경로)
- `--rebuild` : 실행 전 기존 Vector DB를 삭제하고 새로 구축

임베딩 모델/Ollama 서버 주소는 `.env`의 `EMBEDDING_MODEL`/`OLLAMA_HOST`를 따르며,
`agent/spec_retriever.py`(검색 쪽)와 `agent.spec_retriever.get_embeddings()` 하나만
공유합니다 — 두 곳에 각자 하드코딩된 값을 두면 벡터 공간이 어긋나 검색이 조용히
실패하므로, 빌드/검색이 항상 동일한 설정을 쓰도록 강제되어 있습니다.

### 5. 서버 실행

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
# 또는: python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

- 서버 PC 접속: http://localhost:8000
- 사내망 접속: http://<서버PC_IP_주소>:8000

접속하면 바로 **전극 검사기 AI**(`/agent`) 화면으로 이동합니다.

> 💡 사내망에서 예전 주소로 접속이 안 될 때: 서버 PC가 재부팅되면서 IP가 자동으로
> 다시 할당되는 환경이라면, 서버 PC의 IP 주소 자체가 바뀌었을 수 있습니다. 서버 PC에서
> `ipconfig`로 현재 IP를 확인하세요(원인이 방화벽이 아니라 옛날 주소로 찾아가고
> 있는 경우가 흔합니다). 반복을 피하려면 서버 PC에 고정 IP를 할당하는 것을 권장합니다.

## 🔬 전극 검사기 AI 사용 흐름

```
자연어 입력 (또는 조건 선택)
        ↓
"AI가 이해한 요구사항" 확인 — 검사 대상/폭/검사 항목/측정 범위/요구 정확도/측정 방식/측정 원리/검사 모드
        ↓
정보가 부족하면 추가 질문 → 답변 입력 → 재검증 (반복)
        ↓
사내 사양서 RAG 검색 → 후보 장비 hard requirement PASS/FAIL 판정 → Specification 생성
        ↓
자동 검증 결과 + 사용자 요구조건 검증(Hard Requirement PASS/FAIL) + "AI 추정값" 확인 항목 표시
   (하나라도 FAIL이면 "조건을 모두 충족하는 장비를 찾지 못했습니다" 경고 배너 표시)
        ↓
Markdown 사양서 생성 (generated_files/electrode_inspection_spec_*.md)
```

예를 들어 "양극 폭 100 mm의 두께를 0~200 μm 범위에서 ±1 μm 이하 정확도로 측정할 수
있는 Inline 비접촉식 검사기를 찾아줘."라고 입력하면:

**1단계 — AI가 이해한 요구사항**

```
검사 대상: 양극        폭: 100 mm       검사 항목: thickness
측정 범위: 0 ~ 200 μm   요구 정확도: ±1 μm 이하
측정 방식: 비접촉        측정 원리: 미정        검사 모드: Inline
```

**3단계 — 생성된 사양서 + 요구조건 검증**

```
설비명: OptiScan ES-200
측정 범위: 0 ~ 200 μm (VERIFIED, SPEC-001.md)
요구 정확도: ±1 μm 이하        장비 정확도: 1 μm (VERIFIED, SPEC-001.md)

사용자 요구조건 검증 (Hard Requirement)
  [Measurement Range]    요구 범위 0~200um / 장비 범위 0~200um → PASS
  [Accuracy]              요구 정확도 <= 1um / 장비 정확도 1um → PASS
  [Inspection Mode]       요구 Inline / 장비 Inline → PASS
  [Measurement Method]    요구 Non-contact / 장비 Non-contact → PASS

참고 문서: SPEC-001.md   ← 실제 근거가 있는 문서만 우선 표시
```

## 🧠 핵심 설계 원칙

- **Agent Framework 미사용**: LangChain/LangGraph 없이 `agent/` 아래 평범한 Python 함수 파이프라인으로 구현했습니다(`agent/pipeline.py`).
- **판단이 필요한 곳은 LLM이 아니라 코드로**:
  - 측정 범위/정확도 구조화: `agent/units.py`의 정규식/단위 파싱(`parse_range_with_span`, `parse_value_unit_with_span`)이 raw_text에서 직접 추출합니다 — LLM이 놓쳐도 코드가 보강합니다(`agent/requirement_parser.py:apply_deterministic_extraction`).
  - 검사 모드/측정 방식/측정 원리 구조화: `agent/categorical_match.py`가 Inline/Offline, Contact/Non-contact, OCT/Laser/Interferometry/Vision/Spectral Reflectometry 등을 대소문자·공백·하이픈 차이 없이 키워드 매칭으로 정규화합니다. 요구사항 쪽과 후보 문서 쪽에서 동일한 함수를 재사용해 항상 같은 canonical 값으로 비교할 수 있게 합니다.
  - **LLM 환각 방지**: 최초 자연어 파싱 직후(`parse_requirement_text`) 딱 한 번, raw_text에 실제 근거가 있는 값이 LLM의 결과를 무조건 덮어씁니다 — 근거가 없으면 LLM이 채운 값도 지웁니다. 반면 추가 질문 팔로우업(`existing_requirement` 경로)에서는 사용자가 직접 입력한 값을 절대 덮어쓰지 않습니다.
  - **Hard Requirement PASS/FAIL**: `agent/units.py:evaluate_hard_requirements`/`range_covers`(수치형)와 `agent/categorical_match.py`(범주형)가 "장비의 측정 범위가 요구 범위를 포함하는가", "장비의 정확도/검사 모드/측정 방식/측정 원리가 요구 조건을 만족하는가"를 순수 함수로 판정합니다. `agent/candidate_matcher.py`가 이 함수들을 사용해 후보 장비를 PASS 우선으로 선정합니다 — LLM은 이 판정에 전혀 관여하지 않습니다.
  - Source 검증: LLM이 `status="VERIFIED"`라고 주장해도, 실제 검색된 문서 원문에 그 수치가 있는지 코드로 재대조합니다(`agent/spec_generator.py:_verify_sourced_numbers`). 확인되지 않으면 `INFERRED`로 자동 강등됩니다.
- **값을 추측하지 않음**: 사용자가 말하지 않은 값은 `null`로 남기고, 정보가 부족하면 화면에서 추가 질문을 먼저 던집니다(`agent/requirement_validator.py`). LLM이 사용자가 언급하지 않은 검사 항목(예: `surface_defect`)을 임의로 추가하면 raw_text 근거를 확인해 걸러냅니다.
- **텍스트 정규화 안정성**: 한글 키워드 매칭은 Unicode 정규화 형태(NFC/NFD) 차이에 흔들리지 않도록 매칭 직전 항상 NFC로 정규화합니다 — 다른 문서에서 복사한 단어를 붙여넣었을 때도 안정적으로 인식됩니다.
- **요구값과 실측값을 혼동하지 않음**: `measurement_performance.accuracy_um`(사용자가 요구한 값, `USER_DEFINED`로 보호되어 LLM이 덮어쓸 수 없음)과 `equipment_accuracy_um`(후보 장비에서 실제로 확인된 값, `VERIFIED`+근거 문서)은 서로 다른 필드입니다. `equipment.inline_offline`/`equipment.measurement_method`/`equipment.measurement_principle`도 마찬가지로 "선택된 후보 장비에서 실제로 확인된 값"만 담습니다.
- **근거 추적**: 수치 성능 필드는 `SourcedNumber{value, unit, operator, status, source, reasoning}` 구조로, 어떤 문서/chunk에서 가져왔는지(`source.document`/`chunk_id`) 또는 AI가 추정한 값인지(`INFERRED`, `reasoning` 포함)를 함께 저장합니다. 범위형 필드는 `SourcedRange{min, max, unit, status, source}`를 씁니다. 추정값은 `needs_confirmation` 목록으로 모아 화면에서 확인을 요구합니다.
- **참고 문서는 실제 근거만**: `Specification.sources`(검색된 문서 전체)와 별도로 `Specification.primary_sources`(실제로 `VERIFIED`된 필드의 근거 문서만)를 계산해 UI에 우선 노출합니다 — 관련 없는 문서 10개를 무조건 나열하지 않습니다.
- **적합/부적합 구분을 명확히 표시**: Hard Requirement 중 하나라도 FAIL이면 화면 상단에 "조건을 모두 충족하는 장비를 찾지 못했습니다" 경고를 표시해, FAIL 후보를 마치 조건을 만족한 추천 장비처럼 오인하지 않도록 합니다.
- **LLM에게 불필요한 정보를 주지 않음**: 사양서 생성 시 후보 판정(`candidate_matcher`)을 LLM 호출 전에 먼저 수행하고, 최종적으로 선택된 후보 문서의 chunk만 프롬프트에 담습니다 — RAG 검색/후보 매칭 자체는 문서 전체를 계속 보되, LLM에게 넘기는 컨텍스트만 좁혀 응답 속도를 높이고 timeout 위험을 줄입니다.

## 🧩 Requirement / Specification 스키마 개요

`agent/schemas.py` (자세한 필드 목록은 `docs/SPECIFICATION_SCHEMA.md` 참고):

| 개념 | 역할 |
| --- | --- |
| `RequirementSchema` | 사용자가 원하는 조건. `target`(검사 대상), `inspection_items`, `measurement_range`(`RequirementRange: min/max/unit`), `accuracy`(`RequirementValue: value/unit/operator`), `inline_offline`(`inline`/`offline`), `measurement_method`(`non_contact`/`contact`), `measurement_principle`(자유 문자열, 예: `OCT`/`Spectral Reflectometry`) 등. `required_accuracy_um` 같은 레거시 float 필드는 `sync_legacy_fields()`로 구조화 필드와 항상 동기화됩니다. |
| `SpecificationSchema` | 장비의 실제/제안 사양. `Status = USER_DEFINED \| VERIFIED \| INFERRED \| UNKNOWN` 4단계로 값의 신뢰도를 명시합니다. `Equipment.inline_offline`/`measurement_method`/`measurement_principle`은 선택된 후보 장비에서 실제로 확인된 값만 담습니다. |
| `SourcedNumber` / `SourcedRange` | 근거가 있는 수치/범위 필드. `source: SourceRef{document, chunk_id, section, ...}`로 어느 문서의 어느 chunk에서 왔는지 추적합니다. |
| `CandidateEquipment` / `CandidateFieldMatch` | `agent/candidate_matcher.py`가 만드는 후보 장비 단위 평가 결과. Range/Accuracy(수치형, `requirement_value`/`found_value`)와 Inspection Mode/Measurement Method/Measurement Principle(범주형, `requirement_text`/`found_text`) 항목별 PASS/FAIL/UNKNOWN과 근거를 담습니다. |
| `ComplianceRecord` | Requirement vs Specification 항목별 비교 결과(`agent/spec_validator.py:build_hard_requirement_report`). `/api/agent/generate-spec` 응답의 `hard_requirement_report`로 노출됩니다. |

## 🔍 RAG 파이프라인 상세 (`agent/spec_retriever.py`)

`retrieve_for_requirement()`는 단일 유사도 검색이 아니라 여러 신호를 병합합니다.

1. **의미 기반 질의**: `target.material`/`inspection_items`로 만든 질의(예: "음극 검사 설비", "음극 두께 측정 두께 정확도 두께 분해능").
2. **원문 질의(raw_text)**: 사용자의 원본 문장을 항상 추가 질의로 포함합니다 — material/inspection_items가 이미 있어도 원문의 구체적 수치("0~200 μm")가 의미 질의만으로는 상위 k에 들지 못할 수 있기 때문입니다.
3. **range_boost**: raw_text에서 파싱한 범위 조건(예: "0~200 μm")을 실제로 포함하는 chunk를 의미 검색 순위와 무관하게 컬렉션 전체에서 찾아 강제로 포함시킵니다(`agent.units.range_covers` 재사용).
4. **identity_chunk**: 검색 결과에 이미 포함된 문서의 "General"(제조사/모델) chunk를 별도로 함께 끌어와, 성능 수치만 검색되고 정작 장비명 정보가 빠지는 것을 방지합니다.

기본 `k_per_query=5`이며, 결과는 `(source, content 앞부분)` 기준으로 중복 제거됩니다.
이렇게 검색된 문서 전체는 후보 판정(hard requirement PASS/FAIL)에 계속 쓰이지만,
사양서 생성 LLM 호출에는 **최종 선택된 후보 문서의 chunk만** 전달됩니다(위 "핵심 설계
원칙" 참고).

## 🩺 진단 도구

- `python scripts/rag_diagnostics.py` : ChromaDB 내용/설정 일치 여부/생성되는 검색 질의/실제 검색 결과를 단계별로 출력합니다. "검색 결과 0개" 같은 문제를 코드 추측이 아니라 실제 값으로 확인할 때 사용하세요.
- `python debug_rag.py` : 더 포괄적인 RAG 독립 진단(빌드↔검색 설정, 원본 파일 vs 색인된 chunk 비교 등).

두 스크립트 모두 사내 Ollama가 켜진 환경에서 실행해야 실제 임베딩 결과를 확인할 수 있습니다.

Ollama 호출 자체가 느리거나 timeout이 발생하면, 서버 로그에서 `[LLM DEBUG]`/`[LLM
TIMEOUT]`로 시작하는 줄을 확인하세요 — 모델명, 프롬프트 길이(문자 수), 실제 LLM에게
전달된 참고 문서 chunk 개수, timeout 설정값, 소요 시간이 함께 기록됩니다.

## 🛠️ 환경변수 설정

`.env.example`을 복사해 `.env`로 만듭니다.

```powershell
copy .env.example .env
```

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
EMBEDDING_MODEL=bge-m3
# OLLAMA_TIMEOUT=180
AGENT_PORT=8000
LOG_LEVEL=INFO
# CHROMA_DB_PATH=./chroma_db_specs
# ELECTRODE_TEMPLATE_PATH=./template_electrode.pptx
```

`OLLAMA_MODEL`만 바꾸면 다른 LLM으로 교체할 수 있습니다(코드 변경 불필요).
`OLLAMA_TIMEOUT`은 `/api/generate` 구조화 출력 호출의 read timeout(초)입니다 — 느린
하드웨어나 reasoning 모델(deepseek-r1 등) 사용 시 늘려야 할 수 있습니다(비워두면
기본값 180). PPTX를 회사 지정 양식으로 출력하고 싶다면(현재 웹 UI는 Markdown을
기본으로 생성하며, PPTX 생성 경로는 코드에 남아 있지만 UI에서 직접 연결되어 있지는
않습니다) `ELECTRODE_TEMPLATE_PATH`로 템플릿 경로를 지정하세요.

> **PPTX 템플릿 파일은 회사 기밀정보를 포함할 수 있으므로 이 저장소에 커밋하지 않습니다.**

## 🧪 테스트

이 개발 환경에는 Ollama가 없어 LLM 추론 자체는 검증하지 못합니다.
`OllamaEmbeddings.embed_*`/`ollama_client.parse_structured`/`requests.post`만
결정론적 스텁으로 대체하고, 나머지(Markdown 파싱/chunking, ChromaDB 색인/검색,
range_boost/identity_chunk, hard requirement PASS/FAIL 판정, source 검증/강등,
사양서 검증 규칙, Markdown/PPTX 생성)는 실제 코드 경로 그대로 실행해서 검증합니다.

```powershell
python -m pip install pytest numpy
python -m pytest tests/ -v
```

현재 총 **210개** 테스트가 통과합니다. 주요 테스트 파일:

| 파일 | 검증 대상 |
| --- | --- |
| `test_units.py` | 단위 변환/파싱/`evaluate_hard_requirements` 순수 함수 |
| `test_requirement_structuring.py` | 요구사항 원문 → measurement_range/accuracy 결정론적 구조화 |
| `test_requirement_target_extraction.py` | target.material/width_mm 결정론적 추출 |
| `test_width_range_disambiguation.py` | width_mm 값이 measurement_range로 잘못 재사용되지 않는지 |
| `test_material_extraction_ai_understood_screen.py` | material 추출 + Unicode(NFC/NFD) 정규화 안정성 |
| `test_llm_hallucination_and_categorical_hardreq.py` | LLM 환각 방지 정책 + Inspection Mode/Measurement Method/Measurement Principle hard requirement |
| `test_source_verification.py` | RAG 검색 보강(range_boost/identity_chunk) + VERIFIED source 검증/강등 |
| `test_candidate_matcher.py` | 후보 장비 hard requirement PASS/FAIL 판정 + 실제 SPEC-001.md 기반 end-to-end |
| `test_sample_specs_full_coverage.py` | sample_specs 10개 문서 전체에 대한 라벨 인식/후보 선택 회귀 |
| `test_markdown_rag.py` | Markdown chunking/색인/검색 (PPTX 없이도 동작) |
| `test_agent_pipeline.py` | Requirement/Specification Validator + 통합 파이프라인 시나리오 |
| `test_integration_verification.py` | RAG/RequirementParser/Hard Requirement/Specification 생성 통합 검증 |
| `test_build_markdown_route.py` | `/api/agent/build-markdown` 라우트 + 다운로드 media_type |
| `test_ollama_timeout_handling.py` | Ollama timeout/재시도/LLM context 축소/디버그 로그 |
| `test_renderers.py` | Specification JSON ↔ Markdown/HTML/PPTX 렌더러(범용, CLI 전용) |
| `test_no_xxhash_dependency.py` | `agent/chroma_store.py` 경로가 `xxhash`/`langsmith`를 로드하지 않는지 확인 |

**사내 서버에서 반드시 추가로 확인할 것**: 실제 LLM이 구조화 출력 요청 시 얼마나
정확하게 필드를 채우는지, 응답 속도는 이 환경에서 검증할 수 없었습니다 — 다만 위
"핵심 설계 원칙"에 정리된 대로, 측정 범위/정확도/검사 모드/측정 방식/측정 원리
구조화와 hard requirement PASS/FAIL 판정은 LLM 품질과 무관하게 코드가 보장합니다.

## 🛡️ 폐쇄망 Windows PC에서 xxhash DLL 차단 문제

일부 사내 Windows PC의 애플리케이션 제어 정책이 `xxhash`의 네이티브 확장(`_xxhash`)
DLL 로드를 차단해 `build_rag_ollama.py` 실행 시 `ImportError: DLL load failed while
importing _xxhash`가 발생할 수 있습니다. 원인은 `langchain_chroma`를 import하면
`langchain_core.tracers.context` → `langsmith` → `xxhash`까지 전부 로드되기
때문입니다(LangSmith는 이 프로젝트가 쓰지 않는 별도 트레이싱 SaaS 클라이언트).

`agent/chroma_store.py`(`SimpleChromaStore`)가 `langchain_chroma.Chroma` 대신
`chromadb`를 직접 사용하도록 대체해 이 문제를 해결했습니다 — `chromadb`는
`xxhash`/`langsmith`에 의존하지 않음을 확인했습니다. `requirements.txt`에서
`xxhash`를 단순히 지워서 문제를 숨기지 않고, 근본적으로 그 패키지를 로드하는
경로 자체를 없앴습니다. `langchain-chroma`는 레거시 모듈(`generator.py`/
`preprocess_specs.py`)이 여전히 쓰므로 `requirements.txt`에서 완전히 빼지는
않았습니다.

## 🛠️ 자주 발생하는 오류 및 해결 방법

### 1. `Fatal error in launcher` 오류

```powershell
python -m pip install -r requirements.txt

# 가상환경 재생성 (필요시)
deactivate
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. `스크립트를 실행할 수 없으므로...` (PowerShell 보안 정책)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. RAG 검색 결과가 0개로 나올 때

`python scripts/rag_diagnostics.py` 또는 `python debug_rag.py`를 실행해 ChromaDB
경로/설정 불일치, collection이 비어 있는지, 임베딩 차원 불일치 등을 단계별로
확인하세요. `CHROMA_DB_PATH`를 명시하지 않았다면 `agent/paths.py`가 cwd와 무관하게
저장소 루트 기준 절대경로를 쓰므로, 빌드와 검색이 서로 다른 디렉터리를 가리키는
문제는 발생하지 않습니다.

### 4. 사양서 생성 단계에서 Ollama read timeout이 발생할 때

먼저 서버 로그의 `[LLM DEBUG]` 줄에서 `context_chunks`(LLM에 전달된 참고 문서
개수)와 `prompt_chars`(프롬프트 길이)를 확인하세요. `agent/spec_generator.py`가
이미 선택된 후보 문서의 chunk만 전달하도록 되어 있어 비정상적으로 크지는 않아야
합니다. 그래도 timeout이 반복되면 `.env`의 `OLLAMA_TIMEOUT`을 늘리거나, 서버
하드웨어 성능(위 "권장 서버 하드웨어 사양" 참고) 또는 사용 중인 모델의 크기를
재검토하세요.

### 5. 예전에 되던 사내망 주소가 갑자기 안 될 때

브라우저에 "이 사이트에 연결할 수 없음"/"응답 시간 초과"가 뜬다면, 방화벽 차단보다
**서버 PC의 IP 주소가 바뀐 경우**가 흔한 원인입니다(재부팅 시 IP가 자동 재할당되는
사내망 환경). 서버 PC에서 `ipconfig`로 현재 IP를 확인하고, 그 주소로 다시 접속해
보세요. 반복을 막으려면 서버 PC에 고정 IP를 할당하는 것을 권장합니다.

## 🛡️ 사내 방화벽 설정 안내

사내 다른 직원 PC에서 웹 접속이 안 될 경우, 서버 PC의 윈도우 방화벽 인바운드 규칙에서
8000번 포트(TCP)를 허용하도록 설정하세요.

## 🔒 폐쇄망(완전 오프라인) 환경 설치 가이드

인터넷이 연결된 외부 PC에서 아래 자료를 미리 준비한 뒤, USB 등으로 사내 폐쇄망 서버
PC에 이관합니다.

### 1. Python 패키지 오프라인 이관

```powershell
# (외부 PC) 프로젝트에 필요한 wheel 파일을 모두 다운로드
python -m pip download -r requirements.txt -d ./offline_wheels

# (폐쇄망 서버 PC) 네트워크 접속 없이 wheel 폴더에서 설치
python -m pip install --no-index --find-links=./offline_wheels -r requirements.txt
```

### 2. Ollama 모델 오프라인 이관

외부 PC에서 필요한 모델을 `ollama pull`한 뒤 생성되는 모델 데이터 폴더(`blobs`,
`manifests`)를 통째로 복사하여 폐쇄망 서버 PC의 동일 Ollama 데이터 경로에
붙여넣습니다.

### 3. 외부 네트워크 통신 완전 차단

`main.py`, `build_rag_ollama.py` 실행 시 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
환경변수를 자동으로 설정하여, LangChain/ChromaDB 관련 라이브러리가 HuggingFace Hub
등 외부로 통신을 시도하지 않도록 차단합니다. 필요 시 시스템 환경변수로도 동일하게
설정해 이중으로 보안을 강화할 수 있습니다.
