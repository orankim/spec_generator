"""
CandidateMatcher — RAG 검색 결과를 문서(장비) 단위로 그룹화하고, 측정 범위/정확도/
최소 검출 결함 크기 같은 hard requirement를 실제 원문에서 추출해 agent.units의
순수 비교 함수(evaluate_hard_requirements/range_covers)로 PASS/FAIL을 판정한다.

핵심 원칙: LLM은 이 판정에 전혀 관여하지 않는다. 이미 agent.spec_retriever가
retrieved_docs를 만드는 과정에서 range_boost/identity_chunk 로직으로 각 후보 문서의
관련 chunk를 모아 놓았으므로, 여기서 벡터 DB를 다시 스캔하지 않고 그 결과를 그대로
입력으로 받는다(중복 구현 방지) — 평가에 필요한 chunk가 retrieved_docs에 없으면
evaluate_hard_requirements가 UNKNOWN으로 정직하게 표시한다.

원래 agent/candidate_matcher.py 파일 하나(1189줄)에 모든 게 들어 있었으나,
"라우트/프론트엔드/로직이 뒤섞여 있다"는 유지보수성 문제(main.py와 같은 종류의
문제)를 응집도 기준으로 나눴다 — 기능은 한 줄도 바뀌지 않았다(select_best_candidate
5순위 버그 수정과 total_margin 4순위/near_duplicates 근접 중복 탐지 추가는 이보다
먼저 별도 커밋으로 완료되어 있었고, 이번 분리는 그 이후 상태를 그대로 옮긴 것이다):

  - extraction.py        문서(Document) chunk -> _CandidateFact 정규식 파싱 계층
  - hard_requirements.py RequirementSchema -> (value, unit[, operator]) 정규화 계층
  - inspection_items.py  thickness/coating 전용 판정 + 검사 항목 키워드 테이블
  - core.py              build_candidates() — 위 세 계층을 조합하는 orchestrator
  - ranking.py           근접 중복 탐지 + select_best_candidate() 최종 랭킹

이 파일은 기존에 `from agent.candidate_matcher import X`로 가져다 쓰던 모든
이름(공개 API 3개 + 외부에서 실제로 import하는 것으로 확인된 private 이름 몇 개)을
그대로 재노출한다 — 패키지로 나뉘었다는 사실이 호출부에 보이지 않게 하기 위함이다.
"""
from ..schemas import CandidateEquipment
from .core import build_candidates
from .extraction import (
    _EQUIPMENT_TYPE_RE,
    _MANUFACTURER_RE,
    _MEASUREMENT_PRINCIPLE_RE,
    _MODEL_RE,
    _extract_candidate_fact,
    _extract_table_rows,
    extract_manufacturer_model,
)
from .ranking import _annotate_near_duplicates, select_best_candidate

__all__ = [
    "CandidateEquipment",
    "build_candidates",
    "select_best_candidate",
    "extract_manufacturer_model",
]
