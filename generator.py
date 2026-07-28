import json
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# LangChain & Chroma DB 모듈
from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.llms import Ollama


# ==========================================
# 1. Pydantic을 활용한 사양서 JSON 데이터 구조 정의
# ==========================================
class SpecTableItem(BaseModel):
    category: str = Field(description="구분/분류 (예: 전력, 치수, 챔버 사양 등)")
    item: str = Field(description="항목명 (예: 정격 전압, 처리 크기, 진공도 등)")
    value: str = Field(description="사양값 (예: AC 220V 3Phase, 300mm, 10^-6 Torr)")
    note: Optional[str] = Field(default="", description="비고 또는 세부조건")

class SpecDocumentData(BaseModel):
    equipment_name: str = Field(description="설비 표준 명칭")
    overview: str = Field(description="설비 개요 및 주요 특징 요약 (2-3문장)")
    target_capacity: str = Field(description="처리 능력 / 용량 사양")
    spec_table: List[SpecTableItem] = Field(description="상세 기술 사양 표 데이터")


# ==========================================
# 2. 사양서 데이터 생성기 클래스
# ==========================================
class SpecGenerator:
    def __init__(self, db_path: str = "./chroma_db_specs", ollama_base_url: str = "http://localhost:11434"):
        """
        RAG DB 및 Ollama LLM 초기화
        """
        print("=== SpecGenerator 초기화 중... ===")
        self.db_path = db_path
        self.ollama_url = ollama_base_url

        # 1) 임베딩 모델 (RAG 검색용)
        self.embeddings = OllamaEmbeddings(
            model="bge-m3",
            base_url=self.ollama_url
        )

        # 2) Vector DB 연결
        self.vector_store = Chroma(
            persist_directory=self.db_path,
            embedding_function=self.embeddings
        )

        # 3) Ollama LLM 연결 (Qwen2.5 14b 권장)
        self.llm = Ollama(
            model="qwen2.5:14b",
            base_url=self.ollama_url,
            temperature=0.2  # 정확한 값 생성을 위해 낮은 온도 설정
        )
        print("=== 초기화 완료 ===")

    def _retrieve_context(self, user_query: str, k: int = 3) -> str:
        """
        Vector DB에서 유사한 기존 사양서 데이터를 검색합니다.
        """
        results = self.vector_store.similarity_search(user_query, k=k)
        context_text = ""
        for i, doc in enumerate(results, start=1):
            source = doc.metadata.get("source", "Unknown")
            slide = doc.metadata.get("slide_number", "?")
            context_text += f"\n[참고 자료 {i} (출처: {source} Slide {slide})]\n{doc.page_content}\n"
        return context_text

    def generate_spec_json(self, user_prompt: str) -> Dict[str, Any]:
        """
        사용자의 요구사항을 받아 RAG 기반으로 사양서 JSON 데이터를 생성합니다.
        """
        print(f"\n1. 기존 사양 DB에서 관련 정보 검색 중... (요청: '{user_prompt}')")
        context = self._retrieve_context(user_prompt)

        # 시스템 프롬프트 작성
        prompt_template = f"""
당신은 베테랑 설비 엔지니어링 전문가입니다.
기존 사양서 참고 자료와 사용자의 신규 설비 요구사항을 바탕으로, 새롭게 제작할 설비 사양서 내용을 작성하세요.

 반드시 아래 [JSON 출력 형식]에 맞는 완벽한 JSON 문자열만 출력하세요. 
설명, 인삿말, 마크다운 주석 등 JSON 이외의 텍스트는 절대로 포함하지 마세요.

[기존 사양서 참고 자료]
{context}

[사용자 신규 설비 요구사항]
{user_prompt}

[JSON 출력 형식 예시]
{{
  "equipment_name": "300mm 고진공 플라즈마 식각 설비",
  "overview": "본 설비는 300mm 웨이퍼 표면의 미세 패턴을 고진공 환경에서 식각하기 위한 전용 장비입니다.",
  "target_capacity": "시간당 30장 (30 wph)",
  "spec_table": [
    {{"category": "전기/전력", "item": "정격 전압", "value": "3Phi 380V 60Hz", "note": "전압 변동률 ±5% 이내"}},
    {{"category": "진공 사양", "item": "도달 진공도", "value": "1.0 x 10^-6 Torr", "note": "터보분자펌프 적용"}},
    {{"category": "치수/중량", "item": "설비 크기", "value": "2100(W) x 1800(D) x 2000(H) mm", "note": "유지보수 공간 제외"}}
  ]
}}

[JSON 응답]:
"""

        print("2. Ollama(Qwen2.5:14b) 추론 수행 중...")
        raw_response = self.llm.invoke(prompt_template)

        # 3) JSON 텍스트 정제 및 Pydantic 검증
        cleaned_json = self._clean_and_parse_json(raw_response)
        return cleaned_json

    def _clean_and_parse_json(self, response_text: str) -> Dict[str, Any]:
        """
        LLM 출력물에서 pure JSON 문자열만 파싱하고 검증합니다.
        """
        try:
            # ```json ... ``` 같은 마크다운 코드 블록 제거
            json_str = re.sub(r"```(?:json)?", "", response_text).strip()
            
            # 첫 시작 '{' 부터 마지막 '}' 까지만 추출
            match = re.search(r"\{.*\}", json_str, re.DOTALL)
            if match:
                json_str = match.group(0)

            # JSON 객체 파싱
            data_dict = json.loads(json_str)

            # Pydantic 구조로 검증 (항목 누락 체크)
            validated_data = SpecDocumentData(**data_dict)
            print("3. 성공적으로 사양서 JSON 데이터가 생성 및 검증되었습니다.")
            return validated_data.model_dump()

        except Exception as e:
            print(f"⚠️ JSON 파싱/검증 오류 발생: {e}")
            print(f"원문 응답:\n{response_text}")
            # 에러 발생 시 디버깅을 위한 기본 딕셔너리 반환
            return {
                "error": "JSON 파싱 실패",
                "raw_response": response_text
            }


# ==========================================
# 단독 실행 및 테스트
# ==========================================
if __name__ == "__main__":
    # 클래스 인스턴스화
    generator = SpecGenerator(
        db_path="./chroma_db_specs",
        ollama_base_url="http://localhost:11434"
    )

    # 테스트할 자연어 요구사항 입력
    user_req = "300mm 웨이퍼 처리용 고진공 챔버 설비 사양서 만들어줘. 전압은 380V 삼상 사용하고, 진공도는 10^-6 Torr 이상이어야 해."
    
    # 사양서 JSON 생성 실행
    result_json = generator.generate_spec_json(user_req)

    # 결과 출력
    print("\n=== 최종 생성된 JSON 데이터 ===")
    print(json.dumps(result_json, indent=2, ensure_ascii=False))
