"""
Retrieval MISS Root Cause 분류의 순수 로직 모듈. Real Ollama로 수집한 증거(evidence)
dict만 입력으로 받는다 — Ollama를 호출하지 않고, retrieve_for_requirement()/
_build_queries()도 재구현하지 않는다(scripts/retrieval_root_cause_benchmark.py가
production 함수를 그대로 호출해 이 모듈이 쓸 evidence를 만든다).

핵심 논리(요청서 10/12절 — "단순 semantic retrieval 문제"로 뭉뚱그리지 않는다):
현재 MISS 케이스는 정의상 production k_per_query(예: 10)로 merge한 최종 결과에
expected 문서가 전혀 없다는 뜻이다. agent/spec_retriever.py::retrieve_for_requirement()
는 "확장 질의마다 top-k를 뽑아 합집합"을 만들므로, 어떤 확장 질의든 그 질의의 실제
top-k(=production k) 안에 expected 문서가 있었다면 최종 결과에도 반드시 있어야 한다
(합집합이므로). 즉 MISS라면 "모든 확장 질의에서, production k 안에 expected 문서가
없었다"가 항상 참이다 — 이 모듈은 k를 훨씬 크게(예: 50) 잡아 같은 질의들을 다시 검색해
"그래도 못 찾았는지"(진짜 의미적으로 멀리 있음) 아니면 "k=10~50 사이 어딘가에는
있었는지"(순위 경쟁에서 커트라인 바로 밑으로 밀림)를 구분한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

CAUSE_A_VOCABULARY_MISMATCH = "A_QUERY_VOCABULARY_MISMATCH"
CAUSE_B_GENERIC_QUERY_COMPETITION = "B_GENERIC_QUERY_COMPETITION"
CAUSE_C_SPARSE_REQUIREMENT_QUERY = "C_SPARSE_REQUIREMENT_QUERY"
CAUSE_D_QUERY_EXPANSION_WEAKNESS = "D_QUERY_EXPANSION_WEAKNESS"
CAUSE_E_RANKING_IN_RETRIEVAL_STAGE = "E_RANKING_IN_RETRIEVAL_STAGE"
CAUSE_F_CORPUS_REPRESENTATION_PROBLEM = "F_CORPUS_REPRESENTATION_PROBLEM"
CAUSE_G_OTHER = "G_OTHER"

# Cause C(Sparse) 판정 기준 — RequirementSchema에서 실제로 채워진 구조화 필드 개수가
# 이 값 이하이면 "정보가 부족한 질의"로 본다. 1개(예: accuracy 단독)까지는 명백히
# sparse, 2개는 경계 — 문서화된 임계값이며 추측이 아니라 이 값 자체를 report에 명시한다.
_SPARSE_FIELD_THRESHOLD = 1
# Cause D(Query Expansion Weakness) 판정 기준 — 확장 질의 개수가 이 값 이하이면
# "확장이 거의 안 된 질의"로 본다(raw_text 1개 + 의미 질의 1개 정도만 있는 경우).
_WEAK_EXPANSION_THRESHOLD = 2
# 확장 질의들의 top-N을 합쳤을 때 등장하는 고유 문서 수가 이 값 이상이면 "경쟁이
# 심한(비특이적) 질의"로 본다.
_GENERIC_COMPETITION_DOC_THRESHOLD = 15


@dataclass
class RootCauseEvidence:
    test_id: str
    query: str
    production_k: int
    requirement_field_count: int
    n_expanded_queries: int
    expanded_queries: List[str]
    best_rank_across_queries: Optional[int]  # 확장 질의 전체에서 expected 문서의 최고(가장 작은) 순위, k=50까지 탐색해도 없으면 None
    best_rank_query: Optional[str]
    n_unique_docs_in_expanded_top_n: int  # 확장 질의들의 top-N 합집합 고유 문서 수(경쟁 정도)
    lexical_overlap: bool  # raw_text의 키워드가 expected 문서의 식별 텍스트(General 절)에 등장하는지
    lexical_overlap_terms: List[str]
    range_boost_applicable: bool  # raw_text에 파싱 가능한 수치 범위가 있었는지(있었다면 D/A보다 F/G 쪽에 무게)
    inspection_item_boost_applicable: bool  # boost 키워드 사전에 해당 검사항목이 있었는지


def classify_root_cause(ev: RootCauseEvidence) -> Dict[str, Any]:
    """근거 우선순위(요청서 12절 "단순 추정 금지"를 지키기 위해 순서를 문서화):
    1) best_rank_across_queries가 production_k보다 크면(=더 큰 k로는 찾아짐) ->
       Cause E(순위 경쟁에서 커트라인 바로 밑으로 밀림) — 가장 명확하고 직접적인 증거.
    2) 그래도 못 찾았다면(None) 아래 순서로 판단:
       a) requirement_field_count가 낮으면 -> Cause C(Sparse)
       b) n_expanded_queries가 낮으면 -> Cause D(Expansion Weakness)
       c) lexical_overlap이 없으면 -> Cause A(Vocabulary Mismatch)
       d) n_unique_docs_in_expanded_top_n이 높으면 -> Cause B(Generic Competition)
       e) 위 어느 것도 아니면 -> Cause F(Corpus Representation, 소극적 결론) 또는 G
    """
    if ev.best_rank_across_queries is not None and ev.best_rank_across_queries > ev.production_k:
        return {
            "cause": CAUSE_E_RANKING_IN_RETRIEVAL_STAGE,
            "reasoning": (
                f"확장 질의 '{ev.best_rank_query}'에서 expected 문서가 순위 {ev.best_rank_across_queries}위로 "
                f"실제 존재했으나 production k={ev.production_k} 밖이었다(k를 크게 잡으면 찾아짐 — 순수 순위 경쟁 문제)."
            ),
        }

    if ev.requirement_field_count <= _SPARSE_FIELD_THRESHOLD:
        return {
            "cause": CAUSE_C_SPARSE_REQUIREMENT_QUERY,
            "reasoning": (
                f"파싱된 Requirement의 구조화 필드가 {ev.requirement_field_count}개뿐(임계값 {_SPARSE_FIELD_THRESHOLD} 이하) "
                f"— 의미적으로 특정 장비를 구별할 정보가 부족함. 확장 질의 {ev.n_expanded_queries}개 전부(k=50까지) "
                f"expected 문서를 찾지 못함."
            ),
        }

    if ev.n_expanded_queries <= _WEAK_EXPANSION_THRESHOLD:
        return {
            "cause": CAUSE_D_QUERY_EXPANSION_WEAKNESS,
            "reasoning": (
                f"확장 질의가 {ev.n_expanded_queries}개뿐(임계값 {_WEAK_EXPANSION_THRESHOLD} 이하) — "
                f"_build_queries()가 이 requirement에서 검색 다양성을 충분히 만들지 못함."
            ),
        }

    if not ev.lexical_overlap:
        return {
            "cause": CAUSE_A_VOCABULARY_MISMATCH,
            "reasoning": (
                f"사용자 질의/확장 질의 어디에도 expected 문서의 식별 텍스트(General 절)와 겹치는 어휘가 없음 "
                f"(확인한 용어: {ev.lexical_overlap_terms})."
            ),
        }

    if ev.n_unique_docs_in_expanded_top_n >= _GENERIC_COMPETITION_DOC_THRESHOLD:
        return {
            "cause": CAUSE_B_GENERIC_QUERY_COMPETITION,
            "reasoning": (
                f"확장 질의들의 top-N 합집합에 서로 다른 문서가 {ev.n_unique_docs_in_expanded_top_n}개나 등장 "
                f"(임계값 {_GENERIC_COMPETITION_DOC_THRESHOLD} 이상) — 질의가 corpus 전반과 비특이적으로 유사해 "
                f"경쟁이 심함."
            ),
        }

    return {
        "cause": CAUSE_F_CORPUS_REPRESENTATION_PROBLEM,
        "reasoning": (
            "requirement 필드/확장 질의 개수/어휘 중첩 모두 정상 범위였지만 k=50까지도 못 찾음 — "
            "남은 설명은 expected 문서의 chunk 구조/표현이 검색에 불리하다는 것(위 A~D 어느 것도 "
            "뚜렷한 근거가 되지 못하므로 소거법으로 F로 분류, 확정적 증거는 아님)."
        ),
    }
