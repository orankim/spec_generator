# ⚙️ Electrode Inspection Specification Agent

로컬 LLM과 RAG(Retrieval-Augmented Generation)를 활용하여 **전극 검사기 요구사항을 자연어로 입력하면 관련 장비 사양을 검색하고, 요구조건에 맞는 사양서를 생성하는 사내망용 AI Agent**입니다.

외부 API에 데이터를 전송하지 않고 사내 PC에서 Ollama를 통해 LLM과 Embedding 모델을 실행하는 것을 목표로 합니다.

> **Project Status: Prototype / Evaluation**
>
> 현재는 실제 사내 데이터에 적용하기 전에 Synthetic Markdown 사양서를 이용하여 Agent의 검색, 요구사항 분석, 사양 추출 및 검증 기능을 테스트하는 단계입니다.

---

## 🎯 프로젝트 목표

전극 검사기 사양서를 작성할 때 기존에는 다음과 같은 작업이 필요합니다.

```text
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
