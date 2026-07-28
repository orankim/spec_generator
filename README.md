⚙️ 사내망 설비 사양서 자동 생성 시스템 (Spec PPTX Generator)
로컬 LLM과 RAG(검색 증강 생성) 기술을 활용하여, 기존 사내 PPT 사양서 데이터를 기반으로 자연어 요구사항에 맞는 표준 PPTX 사양서를 자동 생성해 주는 폐쇄망 전용 웹 애플리케이션입니다.
📌 주요 특징
100% On-Premise / 폐쇄망 지원: 외부 인터넷 연결 및 데이터 유출 없이 사내 서버 PC에서 독자 구동
RAG 기반 사양 정교화: 기존 PPT 사양서(표/텍스트)를 Vector DB에 저장하여 전문 엔지니어링 용어 및 수치 반영
Structured JSON-to-PPTX: LLM 환각(Hallucination) 및 레이아웃 깨짐 방지를 위해 JSON 구조화 데이터 추출 후 python-pptx 백엔드로 파워포인트 자동 합성
웹 UI 제공: 사내 사용자 누구나 웹 브라우저 접속을 통해 사양서 생성 및 다운로드 가능
🏗️ 시스템 아키텍처
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


🖥️ 권장 서버 하드웨어 사양
CPU: AMD Threadripper Pro 5965WX (24 Cores) 이상 권장
GPU: NVIDIA GeForce RTX 4080 (VRAM 16GB) 이상 필수
RAM: 64GB 이상
OS: Windows 11 / Windows Server / Ubuntu Linux
Python: 3.11 이상
📂 프로젝트 폴더 구조
spec-generator/
├── sample_specs/          # [입력] RAG 학습용 기존 PPTX 사양서 파일 저장 폴더
├── chroma_db_specs/       # [생성] RAG용 Vector DB 저장 폴더
├── generated_files/       # [생성] 사용자가 다운로드할 완성된 PPTX 저장 폴더
├── .venv/                 # Python 가상환경 폴더
├── template.pptx          # 마스터 PPTX 템플릿 파일
├── build_rag_ollama.py    # 1단계: 기존 사양서 PPTX 파싱 및 Vector DB 구축 스크립트
├── generator.py           # 2단계: RAG 검색 및 Ollama 기반 사양서 JSON 생성 모듈
├── pptx_builder.py        # 3단계: JSON 데이터를 PPTX 템플릿에 채워넣는 모듈
├── make_template.py       # [보조] 테스트용 template.pptx 자동 생성 스크립트
├── main.py                # 4단계: FastAPI 웹 서버 및 UI 메인 실행 파일
├── requirements.txt       # 의존성 패키지 목록
└── README.md              # 프로젝트 안내 문서


🚀 빠른 시작 가이드 (Quick Start)
1. VS Code PowerShell 가상환경 세팅 및 패키지 설치
A. PowerShell 스크립트 실행 권한 허용 (최초 1회)
VS Code 터미널(PowerShell)에서 가상환경 활성화 스크립트가 막히지 않도록 권한을 허용합니다.
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser


B. 가상환경 생성 및 활성화
# 프로젝트 폴더 이동 후 가상환경 생성
python -m venv .venv

# 가상환경 활성화 (PowerShell)
.\.venv\Scripts\Activate.ps1


(성공 시 터미널 입력창 맨 앞에 (.venv) 표시가 생깁니다.)
💡 VS Code 자동 연동 팁: Ctrl + Shift + P -> Python: Select Interpreter 검색 -> .\.venv\Scripts\python.exe를 선택해 두면 이후 터미널을 열 때마다 가상환경이 자동 활성화됩니다.
C. 필수 라이브러리 설치
Fatal error in launcher 같은 실행 파일 경로 오류를 방지하기 위해 python -m pip 형태로 설치합니다.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt


2. Ollama 모델 확인 (로컬 실행 중이어야 함)
터미널에서 Ollama에 필수 모델이 들어있는지 확인합니다.
ollama list


필수 모델: qwen2.5:14b (LLM 추론용), bge-m3 (임베딩용)
3. 테스트용 마스터 템플릿 생성
python make_template.py


(실제 운영 시에는 디자인된 사내 표준 template.pptx 파일로 교체하세요.)
4. RAG Vector DB 구축
sample_specs/ 폴더에 학습시킬 기존 사양서 PPTX 파일들을 넣고 실행합니다.
python build_rag_ollama.py


5. 웹 서버 실행 (사내망 서비스 개방)
python main.py


서버 PC 접속: http://localhost:8000
사내망 접속: http://<서버PC_IP_주소>:8000
🛠️ 자주 발생하는 오류 및 해결 방법
1. Fatal error in launcher 오류 발생 시
파이썬 경로 변경이나 가상환경 손상 시 발생합니다. pip 대신 python -m pip을 사용해 설치하거나 가상환경을 재생성합니다.
# 우회 설치
python -m pip install -r requirements.txt

# 가상환경 재생성 (필요시)
deactivate
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt


2. 스크립트를 실행할 수 없으므로... 에러 발생 시
PowerShell 보안 정책 에러입니다. 권한 변경 명령을 실행해 주세요.
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser


🛡️ 사내 방화벽 설정 안내
사내 다른 직원 PC에서 웹 접속이 안 될 경우, 서버 PC의 윈도우 방화벽 인바운드 규칙에서 8000번 포트(TCP)를 허용하도록 설정하세요.

🔒 폐쇄망(완전 오프라인) 환경 설치 가이드
인터넷이 연결된 외부 PC에서 아래 자료를 미리 준비한 뒤, USB 등으로 사내 폐쇄망 서버 PC에 이관합니다.

1. Python 패키지 오프라인 이관
```
# (외부 PC) 프로젝트에 필요한 wheel 파일을 모두 다운로드
python -m pip download -r requirements.txt -d ./offline_wheels

# (폐쇄망 서버 PC) 네트워크 접속 없이 wheel 폴더에서 설치
python -m pip install --no-index --find-links=./offline_wheels -r requirements.txt
```

2. Ollama 모델 오프라인 이관
외부 PC에서 `ollama pull qwen2.5:14b`, `ollama pull bge-m3` 실행 후 생성되는 모델 데이터 폴더(`blobs`, `manifests`)를 통째로 복사하여 폐쇄망 서버 PC의 동일 Ollama 데이터 경로에 붙여넣습니다.

3. 외부 네트워크 통신 완전 차단
본 프로젝트는 `main.py`, `build_rag_ollama.py` 실행 시 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` 환경변수를 자동으로 설정하여, LangChain/ChromaDB 관련 라이브러리가 HuggingFace Hub 등 외부로 통신을 시도하지 않도록 원천 차단합니다. 필요 시 시스템 환경변수로도 동일하게 설정해 이중으로 보안을 강화할 수 있습니다.
