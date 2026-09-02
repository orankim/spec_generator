# ⚙️ 전극 검사기 사양서 자동 생성 AI (전극검사기 AI)

> 이 문서는 **컴퓨터/개발 지식이 전혀 없는 분**도 처음부터 끝까지 따라 할 수 있도록,
> 설치 과정을 하나하나 자세히 설명합니다. 회사 인트라넷(폐쇄망) PC에 설치하는 것을
> 기준으로 작성했습니다.

---

## 목차

1. [이 프로그램은 무엇인가요?](#1-이-프로그램은-무엇인가요)
2. [시작하기 전에 준비할 것](#2-시작하기-전에-준비할-것)
3. [설치 가이드 (처음 한 번만)](#3-설치-가이드-처음-한-번만)
4. [실행하기 (매번 사용할 때)](#4-실행하기-매번-사용할-때)
5. [사용 방법 (화면 사용법)](#5-사용-방법-화면-사용법)
6. [자주 발생하는 문제 해결](#6-자주-발생하는-문제-해결)
7. [프로그램 끄는 방법](#7-프로그램-끄는-방법)
8. [주요 기능 요약](#8-주요-기능-요약)
9. [(개발자용) 프로젝트 구조 / 아키텍처](#9-개발자용-프로젝트-구조--아키텍처)
10. [(개발자용) 자동 테스트 실행](#10-개발자용-자동-테스트-실행)

---

## 1. 이 프로그램은 무엇인가요?

전극 검사기(배터리 전극을 검사하는 장비)를 고르려는 사람이 "폭 800mm 이상, 두께
측정 가능, 정확도 ±1μm 이하인 장비 찾아줘" 처럼 **말하듯이(자연어로)** 조건을
입력하면, AI가 사내에 등록된 장비 사양서(문서) 중에서 조건에 맞는 장비를 찾아
추천해 주는 웹 프로그램입니다.

- 인터넷에 연결하지 않고 **회사 PC 안에서만** 동작합니다(폐쇄망 지원). AI 두뇌
  역할을 하는 [Ollama](https://ollama.com)라는 프로그램도 같은 PC(또는 같은
  사내망의 다른 PC) 안에서 돌아갑니다.
- 장비가 사용자의 요구조건을 만족하는지(PASS/FAIL) 판단은 AI의 "느낌"이 아니라
  **코드로 정해진 규칙**에 따라 판정하므로, 같은 조건이면 항상 같은 결과가
  나옵니다.
- 추천 결과는 화면에서 바로 확인할 수 있고, **Markdown(.md)** 또는
  **Microsoft Word(.docx)** 문서로 다운로드할 수 있습니다.

이 프로그램을 실행하려면 아래 순서대로 **딱 한 번만** 설치 작업을 하면 됩니다.
그 이후에는 "실행하기" 단계만 반복하면 됩니다.

---

## 2. 시작하기 전에 준비할 것

아래 4가지가 필요합니다. 순서대로 하나씩 설치할 것이므로 지금 미리 다운로드해둘
필요는 없습니다.

| 준비물 | 용도 | 비고 |
|---|---|---|
| Windows PC | 이 프로그램을 설치/실행할 컴퓨터 | 최소 16GB RAM 권장(AI 모델이 메모리를 많이 씁니다) |
| Python | 이 프로그램이 만들어진 프로그래밍 언어 | 3.11 버전 기준으로 안내합니다 |
| Ollama | PC 안에서 AI(LLM)를 돌려주는 프로그램 | 이 프로그램의 "두뇌" 역할 |
| 이 프로젝트 파일 | 지금 보고 있는 이 코드 전체 | ZIP 다운로드 또는 git으로 받습니다 |

> 💡 **PowerShell이 뭔가요?** Windows에 기본으로 설치되어 있는, 글자로 명령을
> 입력해 컴퓨터를 조작하는 "검은/파란 화면"입니다. 시작 메뉴에서 `PowerShell`을
> 검색하면 나옵니다. 아래 안내에서 "PowerShell을 엽니다"라고 하면 이 프로그램을
> 실행하라는 뜻입니다.

---

## 3. 설치 가이드 (처음 한 번만)

### 3-1. Python 설치

1. 웹 브라우저에서 [python.org/downloads](https://www.python.org/downloads/)에
   접속합니다.
2. "Download Python 3.11.x" 버튼(가장 위에 보이는 노란/파란 버튼)을 눌러
   설치 파일을 받습니다.
3. 다운로드된 설치 파일을 실행합니다. **설치 화면 맨 아래의
   "Add python.exe to PATH"(또는 "Add Python to PATH") 체크박스를 반드시
   체크**한 뒤 "Install Now"를 누릅니다.
   - ⚠️ 이 체크박스를 놓치면 나중에 "python은 내부 또는 외부 명령이 아닙니다"라는
     오류가 나옵니다. 이미 설치를 완료했는데 이 오류가 난다면, Python을
     제거(삭제)하고 이 체크박스를 켠 채로 다시 설치하세요.
4. 설치가 끝나면 PowerShell을 새로 열고 아래 명령을 입력해 확인합니다.

   ```powershell
   python --version
   ```

   `Python 3.11.x` 같은 글자가 나오면 성공입니다.

### 3-2. Ollama 설치 및 AI 모델 준비

Ollama는 이 프로그램이 사용하는 AI(LLM)를 PC 안에서 돌려주는 프로그램입니다.

1. [ollama.com/download](https://ollama.com/download)에서 Windows용 설치
   파일을 받아 실행합니다. 설치 마법사를 그대로 따라가면 됩니다.
2. 설치가 끝나면 Ollama가 자동으로 백그라운드에서 실행됩니다(작업 표시줄
   오른쪽 아이콘으로 확인 가능).
3. PowerShell을 열고, 이 프로그램이 사용하는 AI 모델 2개를 받습니다(최초 1회,
   인터넷 다운로드가 필요합니다 — 회사 폐쇄망이라면 인터넷이 되는 PC에서 받은
   뒤 사내 IT 담당자에게 오프라인 설치 방법을 문의하세요).

   ```powershell
   ollama pull qwen2.5:14b
   ollama pull bge-m3
   ```

   - `qwen2.5:14b`는 실제로 답변을 만드는 AI 모델입니다(용량 약 9GB, 다운로드에
     시간이 걸릴 수 있습니다).
   - `bge-m3`는 문서를 검색하기 위한 임베딩 모델입니다(용량 약 1.2GB).
   - 다운로드 중 화면에 진행률(%)이 표시됩니다. `success`라는 글자가 뜨면
     완료된 것입니다.

4. 제대로 받아졌는지 확인합니다.

   ```powershell
   ollama list
   ```

   목록에 `qwen2.5:14b`와 `bge-m3`가 보이면 성공입니다.

### 3-3. 프로젝트 파일 받기

**컴퓨터/git 지식이 없다면 이 방법을 쓰세요(ZIP 다운로드):**

1. 이 저장소의 GitHub 페이지에서 초록색 "Code" 버튼 → "Download ZIP"을
   클릭합니다.
2. 다운로드된 ZIP 파일을 원하는 위치(예: `C:\전극검사기AI`)에 압축 해제합니다.

**git을 쓸 줄 안다면:**

```powershell
git clone <이 저장소의 URL> spec_generator
cd spec_generator
```

이후 안내에서는 압축을 푼 폴더(예: `C:\전극검사기AI\spec_generator`)를
"프로젝트 폴더"라고 부릅니다.

### 3-4. 프로젝트 폴더에서 PowerShell 열기

1. Windows 탐색기에서 프로젝트 폴더를 엽니다.
2. 폴더 안의 빈 공간에서 **Shift 키를 누른 채 마우스 오른쪽 버튼**을 클릭합니다.
3. 메뉴에서 "여기에 PowerShell 창 열기"(또는 "터미널에서 열기")를 클릭합니다.

이제부터 나오는 모든 명령어는 이 창에 그대로 입력하고 Enter를 누르면 됩니다.

### 3-5. 가상환경 만들고 필요한 패키지 설치

"가상환경"은 이 프로그램 전용으로 격리된 작은 Python 공간을 만드는 것입니다(다른
프로그램과 부품이 섞이지 않게 해줍니다). 아래 4줄을 순서대로 입력합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

- 2번째 줄을 실행하면 프롬프트 맨 앞에 `(.venv)`라는 글자가 붙습니다 — 가상환경이
  켜졌다는 뜻입니다. **이후 모든 명령은 이 `(.venv)`가 보이는 상태에서 실행해야
  합니다.**
- 만약 2번째 줄에서 "이 시스템에서 스크립트 실행을 사용할 수 없으므로..." 같은
  빨간 오류가 나오면, PowerShell을 **관리자 권한으로** 새로 열고 아래 명령을
  한 번 실행한 뒤 다시 시도하세요.

  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

- 마지막 줄(`pip install -r requirements.txt`)은 이 프로그램이 필요로 하는
  모든 부품(패키지)을 자동으로 다운로드/설치합니다. PC 사양에 따라 몇 분 정도
  걸릴 수 있습니다. 중간에 오류 없이 끝나면 성공입니다.

### 3-6. 환경 설정 파일(.env) 만들기

프로젝트 폴더에 있는 `.env.example` 파일을 복사해서 이름을 `.env`로 바꿉니다.

```powershell
Copy-Item .env.example .env
```

- 특별한 이유가 없다면 `.env` 파일 내용은 그대로 두면 됩니다(3-2 단계에서 받은
  모델 이름과 이미 일치합니다).
- 만약 Ollama를 다른 PC에서 돌리고 있다면(예: 사내 서버 PC), `.env` 파일을
  메모장으로 열어 `OLLAMA_HOST=http://localhost:11434` 부분을 그 PC의 주소로
  바꿔주세요(예: `http://192.168.0.10:11434`).

### 3-7. 검색용 데이터베이스 만들기 (최초 1회, 데이터 변경 시 다시 실행)

이 프로그램은 `sample_specs` 폴더 안의 장비 사양서 문서를 미리 읽어서 "검색하기
좋은 형태"로 변환해 둡니다. 이 작업은 **Ollama가 켜져 있어야** 동작합니다(3-2
단계에서 설치한 것이 자동으로 실행 중이어야 합니다).

```powershell
python build_rag_ollama.py --rebuild
```

- 화면에 `[SPEC-001.md] 완료: ...` 같은 줄이 사양서 개수만큼(현재 52개) 쭉
  나오고, 마지막에 `성공! Vector DB가 ...에 저장되었습니다.`가 보이면 완료입니다.
- 사양서 문서(`sample_specs/` 폴더 안의 파일)를 새로 추가하거나 수정했을 때는
  이 명령을 다시 실행해야 검색 결과에 반영됩니다.

여기까지 완료했다면 설치가 모두 끝난 것입니다. 🎉

---

## 4. 실행하기 (매번 사용할 때)

컴퓨터를 재시작했거나, 잠시 껐다가 다시 쓰고 싶을 때는 아래만 반복하면 됩니다
(3번 설치 과정을 다시 할 필요는 없습니다).

1. Ollama가 켜져 있는지 확인합니다(작업 표시줄 아이콘). 꺼져 있다면 시작
   메뉴에서 "Ollama"를 검색해 실행합니다.
2. 프로젝트 폴더에서 PowerShell을 엽니다(3-4 참고).
3. 가상환경을 켭니다.

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

4. 웹 서버를 실행합니다.

   ```powershell
   python main.py
   ```

5. 화면에 `Uvicorn running on http://0.0.0.0:8000`처럼 나오면 정상적으로 켜진
   것입니다. **이 PowerShell 창을 닫지 마세요** — 창을 닫으면 프로그램도
   같이 꺼집니다.
6. 웹 브라우저(Chrome, Edge 등)를 열고 주소창에 아래를 입력합니다.

   ```
   http://localhost:8000
   ```

   자동으로 채팅 화면(`/agent`)으로 이동합니다.

> 다른 PC에서도 접속하게 하려면(같은 사내망 안에서), 서버를 실행 중인 PC의
> IP 주소를 알아내(`ipconfig` 명령의 "IPv4 주소") 다른 PC 브라우저에서
> `http://그_PC의_IP주소:8000`으로 접속하면 됩니다.

---

## 5. 사용 방법 (화면 사용법)

1. 화면 가운데 입력창에 원하는 조건을 문장으로 입력합니다. 예:
   > 폭 800mm 이상, 두께를 측정할 수 있고 정확도 ±1μm 이하인 Inline 검사기를
   > 찾아줘.
2. "전송" 버튼을 누르면 AI가 입력 내용을 이해한 결과("AI가 이해한 요구사항"
   카드)를 먼저 보여줍니다. 조건이 부족하면 추가 질문을 하기도 합니다.
3. 검색이 끝나면 추천 장비 카드가 나타나고, 그 아래에 각 요구조건이
   PASS/FAIL/UNKNOWN(확인 불가) 중 무엇인지 표로 정리되어 나옵니다.
   - 만약 이름이 같은 장비가 대화 중 두 번 이상 다르게 추천되면(실제로 서로
     다른 장비인 경우), 화면에 구분 정보와 함께 "이전 추천과 이름은 같지만,
     서로 다른 장비입니다."라는 안내가 표시됩니다.
4. 카드 아래의 **"📄 Markdown 다운로드"** 또는 **"📝 Word 다운로드"** 버튼을
   누르면 그 장비의 사양서 파일이 만들어지고, 잠시 후 실제 다운로드 링크로
   바뀝니다. 링크를 다시 클릭하면 PC에 파일이 저장됩니다.
5. 왼쪽 사이드바에서 "새로운 대화 시작"을 누르면 새 조건으로 처음부터 다시
   검색할 수 있고, "지난 대화 검색"으로 이전에 찾아봤던 대화를 다시 볼 수
   있습니다(대화 내용은 이 컴퓨터의 이 브라우저 안에만 저장됩니다).

---

## 6. 자주 발생하는 문제 해결

| 증상 | 원인 / 해결 방법 |
|---|---|
| `python`, `pip` 명령이 "내부 또는 외부 명령이 아닙니다" | Python 설치 시 "Add to PATH"를 체크하지 않았습니다. Python을 삭제 후 3-1 단계를 체크박스를 켜고 다시 설치하세요. |
| PowerShell에서 `Activate.ps1` 실행 시 빨간 오류 | 실행 정책 문제입니다. 관리자 권한 PowerShell에서 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 실행한 뒤 다시 시도하세요. |
| 화면에 "Ollama 서버에 연결할 수 없습니다" 경고가 뜸 | Ollama가 꺼져 있습니다. Ollama를 실행한 뒤 `python main.py`를 다시 시작하세요. |
| 질문을 입력해도 응답이 아주 느리거나 멈춘 것처럼 보임 | `qwen2.5:14b` 모델은 PC 사양에 따라 응답에 시간이 걸릴 수 있습니다(특히 GPU가 없는 경우). 잠시 기다려도 안 되면 PowerShell 창의 로그를 확인하세요. |
| `python build_rag_ollama.py --rebuild` 실행이 안 되거나 검색 결과가 항상 0개 | Ollama가 꺼져 있거나 `bge-m3` 모델을 받지 않은 상태입니다. 3-2 단계를 다시 확인하세요. |
| `http://localhost:8000` 접속이 안 됨 | `python main.py`를 실행한 PowerShell 창이 켜져 있는지, 오류 없이 `Uvicorn running...` 문구가 나왔는지 확인하세요. 다른 프로그램이 8000번 포트를 쓰고 있다면 `.env` 파일의 `AGENT_PORT` 값을 예: `8001`로 바꿔보세요. |
| `pip install -r requirements.txt` 도중 오류 | 인터넷 연결을 확인하세요. 사내 폐쇄망이라 인터넷이 안 된다면, IT 담당자에게 오프라인 패키지(wheel) 설치 방법을 문의하세요. |

---

## 7. 프로그램 끄는 방법

`python main.py`를 실행한 PowerShell 창을 클릭한 뒤 `Ctrl + C`를 누르면 서버가
종료됩니다. 창을 그냥 닫아도 종료됩니다. Ollama는 계속 켜두어도 괜찮습니다(다른
프로그램에 영향을 주지 않습니다).

---

## 8. 주요 기능 요약

- **자연어 대화형 검색**: 조건을 문장으로 입력하면 AI가 이해한 내용을 먼저
  보여주고, 부족한 정보는 되물어 확인합니다(추측해서 진행하지 않습니다).
- **결정론적 Hard Requirement 판정**: 전극 폭·측정 범위·정확도·검사
  속도·최소 검출 결함 크기·검사 모드(Inline/Offline)·측정 방식·측정
  원리·검사 항목(두께/표면 결함/3D 프로파일 등) 충족 여부를 AI의 판단이 아닌
  **코드 규칙**으로 PASS/FAIL/UNKNOWN 판정합니다. 근거가 없는 값은 절대
  추측해서 채우지 않고 정직하게 "UNKNOWN"으로 남깁니다.
- **동일 이름 장비 구분(Disambiguation)**: 서로 다른 두 장비가 우연히 같은
  이름을 쓰는 경우에도, 실제로 다른 장비임을 사용자가 알 수 있도록 구분
  정보와 안내 문구를 자동으로 보여줍니다. 이름이 같고 실제로도 같은 장비라면
  불필요한 안내를 표시하지 않습니다.
- **Markdown(.md) + Word(.docx) 동시 다운로드**: 추천된 장비 하나의 사양서를
  Markdown과 Word 두 형식으로 각각 내려받을 수 있습니다. 두 형식은 항상 같은
  데이터에서 만들어지므로 서로 다른 내용을 보여주는 일이 없습니다.
- **모바일 대응 + 접근성**: 좁은 화면(모바일)에서도 메뉴가 Overlay Drawer로
  자연스럽게 열리고, 스크린 리더 사용자를 위한 명도 대비(WCAG AA)와 키보드
  조작을 지원합니다.
- **폐쇄망(사내망) 전용 동작**: 외부 인터넷 연결 없이 사내 PC의 Ollama만으로
  전부 동작합니다.
- **자동 검증 도구**: `scripts/audit_sample_specs.py`로 사양서 데이터의
  중복/누락 여부를 자동으로 점검할 수 있습니다.

---

## 9. (개발자용) 프로젝트 구조 / 아키텍처

> 이 아래 내용은 코드를 직접 수정하거나 동작 원리를 이해하고 싶은 개발자를
> 위한 내용입니다. 사용만 하실 분은 여기까지 읽지 않으셔도 됩니다.

### 시스템 아키텍처 / 파이프라인

```
[사용자 PC (Web Browser)]
         │  http://<서버_IP>:8000  (접속 시 자동으로 /agent 로 이동)
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                          사내 서버 PC                              │
│  [FastAPI Web Server (main.py)] ──► [/agent 채팅 페이지 + /api/agent/*] │
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
│   7. Renderers  (renderers/markdown_renderer.py, docx_renderer.py)    │
│        └ Markdown/Word 사양서 생성 (generated_files/*.md, *.docx)     │
│                                                                      │
│   [Chroma DB (chroma_db_specs, agent/chroma_store.py)]               │
│   [Ollama (LLM 추론 + 임베딩)]                                       │
└──────────────────────────────────────────────────────────────────┘
```

Markdown과 Word는 `renderers/candidate_specification.py`가 만드는 하나의
공통 데이터(Structured Data)를 각자 다른 형식으로 출력만 할 뿐, 값을 각자
다시 계산하지 않습니다 — 그래서 두 파일의 핵심 정보(장비명/측정 범위/정확도/
Hard Requirement 결과 등)가 항상 일치합니다.

### 프로젝트 폴더 구조

```
spec_generator/
├── sample_specs/               # [입력] RAG 표준 Markdown 사양서 (SPEC-001.md ~ SPEC-052.md)
├── sample_specs_original/      # [백업] 원본 사양서 데이터 보존 백업 폴더
├── chroma_db_specs/            # [생성] RAG용 Vector DB 저장 폴더 (build_rag_ollama.py가 생성)
├── generated_files/            # [생성] 다운로드용 Markdown/Word 사양서 저장 폴더
├── ground_truth/               # 사양서 정답지(사람이 확인용, RAG 색인 대상 아님)
├── build_rag_ollama.py         # RAG Vector DB 구축 및 재색인 스크립트 (--rebuild 지원)
├── scripts/
│   ├── audit_sample_specs.py                 # sample_specs 데이터 무결성(중복 이름/필수 필드 누락 등) 감사 도구
│   ├── migrate_specs_to_standard_schema.py   # 원본 사양서 -> 표준 마크다운 변환 스크립트
│   ├── generate_ground_truth_dataset.py      # Ground Truth 데이터 세팅
│   ├── validate_spec_schema.py               # Schema 검증 스크립트
│   ├── verify_no_data_loss.py                # 데이터 누락 여부 검증 스크립트
│   ├── validate_ground_truth.py              # Ground Truth 무결성 검증
│   └── rag_diagnostics.py                    # RAG 색인 진단 CLI
├── main.py                     # FastAPI 웹 서버 + 채팅 UI (/agent 단일 기능)
├── agent/                      # 전극 검사기 AI Agent 코어 파이프라인
│   ├── schemas.py                 # RequirementSchema / SpecificationSchema / CandidateEquipment (Pydantic)
│   ├── units.py                   # 수치/단위 파싱 및 Hard Requirement PASS/FAIL 판정
│   ├── categorical_match.py       # Inline/Offline, Measurement Method/Principle 키워드 정규화
│   ├── paths.py                   # CWD 독립 절대경로 정의
│   ├── chroma_store.py            # chromadb 직접 래핑 (xxhash 문제 회피)
│   ├── requirement_parser.py      # 자연어/조건선택 -> RequirementSchema (결정론적 구조화)
│   ├── requirement_validator.py   # 미입력 조건 추가질문 유도
│   ├── spec_retriever.py          # 다중 질의 RAG 검색 + range_boost + identity_chunk
│   ├── candidate_matcher.py       # 후보 장비 그룹화 및 결정론적 PASS/FAIL 매칭 Engine
│   ├── spec_generator.py          # SpecificationSchema 생성 및 Source 검증/강등
│   ├── spec_validator.py          # 자동 사양 검증 및 Hard Requirement Report 출력
│   ├── pipeline.py                # 파이프라인 오케스트레이터
│   └── routes.py                  # /api/agent/* 라우터
├── renderers/                   # Markdown/HTML/PPTX/Word 출력 렌더러
│   ├── common.py                     # SpecificationSchema 기반 공통 섹션 빌더
│   ├── candidate_specification.py    # CandidateEquipment 기반 Markdown/Word 공통 Structured Data
│   ├── markdown_renderer.py
│   ├── docx_renderer.py              # Word(.docx) 렌더러
│   ├── html_renderer.py
│   └── pptx_renderer.py
├── docs/                        # 상세 스키마 및 포맷 명세서
├── tests/                       # pytest 자동화 테스트 (Backend + tests/e2e/ Playwright, 총 650개 이상)
├── requirements.txt             # 의존성 패키지 목록
├── .env.example                 # 환경변수 설정 예시 (복사해서 .env로 사용)
└── README.md
```

### 환경변수 (.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_MODEL` | `qwen2.5:14b` | 답변 생성용 LLM 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | 문서 검색용 임베딩 모델 |
| `OLLAMA_TIMEOUT` | `180`(초) | LLM 호출 read timeout |
| `AGENT_PORT` | `8000` | `python main.py`로 직접 실행할 때 쓰는 포트 |
| `LOG_LEVEL` | `INFO` | 로그 상세도 |
| `CHROMA_DB_PATH` | 저장소 루트의 `chroma_db_specs/` | Vector DB 경로 오버라이드(선택) |
| `PPT_TEMPLATE_PATH` | (없음) | 회사 PPT 템플릿 경로(선택, 커밋 금지) |

`main.py`(웹 서버)는 `.env`를 자동으로 읽습니다. 다만 `build_rag_ollama.py`를
**직접** 실행할 때는 `.env`를 자동으로 읽지 않으므로, `OLLAMA_HOST` 등을
기본값과 다르게 쓰고 싶다면 실행 전에 PowerShell에서 직접 설정하세요.

```powershell
$env:OLLAMA_HOST = "http://192.168.0.10:11434"
python build_rag_ollama.py --rebuild
```

---

## 10. (개발자용) 자동 테스트 실행

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -v
```

- Backend(순수 로직/HTTP 계층) 테스트와 `tests/e2e/`의 실제 Chromium 브라우저
  기반 E2E(UX) 테스트를 합쳐 **650개 이상**을 실행합니다.
- 마커로 원하는 그룹만 골라 실행할 수도 있습니다.

  ```powershell
  python -m pytest -m regression -v      # Ground Truth 기반 종단 회귀 테스트
  python -m pytest -m e2e -v             # 실제 브라우저 E2E 테스트
  python -m pytest -m specification -v   # Markdown/Word 사양서 렌더링 테스트
  python -m pytest -m download -v        # 사양서 다운로드 API/E2E 테스트
  ```

- 테스트 체계와 각 테스트가 무엇을 검증하는지 자세한 설명은 `TESTING.md`를
  참고하세요.

### sample_specs 데이터 무결성 점검

```powershell
python scripts/audit_sample_specs.py
```

`sample_specs/` 안에 동일한 SPEC ID/장비명 중복, 완전히 동일한 문서, 필수
필드(Manufacturer/Model) 누락 여부를 점검하고 `PASS`/`WARNING`/`FAIL`을
출력합니다.
