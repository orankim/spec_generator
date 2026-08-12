# Electrode Inspection Specification Agent

전극 검사기 사양서를 대상으로 **자연어 요구사항 분석 → 관련 사양 검색 → 조건 비교 → 사양서 생성**을 자동화하기 위한 사내망용 AI Agent입니다.

Ollama 기반의 로컬 LLM과 RAG(Retrieval-Augmented Generation)를 사용하며, 외부 LLM API로 사내 사양 데이터를 전송하지 않는 것을 기본 방향으로 합니다.

> **Project Status: Prototype / Evaluation**
>
> 현재는 실제 사내 장비 사양서를 적용하기 전에 Synthetic Markdown 사양서를 이용하여 Agent의 요구사항 분석, RAG 검색, 사양 추출, 조건 검증 및 결과 생성 기능을 검증하는 단계입니다.

---

## 1. Project Overview

전극 검사기 사양서를 작성하거나 검토할 때 일반적으로 다음과 같은 작업이 필요합니다.

    기존 장비 사양서 검색
            ↓
    관련 사양 확인
            ↓
    요구조건과 비교
            ↓
    필요한 사양 정리
            ↓
    사양서 작성
            ↓
    PPT 작성

이 프로젝트에서는 이 과정을 AI Agent를 이용하여 자동화하는 것을 목표로 합니다.

    사용자 자연어 요구사항
            ↓
    Requirement Parsing
            ↓
    Requirement Validation
            ↓
    RAG Search
            ↓
    관련 장비/사양 검색
            ↓
    Specification Generation
            ↓
    Specification Validation
            ↓
    Markdown / HTML / PPTX

---

## 2. Core Concept

이 프로젝트에서 가장 중요한 개념은 **LLM이 사양값을 직접 생성하는 것이 아니라, 원본 사양 데이터를 검색하고 그 근거를 기반으로 결과를 생성하는 것**입니다.

전체 구조는 다음과 같습니다.

    ┌────────────────────┐
    │    User Query      │
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │ Requirement Parser │
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │ Requirement        │
    │ Validator          │
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │ RAG Retriever      │
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │ Specification      │
    │ Generator          │
    └─────────┬──────────┘
              │
              ▼
    ┌────────────────────┐
    │ Specification      │
    │ Validator          │
    └─────────┬──────────┘
              │
       ┌──────┼──────┐
       ▼      ▼      ▼
    Markdown HTML   PPTX

핵심 원칙:

1. 원본에 없는 값을 임의로 생성하지 않는다.
2. 숫자와 단위를 원본과 동일하게 유지한다.
3. 요구조건과 장비 사양을 명확하게 비교한다.
4. 정보가 없으면 `UNKNOWN`으로 처리한다.
5. 가능한 경우 결과의 출처를 추적한다.
6. LLM의 자연어 생성 능력보다 데이터의 정확성을 우선한다.

---

## 3. 주요 기능

### 3.1 자연어 Requirement Parsing

사용자가 자연어로 검사 요구사항을 입력할 수 있습니다.

예:

    배터리 전극 폭 500 mm를 검사할 수 있고
    Inline 방식이며
    측정 범위가 0~200 μm 이상이고
    정확도가 ±1 μm 이하인 장비를 찾아줘.

Agent는 이를 구조화된 Requirement로 변환합니다.

예:

    Inspection Target: Electrode
    Inspection Type: Inline
    Width: >= 500 mm
    Measurement Range: >= 200 μm
    Accuracy: <= 1 μm

---

### 3.2 조건 선택 방식

자연어 입력이 어려운 사용자를 위해 조건을 UI에서 직접 선택하는 방식도 지원할 수 있습니다.

예:

    검사 대상
    [ 전극 ▼ ]

    검사 방식
    [ Inline ▼ ]

    측정 원리
    [ 3D Laser ▼ ]

    측정 범위
    [ >= 200 ] [ μm ]

    Accuracy
    [ <= 1 ] [ μm ]

    Minimum Detectable Defect
    [ <= 20 ] [ μm ]

자연어 입력과 조건 선택 입력은 최종적으로 동일한 Requirement Schema를 사용합니다.

---

### 3.3 RAG 기반 사양 검색

장비 사양서를 Embedding하여 Vector DB에 저장하고, 사용자의 요구사항과 관련된 사양을 검색합니다.

    Specification Documents
            ↓
    Preprocessing
            ↓
    Chunking
            ↓
    Embedding
            ↓
    Vector Database
            ↓
    User Requirement
            ↓
    Similarity Search
            ↓
    Relevant Specifications

현재 Prototype에서는 Ollama를 이용한 로컬 Embedding과 Chroma 기반 Vector DB를 사용합니다.

---

### 3.4 Specification Generation

검색된 사양과 사용자의 Requirement를 기반으로 최종 Specification을 생성합니다.

예:

    Requirement
    Accuracy <= 1 μm

    Retrieved Specification
    Accuracy = ±0.8 μm

    Result
    PASS

여러 장비가 검색되는 경우 조건별로 비교하여 적합한 후보를 제시할 수 있도록 설계합니다.

---

### 3.5 PASS / FAIL 검증

단순히 LLM에게 판단을 맡기지 않고 가능한 경우 Python 기반 로직으로 수치와 조건을 검증합니다.

예:

    Requirement:
    Accuracy <= 1 μm

    Equipment:
    Accuracy = ±0.8 μm

    Result:
    PASS

반대로:

    Requirement:
    Accuracy <= 1 μm

    Equipment:
    Accuracy = ±3 μm

    Result:
    FAIL

---

### 3.6 단위 변환

서로 다른 단위가 사용되는 경우 비교를 위해 표준 단위로 변환합니다.

예:

    800 nm
        ↓
    0.8 μm

이를 통해 다음과 같은 조건을 올바르게 판단할 수 있습니다.

    Requirement:
    Accuracy <= 1 μm

    Specification:
    Accuracy = 800 nm

    Result:
    PASS

---

### 3.7 UNKNOWN 처리

원본 사양서에 존재하지 않는 정보는 임의로 추정하지 않습니다.

예:

    사양서:
    Accuracy = ±1 μm

    사용자:
    Repeatability는 얼마인가?

원본에 Repeatability 정보가 없다면:

    UNKNOWN

으로 처리해야 합니다.

다음과 같은 답변은 허용하지 않습니다.

    Repeatability = ±0.5 μm

즉, **Hallucination 방지**를 핵심 요구사항으로 합니다.

---

### 3.8 Source Traceability

가능한 경우 결과값의 근거를 원본 문서까지 추적합니다.

예:

    Accuracy
    ±0.8 μm

    Source
    SPEC-010.md
    Measurement Performance

향후 실제 PPTX 데이터를 적용할 경우:

    Source
    Vendor_A_Specification.pptx
    Slide 12
    Measurement Performance

와 같이 확장하는 것을 목표로 합니다.

---

# 4. System Architecture

전체 시스템은 다음과 같이 구성됩니다.

    ┌───────────────────────────────┐
    │        User Web Browser       │
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │         FastAPI Server        │
    │                               │
    │           main.py             │
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │         Agent Pipeline        │
    │                               │
    │  Requirement Parser           │
    │           ↓                   │
    │  Requirement Validator        │
    │           ↓                   │
    │  RAG Retriever                │
    │           ↓                   │
    │  Specification Generator      │
    │           ↓                   │
    │  Specification Validator      │
    └───────────────┬───────────────┘
                    │
            ┌───────┴────────┐
            ▼                ▼
    ┌───────────────┐  ┌───────────────┐
    │    Ollama     │  │   Chroma DB   │
    │               │  │               │
    │ LLM           │  │ Vector DB     │
    │ Embedding     │  │               │
    └───────────────┘  └───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐
    │            Output             │
    │                               │
    │ Markdown / HTML / PPTX        │
    └───────────────────────────────┘

---

# 5. Technology Stack

| Category | Technology |
|---|---|
| Language | Python |
| Web Framework | FastAPI |
| LLM Runtime | Ollama |
| LLM | Qwen2.5 14B |
| Embedding | BGE-M3 |
| Vector DB | Chroma |
| Data Format | Markdown / JSON |
| Output | Markdown / HTML / PPTX |
| Validation | Pydantic + Python Logic |

---

# 6. Recommended Hardware

현재 Prototype 실행 환경:

| Component | Specification |
|---|---|
| CPU | Multi-core CPU |
| RAM | 64 GB |
| GPU | NVIDIA GeForce RTX 4080 16 GB |
| OS | Windows 11 / Linux |
| Python | 3.11+ |

현재 사용 중인 **RAM 64 GB + GeForce RTX 4080** 환경에서 Prototype을 실행할 수 있습니다.

LLM 모델의 크기와 Context Length에 따라 GPU VRAM 사용량과 응답 속도가 달라질 수 있습니다.

---

# 7. Project Structure

현재 프로젝트의 주요 구조는 다음과 같습니다.

    spec_generator/
    │
    ├── agent/
    │   ├── schemas.py
    │   ├── ollama_client.py
    │   ├── requirement_parser.py
    │   ├── requirement_validator.py
    │   ├── spec_retriever.py
    │   ├── spec_generator.py
    │   ├── spec_validator.py
    │   ├── pipeline.py
    │   └── routes.py
    │
    ├── sample_specs/
    │   └── synthetic/
    │       ├── SPEC-001.md
    │       ├── SPEC-002.md
    │       ├── SPEC-003.md
    │       ├── SPEC-004.md
    │       ├── SPEC-005.md
    │       ├── SPEC-006.md
    │       ├── SPEC-007.md
    │       ├── SPEC-008.md
    │       ├── SPEC-009.md
    │       └── SPEC-010.md
    │
    ├── evaluation/
    │   └── ...
    │
    ├── chroma_db_specs/
    │
    ├── generated_files/
    │
    ├── main.py
    ├── build_rag_ollama.py
    ├── preprocess_specs.py
    ├── generator.py
    ├── pptx_builder.py
    ├── requirements.txt
    ├── .env.example
    └── README.md

---

# 8. Installation

## 8.1 Clone Repository

    git clone https://github.com/orankim/spec_generator.git
    cd spec_generator

이미 Repository를 다운로드한 경우 프로젝트 폴더로 이동합니다.

---

## 8.2 Create Python Virtual Environment

### Windows PowerShell

    python -m venv .venv

가상환경을 활성화합니다.

    .\.venv\Scripts\Activate.ps1

PowerShell 실행 정책 오류가 발생하는 경우:

    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

다시 실행합니다.

    .\.venv\Scripts\Activate.ps1

정상적으로 활성화되면 다음과 같이 표시됩니다.

    (.venv)

---

## 8.3 Install Python Packages

    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

`pip` 대신 `python -m pip` 사용을 권장합니다.

---

# 9. Ollama Setup

## 9.1 Install Ollama

서버 PC에 Ollama를 설치합니다.

설치 후 정상적으로 설치되었는지 확인합니다.

    ollama --version

설치된 모델을 확인합니다.

    ollama list

---

## 9.2 Install LLM

현재 기본 테스트 모델은 Qwen2.5 14B입니다.

    ollama pull qwen2.5:14b

실행 테스트:

    ollama run qwen2.5:14b

간단한 질문을 입력하여 응답이 정상적으로 생성되는지 확인합니다.

종료:

    /bye

---

## 9.3 Install Embedding Model

RAG 검색용 Embedding 모델을 설치합니다.

    ollama pull bge-m3

설치 확인:

    ollama list

예:

    NAME
    qwen2.5:14b
    bge-m3

`bge-m3`는 일반적인 텍스트 생성용 모델이 아니라 RAG 검색을 위한 Embedding 모델입니다.

---

# 10. Environment Configuration

`.env.example`을 복사하여 `.env`를 생성합니다.

Windows:

    copy .env.example .env

필요한 경우 `.env` 파일을 수정합니다.

예:

    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_MODEL=qwen2.5:14b
    OLLAMA_EMBED_MODEL=bge-m3

> 실제 프로젝트에서 사용하는 환경변수 이름은 최신 `.env.example`을 기준으로 확인합니다.

---

# 11. Test Dataset

현재 Agent의 초기 검증에서는 실제 사내 장비 사양서 대신 **Synthetic Markdown Specification Dataset**을 사용합니다.

구조:

    sample_specs/
    └── synthetic/
        ├── SPEC-001.md
        ├── SPEC-002.md
        ├── SPEC-003.md
        ├── SPEC-004.md
        ├── SPEC-005.md
        ├── SPEC-006.md
        ├── SPEC-007.md
        ├── SPEC-008.md
        ├── SPEC-009.md
        └── SPEC-010.md

이 데이터는 실제 제조사 또는 사내 장비 데이터가 아니라 **Agent 기능 검증을 위한 가상 테스트 데이터**입니다.

---

# 12. Build RAG Database

테스트용 사양서를 이용하여 Vector DB를 생성합니다.

    python build_rag_ollama.py

정상적으로 생성되면 다음과 같은 Vector DB 디렉터리가 생성됩니다.

    chroma_db_specs/

RAG DB를 다시 구축하는 경우 기존 데이터가 섞이지 않도록 기존 `chroma_db_specs/`를 백업하거나 삭제한 후 다시 생성하는 것을 권장합니다.

예:

    Remove-Item -Recurse -Force chroma_db_specs
    python build_rag_ollama.py

---

# 13. Run Web Application

웹 애플리케이션을 실행합니다.

    python main.py

정상적으로 실행되면 다음 주소에서 접속할 수 있습니다.

    http://localhost:8000

브라우저에서 접속합니다.

    http://localhost:8000

---

# 14. Remote Access in Internal Network

서버 PC에서 Agent를 실행하고 다른 사내 PC에서 웹 브라우저로 접속할 수 있습니다.

구조:

    ┌────────────────────────────┐
    │        Server PC           │
    │                            │
    │ FastAPI :8000              │
    │ Ollama  :11434             │
    │ Chroma DB                  │
    └─────────────┬──────────────┘
                  │
              Company LAN
                  │
          ┌───────┴───────┐
          │               │
          ▼               ▼
       User PC 1       User PC 2

사용자 PC에서는 별도의 Python이나 Ollama를 설치하지 않고 웹 브라우저를 통해 접속하는 것을 목표로 합니다.

서버 IP가 예를 들어 다음과 같다면:

    192.168.0.100

사용자는 다음 주소로 접속합니다.

    http://192.168.0.100:8000

> 실제 사내망에서 원격 접속하려면 Windows Firewall, 사내 방화벽 및 네트워크 정책에 따라 TCP 8000 포트 접근을 허용해야 할 수 있습니다.

---

# 15. Agent Usage

웹 UI에서 자연어로 검사 요구사항을 입력합니다.

예:

    500 mm 이상의 전극 폭을 검사할 수 있고
    Inline 방식이며
    측정 범위가 200 μm 이상이고
    정확도가 ±1 μm 이하인 장비를 찾아줘.

Agent는 다음과 같이 처리합니다.

    Natural Language
           ↓
    Requirement Parsing
           ↓
    Requirement Validation
           ↓
    RAG Retrieval
           ↓
    Specification Generation
           ↓
    Specification Validation
           ↓
    Result

---

# 16. Manual Testing

현재 단계에서는 자동 평가보다 **사용자가 직접 Agent 결과를 확인하는 방식**으로 검증합니다.

## Test 1. Basic Retrieval

질문:

    0~200 μm 이상의 측정 범위와
    ±1 μm 이하의 정확도를 만족하는 장비를 찾아줘.

확인할 항목:

- 관련 장비가 검색되는가?
- 검색된 장비의 사양이 원본과 일치하는가?
- 숫자가 정확한가?
- 단위가 정확한가?
- Source가 표시되는가?

---

## Test 2. Multiple Conditions

질문:

    500 mm 이상의 전극 폭을 검사할 수 있고
    Inline 방식이며
    정확도가 ±1 μm 이하이고
    20 μm 이하 크기의 결함을 검출할 수 있는 장비를 찾아줘.

확인할 조건:

    Width >= 500 mm

    Inspection Type = Inline

    Accuracy <= 1 μm

    Minimum Detectable Defect <= 20 μm

각 조건에 대해 PASS / FAIL / UNKNOWN이 정확하게 판단되는지 확인합니다.

---

## Test 3. UNKNOWN

질문:

    SPEC-006의 두께 측정 정확도를 알려줘.

원본 사양서에 해당 정보가 없다면:

    UNKNOWN

또는:

    해당 정보가 사양서에 없습니다.

와 같이 답변해야 합니다.

정보가 없는데 임의의 수치를 생성한다면 Hallucination 문제로 판단합니다.

---

## Test 4. Hallucination

질문:

    SPEC-001의 양극/음극 구분 정보를 알려줘.

원본에 해당 정보가 없다면 AI가 임의로 양극 또는 음극이라고 판단해서는 안 됩니다.

---

## Test 5. Unit Conversion

질문:

    정확도가 1 μm 이하인 장비를 찾아줘.

원본 사양서에 다음과 같이 다른 단위가 사용되어 있는 경우:

    800 nm

이를:

    0.8 μm

로 변환하여 조건을 올바르게 판단해야 합니다.

---

## Test 6. Boundary Condition

경계값 조건을 확인합니다.

질문:

    측정 범위가 정확히 200 μm인 장비도
    200 μm 이상 조건을 만족하는 것으로 판단해줘.

`200 μm`가 정확히 조건의 경계값인 경우 `>=` 조건에서는 PASS가 되어야 합니다.

반면:

    200 μm를 초과해야 한다.

와 같은 `>` 조건에서는 정확히 `200 μm`인 장비는 PASS가 되면 안 됩니다.

---

# 17. Evaluation Criteria

초기 검증에서는 다음 항목을 확인합니다.

| 평가 항목 | 확인 내용 |
|---|---|
| Requirement Parsing | 자연어를 구조화된 요구사항으로 변환하는가 |
| Retrieval | 관련 사양서를 검색하는가 |
| Numeric Accuracy | 숫자를 원본과 동일하게 가져오는가 |
| Unit Handling | nm / μm / mm 등의 단위를 올바르게 처리하는가 |
| PASS / FAIL | 요구조건과 사양을 정확히 비교하는가 |
| UNKNOWN | 정보가 없을 때 추정하지 않는가 |
| Source Traceability | 결과의 근거를 추적할 수 있는가 |
| Hallucination | 원본에 없는 정보를 생성하지 않는가 |
| Ranking | 여러 후보를 합리적으로 비교하는가 |

---

# 18. Data Management

실제 사내 장비 사양서를 적용할 때는 원본 파일과 변환 파일을 분리하여 관리합니다.

권장 구조:

    Original Specification
            ↓
    PPTX → Markdown / HTML
            ↓
    Human Review
            ↓
    Validated Specification
            ↓
    RAG Index

원본 파일을 직접 수정하지 않는 것을 권장합니다.

---

## 18.1 Original Data Preservation

원본의 숫자와 단위를 임의로 변경하지 않습니다.

잘못된 예:

    Original:
    Accuracy: ±1.0 μm

    Converted:
    Accuracy: ±0.5 μm

변환 과정에서 이런 오류가 발생하지 않도록 변환 후 원본과 대조하는 검수 과정이 필요합니다.

---

## 18.2 Source Traceability

가능한 경우 다음 정보를 유지합니다.

    Source File
    Slide
    Section
    Table
    Row
    Original Value

이를 통해 Agent가 생성한 결과가 어느 원본 데이터에서 나온 것인지 추적할 수 있도록 합니다.

---

# 19. PPTX / Markdown / HTML Architecture

현재 프로젝트에서는 PPTX 파일 자체를 Agent의 핵심 데이터 구조로 사용하는 대신 **Specification을 중심 데이터 구조로 사용하는 방향**을 권장합니다.

전체 구조:

    ┌─────────────┐
    │ Requirement │
    └──────┬──────┘
           ↓
        Agent
           ↓
    ┌─────────────┐
    │Specification│
    └──────┬──────┘
           │
       ┌───┼────┐
       ↓   ↓    ↓
      MD  HTML  PPTX

즉:

    Specification
          │
          ├── Markdown Renderer
          │
          ├── HTML Renderer
          │
          └── PPTX Renderer

형태로 구성합니다.

이 구조를 사용하면 실제 회사 PPT 템플릿이 변경되더라도 Agent의 핵심 로직을 수정하지 않고 PPTX Renderer만 수정할 수 있습니다.

---

# 20. Document Conversion

향후 실제 사내 데이터를 적용할 때 다음 기능을 구현하는 것을 목표로 합니다.

## PPTX → Markdown / HTML

    PPTX
      ↓
    Text / Table Extraction
      ↓
    Markdown / HTML
      ↓
    Human Review
      ↓
    RAG

## Markdown / HTML → PPTX

    Specification
          ↓
    Markdown / HTML
          ↓
    PPTX Renderer
          ↓
    Company Specification Template

이렇게 구성하면 실제 회사 PPT 템플릿 파일을 GitHub에 저장하지 않고도 개발 및 테스트가 가능합니다.

---

# 21. Security Considerations

이 프로젝트는 사내망 환경에서 사용하는 것을 기본 전제로 합니다.

기본 구조:

    User
      ↓
    Internal Network
      ↓
    FastAPI Server
      ↓
    Local Ollama
      ↓
    Local Vector DB
      ↓
    Local Result

외부 LLM API에 사양 데이터를 전송하지 않는 구조를 목표로 합니다.

실제 운영 환경에서는 다음 사항을 별도로 검토해야 합니다.

- 사내망 방화벽
- Windows Firewall
- 사용자 인증
- 접근 권한
- 파일 업로드 권한
- 생성 파일 보관 정책
- 사양서 기밀정보 처리 정책
- 서버 로그 관리
- Vector DB 접근 권한
- 모델 및 데이터 저장 위치

---

# 22. Development Roadmap

## Phase 1 — Agent Core Validation

현재 단계입니다.

    Synthetic Markdown
            ↓
           RAG
            ↓
       Requirement
            ↓
      Specification
            ↓
        Validation

목표:

- Requirement Parsing 검증
- RAG Retrieval 검증
- 숫자 정확성 검증
- 단위 변환 검증
- PASS / FAIL 검증
- UNKNOWN 처리 검증
- Hallucination 검증

---

## Phase 2 — Document Conversion

    PPTX
      ↓
    Markdown / HTML

및:

    Markdown / HTML
          ↓
        PPTX

변환 기능을 구현합니다.

---

## Phase 3 — Real Specification Data

실제 사내 장비 사양서를 적용합니다.

    Internal Specification
            ↓
        PPTX → Markdown
            ↓
         Human Review
            ↓
    Validated Specification
            ↓
            RAG

---

## Phase 4 — Specification Generation

실제 업무에서 사용할 수 있는 사양서 생성 기능을 구현합니다.

    Requirement
          ↓
    Candidate Equipment
          ↓
    Requirement Comparison
          ↓
    Specification
          ↓
    Markdown / HTML / PPTX

---

## Phase 5 — Internal Service

사내에서 여러 사용자가 사용할 수 있는 Web Service로 확장합니다.

    Browser
      ↓
    Authentication
      ↓
    Agent Server
      ↓
    Ollama
      ↓
    Vector DB
      ↓
    Specification Repository

추가 기능:

- 사용자 인증
- 프로젝트/세션 관리
- 검색 이력
- 생성 이력
- 사양서 버전 관리
- Source Traceability
- 권한 관리
- 로그 관리

---

# 23. Development Principles

이 프로젝트의 가장 중요한 원칙은 다음과 같습니다.

> **LLM이 사양값을 창작하지 않고, 원본 데이터에 근거하여 사양서를 생성하도록 한다.**

따라서 다음 순서를 우선합니다.

    사용자 요구사항
          ↓
        구조화
          ↓
         검색
          ↓
       원본 근거
          ↓
       조건 검증
          ↓
         생성

LLM의 자연어 생성 능력보다 다음 요소를 우선합니다.

1. 검색 정확성
2. 숫자 정확성
3. 단위 정확성
4. PASS / FAIL 정확성
5. UNKNOWN 처리
6. Source Traceability
7. Hallucination 억제

---

# 24. Current Project Status

현재 프로젝트는 **Prototype / Evaluation 단계**입니다.

## Implemented

- [x] Ollama 기반 LLM 연동
- [x] Embedding 기반 RAG
- [x] 자연어 Requirement Parsing
- [x] Requirement Validation
- [x] Specification Generation
- [x] Specification Validation
- [x] Markdown 기반 Synthetic Specification Dataset
- [x] 기본 Web UI
- [x] RAG 검색 파이프라인
- [x] Source 정보 처리 구조

## Planned

- [ ] 실제 사내 장비 사양서 적용
- [ ] PPTX → Markdown 변환
- [ ] Markdown → PPTX 변환
- [ ] HTML 기반 사양서 생성
- [ ] 자동 Agent 평가
- [ ] 후보 장비 선택 단계
- [ ] 생성된 사양서 직접 수정
- [ ] 사용자 인증
- [ ] 사양서 버전 관리
- [ ] 사내 서비스 운영

---

# 25. License

현재 Repository의 라이선스 정책을 따릅니다.
