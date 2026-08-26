# ⚙️ 전극 검사기 사양서 자동 생성 AI Agent

로컬 LLM(Ollama)과 RAG(검색 증강 생성)를 활용해, 자연어(또는 조건 선택)로 전극 검사기 요구사항을 입력하면 사내 사양 데이터(표준 Markdown 기반 `SPEC-001.md` ~ `SPEC-050.md`)를 검색하고, 후보 장비의 hard requirement(전극 폭/측정 범위/정확도/검사 속도/최소 결함 크기/검사 모드/측정 방식/측정 원리/검사 항목) 충족 여부를 **Python 코드로 결정론적으로 판정**한 뒤, 근거(source)를 추적할 수 있는 표준 Specification을 생성해 Markdown 문서로 출력해 주는 폐쇄망 전용 웹 애플리케이션입니다.

사용자에게 노출되는 기능은 **전극 검사기 AI**(`/agent`) 하나뿐입니다.

---

## 📌 주요 특징

- **100% On-Premise / 폐쇄망 지원**: 외부 인터넷 연결 없이 사내 서버 PC(Ollama)에서 독자 구동. `agent/chroma_store.py`가 `chromadb`를 직접 사용해 Windows 사내 PC의 애플리케이션 제어 정책이 차단하는 `xxhash` 네이티브 DLL 의존성을 원천적으로 회피합니다.
- **표준 12섹션 Markdown Schema & Synthetic Ground Truth 데이터셋**:
  - `sample_specs/SPEC-001.md` ~ `SPEC-050.md` 전체 50개 장비 사양서가 동일한 12개 섹션 표준 Markdown Schema 구조로 통일되어 있습니다.
  - RAG 검색 및 Hard Requirement 검증 테스트를 위해 **모든 UNKNOWN 필드가 구체적이고 현실적인 Synthetic Ground Truth 사양값으로 100% 채워졌습니다 (UNKNOWN 비율 0%)**.
  - 기존 사양서에 명시되어 있던 원본 기준값(977개 항목)은 100% 데이터 손실 없이 완벽히 보존되었습니다 (원본 백업: `sample_specs_original/`).
- **결정론적 요구사항 구조화**: "0~200 μm 측정 범위와 ±1 μm 이하 정확도" 같은 표현을 LLM 품질에 의존하지 않고 정규식/단위 파싱(`agent/units.py`)으로 직접 구조화합니다 (`agent/requirement_parser.py`).
- **LLM 환각(hallucination) 방지**: 최초 자연어 파싱 직후에는 raw_text에 실제 근거가 있는 값이 항상 LLM의 결과를 덮어씁니다 — 근거가 없으면 LLM이 뭘 채웠든 지웁니다 (`apply_deterministic_extraction(trust_llm_guess=False)`).
- **한글 텍스트 정규화(NFC/NFD) 안정성**: 자연어 키워드 매칭이 Unicode 정규화 형태 차이에 영향을 받지 않도록, 매칭 전에 항상 NFC로 정규화합니다.
- **Hard Requirement PASS/FAIL을 LLM이 아니라 Python 코드로 판정**: `agent/candidate_matcher.py`가 RAG 검색 결과를 장비 단위로 그룹화하고, 전극 폭(Width)·측정 범위(Range)·정확도(Accuracy)·속도(Speed)·최소 결함 크기(Min Defect Size)·검사 모드(Inline/Offline)·측정 방식(Contact/Non-contact)·측정 원리(OCT/3D Laser/Interferometry/Vision/Reflectometry 등)·검사 항목(thickness/surface_defect/profile_3d 등)까지 원문에서 파싱하여 조건을 만족하는지 결정론적으로 판정합니다.
- **Requirement/Specification 분리 + Source 추적**: 사용자가 원하는 조건(Requirement)과 장비가 실제 제공하는 사양(Specification)을 분리 유지하고, 값마다 `USER_DEFINED`/`VERIFIED`/`INFERRED` 상태와 근거 문서(`source.document`/`chunk_id`)를 남깁니다.
- **자동 검증 및 Ground Truth 검증 스크립트 구축**:
  - `scripts/validate_spec_schema.py`: 12개 헤더 섹션 구조, 테이블 컬럼, `VERIFIED` 상태 및 `Source File` 명시 검증 (50/50 PASS)
  - `scripts/verify_no_data_loss.py`: 기존 원본 백업과 대조하여 데이터 누락 0건 검증 (100% Retained)
  - `scripts/validate_ground_truth.py`: UNKNOWN/NA/TBD 잔재 유무, 장비/제조사/모델 중복 유무, Test 1~5 조건 충족 장비 적격성 검증 (0 ERRORS PASS)

---

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
│        └ 후보 장비 그룹화 + Range/Accuracy/Width/Speed/MinDefect/   │
│          Mode/Method/Principle 등 hard requirement PASS/FAIL 판정     │
│   5. SpecificationGenerator (agent/spec_generator.py)                │
│        └ 선택된 후보의 chunk만 LLM에 전달(context 최소화) + 후보     │
│          실측값 반영 + source 검증/강등                              │
│   6. SpecificationValidator (agent/spec_validator.py)                │
│        └ 자동 검증 + Hard Requirement Report(요구 vs 실측 PASS/FAIL) │
│   7. Markdown Renderer    (renderers/markdown_renderer.py)           │
│        └ 표준 Markdown 사양서 생성 (generated_files/*.md)            │
│                                                                      │
│   [Chroma DB (chroma_db_specs, agent/chroma_store.py)]               │
│   [Ollama (LLM 추론 + 임베딩)]                                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📋 표준 Markdown Specification Schema (12 Sections)

모든 `sample_specs/SPEC-001.md` ~ `SPEC-050.md` 사양서는 다음 12개 표준 섹션과 구조화된 표 형식으로 구성되어 있습니다.

```markdown
# [Equipment Name]

## 1. General Specification
| Item | Specification |

## 2. Inspection Target
| Item | Unit | Specification | Status | Source |

## 3. Inspection Requirements
| Item | Unit | Specification | Status | Source |

## 4. Measurement Performance
| Item | Unit | Specification | Status | Source |

## 5. Spatial Performance
| Item | Unit | Specification | Status | Source |

## 6. Optical System
| Item | Specification |

## 7. Defect Inspection
| Item | Unit | Specification | Status | Source |

## 7-1. Inspection Performance
| Item | Unit | Specification | Status | Source |

## 8. System Configuration
| Item | Specification |

## 9. Interfaces / Data
| Item | Specification |

## 10. Environment
| Item | Specification |

## 11. Safety
| Item | Specification |

## 12. Sources / Notes
| Item | Specification |
```

---

## 📂 프로젝트 폴더 구조

```
spec_generator/
├── sample_specs/               # [입력] RAG 표준 Markdown 사양서 (SPEC-001.md ~ SPEC-050.md, UNKNOWN 0개)
├── sample_specs_original/      # [백업] 원본 사양서 데이터 100% 보존 백업 폴더
├── chroma_db_specs/            # [생성] RAG용 Vector DB 저장 폴더 (ChromaDB 600 chunks)
├── generated_files/            # [생성] 완성된 마크다운 사양서 저장 폴더
├── build_rag_ollama.py         # RAG Vector DB 구축 및 재색인 스크립트 (--rebuild 지원)
├── debug_rag.py                # RAG 검색 진단 스크립트
├── scripts/
│   ├── migrate_specs_to_standard_schema.py   # 원본 사양서 -> 12섹션 표준 마크다운 변환 스크립트
│   ├── generate_ground_truth_dataset.py      # Ground Truth 데이터 세팅 (UNKNOWN 제거 및 사양 완성)
│   ├── validate_spec_schema.py               # 12섹션 Schema 검증 스크립트 (50/50 PASS)
│   ├── verify_no_data_loss.py                # 데이터 누락 여부 검증 스크립트 (0건 누락)
│   ├── validate_ground_truth.py              # Ground Truth 및 Agent Test 적격성 검증 (0 ERRORS PASS)
│   └── rag_diagnostics.py                    # RAG 색인 진단 CLI
├── main.py                     # FastAPI 웹 서버 + UI (/agent 단일 기능)
├── agent/                      # 전극 검사기 AI Agent 코어 파이프라인
│   ├── schemas.py                 # RequirementSchema / SpecificationSchema (Pydantic)
│   ├── units.py                   # 수치/단위 파싱 및 Hard Requirement PASS/FAIL 판정
│   ├── categorical_match.py       # Inline/Offline, Measurement Method/Principle 키워드 정규화
│   ├── paths.py                   # CWD 독립 절대경로 정의
│   ├── chroma_store.py            # chromadb 직접 래핑 (xxhash 문제 해결)
│   ├── requirement_parser.py      # 자연어/조건선택 -> RequirementSchema (결정론적 구조화)
│   ├── requirement_validator.py   # 미입력 조건 추가질문 유도
│   ├── spec_retriever.py          # 다중 질의 RAG 검색 + range_boost + identity_chunk
│   ├── candidate_matcher.py       # 후보 장비 그룹화 및 결정론적 PASS/FAIL 매칭 Engine
│   ├── spec_generator.py          # SpecificationSchema 생성 및 Source 검증/강등
│   ├── spec_validator.py          # 자동 사양 검증 및 Hard Requirement Report 출력
│   ├── pipeline.py                # 파이프라인 오케스트레이터
│   └── routes.py                  # /api/agent/* 라우터
├── docs/                       # 상세 스키마 및 포맷 명세서
├── tests/                       # pytest 자동화 테스트 스위트 (210+ 개)
├── requirements.txt             # 의존성 패키지 목록
└── README.md
```

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 1. 가상환경 세팅 및 패키지 설치 (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. RAG Vector DB 재색인

`sample_specs/` 마크다운 사양서를 ChromaDB로 색인합니다.

```powershell
.\.venv\Scripts\python.exe build_rag_ollama.py --input-dir sample_specs --db-path chroma_db_specs --rebuild
```

### 3. 데이터셋 검증 스크립트 실행

```powershell
python scripts/validate_spec_schema.py    # Schema 검증
python scripts/verify_no_data_loss.py     # 원본 데이터 손실 검증
python scripts/validate_ground_truth.py   # Ground Truth 무결성 및 Test 1~5 PASS 적격성 검증
```

### 4. 웹 서버 실행

```powershell
python main.py
# 또는: python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

- 웹 브라우저 접속: `http://localhost:8000` (자동으로 `/agent` 페이지로 이동)

---

## 🧪 Ground Truth 테스트 케이스 매핑 (Test 1 ~ 5)

Ground Truth 데이터셋(`SPEC-001` ~ `SPEC-050`)은 Agent의 Hard Requirement 판정 검증을 위한 테스트 케이스를 명확히 충족합니다.

| Test ID | 주요 테스트 조건 | expected PASS 장비 샘플 | 판정 근거 |
|---|---|---|---|
| **Test 1** | 폭 >= 800mm, 속도 >= 500mm/s, Inline, 범위 >= 0~500μm, 정밀도 <= 1.0μm, `thickness` | **`SPEC-010.md`**, **`SPEC-013.md`**, **`SPEC-018.md`** | 폭(800/1200/2000mm), 속도(500/600/1000mm/s), Inline, 범위(0~300/800/1000μm), 정밀도(±0.8/0.8/1.0μm), thickness 검사 충족 |
| **Test 2** | 폭 >= 600mm, Inline, `thickness, surface_defect`, 범위 >= 0~300μm, 정밀도 <= 1.0μm | **`SPEC-044.md`**, **`SPEC-045.md`**, **`SPEC-046.md`** | 폭(1000/1000/1600mm), Inline, 두께+표면결함 동시검사, 범위(0~500/300/800μm), 정밀도(±0.8/0.5/0.8μm) 충족 |
| **Test 3** | 폭 >= 800mm, Inline, `Vision`, `scratch, contamination`, 최소 결함 크기 <= 3μm | **`SPEC-024.md`**, **`SPEC-025.md`** | 폭(800mm), Inline, Vision 검사원리, Scratch+Contamination 검사, 최소 결함 2μm (<= 3μm) 충족 |
| **Test 4** | 폭 >= 1000mm, 속도 >= 500mm/s, Inline, `profile_3d` | **`SPEC-009.md`**, **`SPEC-039.md`** | 폭(1200/1000mm), 속도(1000/700mm/s), Inline, 3D 형상(profile_3d) 검사 충족 |
| **Test 5** | 폭 >= 600mm, Inline, `thickness, surface_defect`, 정밀도 미지정 | **`SPEC-043.md`**, **`SPEC-044.md`**, **`SPEC-045.md`**, **`SPEC-046.md`**, **`SPEC-047.md`**, **`SPEC-050.md`** | 폭 600mm 이상, Inline, 두께+표면결함 동시 검사 장비 충족 |

---

## 🧪 자동화 pytest 실행

```powershell
python -m pip install pytest numpy
python -m pytest tests/ -v
```

전체 210개 이상의 파이프라인 및 결정론적 판정 unit/integration 테스트를 수행합니다.

---

## 🛡️ 폐쇄망 Windows PC 보안 정책 회피 (xxhash DLL 차단 이슈)

사내 Windows PC의 보안 정책이 `_xxhash` 네이티브 DLL 로드를 차단하여 RAG 구축이 실패하는 문제를 방지하기 위해, `agent/chroma_store.py`가 `langchain_chroma` 대신 `chromadb`를 직접 사용하도록 구현되었습니다. 외부 인터넷 접속 없이 오프라인 wheel 설치 환경에서도 100% 안정적으로 구동됩니다.
