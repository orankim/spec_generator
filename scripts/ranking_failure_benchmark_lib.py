"""
Ranking Failure Analysis + Alternative Ranking Policy Offline Benchmark의 순수 로직 모듈.

Production Ranking 코드(agent/candidate_matcher.py::select_best_candidate,
_STATUS_RANK)는 이 파일에서 재구현하지 않는다 — Policy A(현재 production 정책)는
select_best_candidate()를 그대로 호출한 결과이며, 이 모듈은 그 결과와 Expected
Candidate를 "비교"만 한다. Policy B/C/D는 요청서 11/14절이 명시적으로 요구하는
"Offline에서만 비교할 대안 정책"이므로 이 모듈 안에 별도 정렬 함수로 존재한다
(production _STATUS_RANK/select_best_candidate는 손대지 않음 — 이 모듈의
_OFFLINE_STATUS_RANK는 그 값을 그대로 복사한 "분석 전용 상수"일 뿐이다).

이 모듈이 다루는 candidate 표현은 실제 CandidateEquipment를 그대로 쓰거나(Policy A
검증, Top-N 계산), 캐시에서 복원한 간략한 dict(candidate_id/source_document/
manufacturer/model/status/pass_count/unknown_count/fail_count/rag_similarity_score/
matches)를 쓴다 — 어느 쪽이든 이미 production build_candidates()가 계산해 둔 값만
읽는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Production agent/candidate_matcher.py의 _STATUS_RANK와 정확히 같은 값을 복사한
# "분석 전용" 상수 — production 상수를 import해 재사용하지 않는 이유는, 이 모듈의
# 대안 정책(B/C/D)들이 이 상수를 서로 다른 위치에 끼워 넣어 별도의 정렬 key를
# 구성해야 하기 때문에(예: Policy B는 similarity를 pass_count보다 앞에 둠) 어차피
# production의 단일 key 튜플과는 다른 구조가 필요하다. 값 자체(PASS=0/PARTIAL=1/
# FAIL=2)는 요청서 13-1절의 "PASS > PARTIAL > FAIL" 정책을 그대로 따른다.
_OFFLINE_STATUS_RANK = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


def _get(obj: Any, name: str) -> Any:
    """CandidateEquipment(속성 접근)와 dict(캐시에서 복원한 candidate) 양쪽을 동일하게
    다루기 위한 헬퍼."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name)


# ==========================================
# 1. Ranking Policy 정의 (요청서 11절) — sort key 함수만 정의, 정렬 자체는 호출부의
# sorted()가 수행한다(별도 재구현 아님, 표준 정렬 함수에 다른 key만 준다).
# ==========================================
def policy_a_key(c: Any) -> Tuple:
    """Policy A — Current Production과 동일한 key(agent/candidate_matcher.py::
    select_best_candidate 그대로 옮김, 값 비교용). Top1 자체는 반드시
    agent.candidate_matcher.select_best_candidate()로 얻어야 한다(§14) — 이 key는
    "production과 같은 순서로 정렬했을 때 Expected가 몇 등인지" 같은 분석에만 쓴다."""
    return (
        _OFFLINE_STATUS_RANK[_get(c, "status")],
        -_get(c, "pass_count"),
        _get(c, "unknown_count"),
        _get(c, "fail_count"),
        -(_get(c, "rag_similarity_score") or 0.0),
        _get(c, "candidate_id"),
    )


def policy_b_key(c: Any) -> Tuple:
    """Policy B — Similarity Earlier: STATUS -> similarity -> pass_count -> unknown_count -> fail_count -> candidate_id."""
    return (
        _OFFLINE_STATUS_RANK[_get(c, "status")],
        -(_get(c, "rag_similarity_score") or 0.0),
        -_get(c, "pass_count"),
        _get(c, "unknown_count"),
        _get(c, "fail_count"),
        _get(c, "candidate_id"),
    )


def policy_c_key(c: Any) -> Tuple:
    """Policy C — Requirement Match Priority: STATUS -> pass_count -> fail_count -> unknown_count -> similarity -> candidate_id.
    (Policy A와 순서만 다름 — fail_count를 unknown_count보다 먼저 본다. 새로운 점수를
    만들지 않고 기존 필드의 순서만 바꾼다는 요청서 11절 제약을 지킨다.)"""
    return (
        _OFFLINE_STATUS_RANK[_get(c, "status")],
        -_get(c, "pass_count"),
        _get(c, "fail_count"),
        _get(c, "unknown_count"),
        -(_get(c, "rag_similarity_score") or 0.0),
        _get(c, "candidate_id"),
    )


def policy_d_key(c: Any) -> Tuple:
    """Policy D — Similarity Dominant Within PASS: STATUS -> similarity -> ... (Policy B와
    사실상 동일 구조이나, 요청서가 별도 정책으로 명시해 독립 함수로 유지 — 향후 두 정책이
    갈라질 여지를 남긴다)."""
    return (
        _OFFLINE_STATUS_RANK[_get(c, "status")],
        -(_get(c, "rag_similarity_score") or 0.0),
        -_get(c, "pass_count"),
        _get(c, "unknown_count"),
        _get(c, "fail_count"),
        _get(c, "candidate_id"),
    )


POLICIES: Dict[str, Callable[[Any], Tuple]] = {
    "A_production_current": policy_a_key,
    "B_similarity_earlier": policy_b_key,
    "C_requirement_match_priority": policy_c_key,
    "D_similarity_dominant": policy_d_key,
}


def rank_candidates_offline(candidates: List[Any], key_fn: Callable[[Any], Tuple]) -> List[Any]:
    """표준 sorted()에 key_fn만 넘긴다 — 정렬 알고리즘 자체를 재구현하지 않는다."""
    return sorted(candidates, key=key_fn)


# ==========================================
# 2. Production Top-N — select_best_candidate()를 반복 호출해 얻는다(요청서 10절,
# tests/test_top_n_ranking.py와 동일한 원칙: 정렬 key를 독립적으로 재구현하지 않는다).
# ==========================================
def top_n_via_production_selection(candidates: List[Any], n: int) -> List[Any]:
    from agent.candidate_matcher import select_best_candidate

    pool = list(candidates)
    top: List[Any] = []
    for _ in range(min(n, len(pool))):
        chosen = select_best_candidate(pool)
        if chosen is None:
            break
        top.append(chosen)
        pool = [c for c in pool if _get(c, "candidate_id") != _get(chosen, "candidate_id")]
    return top


def top_n_offline(candidates: List[Any], key_fn: Callable[[Any], Tuple], n: int) -> List[Any]:
    return rank_candidates_offline(candidates, key_fn)[:n]


# ==========================================
# 3. Funnel 분류 (요청서 3/15/17절) — Retrieval Failure / Validation Failure /
# Ranking Failure / Success를 구조적으로 분리한다.
# ==========================================
FUNNEL_RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
FUNNEL_VALIDATION_FAILURE = "VALIDATION_FAILURE"
FUNNEL_RANKING_FAILURE = "RANKING_FAILURE"
FUNNEL_SUCCESS = "SUCCESS"


@dataclass
class FunnelClassification:
    stage: str  # 위 4개 상수 중 하나
    expected_in_pool: bool
    expected_candidates_in_pool: List[Any] = field(default_factory=list)  # expected_spec_ids와 일치하는 candidate 객체(들)
    expected_has_pass: bool = False
    top1: Optional[Any] = None
    top1_is_expected: bool = False


def classify_funnel(
    candidates: List[Any],
    expected_spec_ids: set,
) -> FunnelClassification:
    """candidates: build_candidates()가 만든 CandidateEquipment 전체 목록(또는 캐시
    dict 목록). expected_spec_ids가 비어있는 케이스(Expected Candidate 없음)는 이
    함수의 대상이 아니다(호출부에서 evaluable 케이스만 넘겨야 한다)."""
    from agent.candidate_matcher import select_best_candidate

    expected_in_pool_candidates = [c for c in candidates if _get(c, "source_document") in expected_spec_ids]
    if not expected_in_pool_candidates:
        return FunnelClassification(stage=FUNNEL_RETRIEVAL_FAILURE, expected_in_pool=False)

    expected_has_pass = any(_get(c, "status") == "PASS" for c in expected_in_pool_candidates)
    if not expected_has_pass:
        return FunnelClassification(
            stage=FUNNEL_VALIDATION_FAILURE,
            expected_in_pool=True,
            expected_candidates_in_pool=expected_in_pool_candidates,
            expected_has_pass=False,
        )

    chosen = select_best_candidate(candidates)
    top1_is_expected = chosen is not None and _get(chosen, "source_document") in expected_spec_ids
    stage = FUNNEL_SUCCESS if top1_is_expected else FUNNEL_RANKING_FAILURE
    return FunnelClassification(
        stage=stage,
        expected_in_pool=True,
        expected_candidates_in_pool=expected_in_pool_candidates,
        expected_has_pass=True,
        top1=chosen,
        top1_is_expected=top1_is_expected,
    )


# ==========================================
# 4. Ranking Loss Reason 자동 분류 (요청서 9절) — Policy A의 정렬 key(=production
# select_best_candidate와 동일한 key 순서)를 첫 번째로 갈라지는 필드 기준으로 설명한다.
# tuple의 사전식 비교 특성상 항상 "가장 먼저 달라지는 필드" 하나가 결정적이다 — 이
# 함수는 그 필드를 찾아 이름 붙일 뿐, 별도 판단 로직을 추가하지 않는다.
# ==========================================
STATUS_LOSS = "STATUS_LOSS"
PASS_COUNT_LOSS = "PASS_COUNT_LOSS"
UNKNOWN_COUNT_LOSS = "UNKNOWN_COUNT_LOSS"
FAIL_COUNT_LOSS = "FAIL_COUNT_LOSS"
SIMILARITY_LOSS = "SIMILARITY_LOSS"
CANDIDATE_ID_TIEBREAK = "CANDIDATE_ID_TIEBREAK"


def classify_ranking_loss_reason(expected: Any, top1: Any) -> str:
    """expected(밀린 후보)와 top1(선택된 후보)의 Policy A key를 필드 하나씩 비교해
    가장 먼저 달라지는 지점을 원인으로 삼는다. RANKING_FAILURE 케이스는 이미
    classify_funnel()에서 expected/top1 둘 다 status=PASS임이 보장되므로
    STATUS_LOSS는 이론상 발생하지 않지만(구조적으로 PASS가 먼저 정렬되므로),
    호출부 오류 등 예외 상황을 대비해 방어적으로 남겨둔다."""
    e_status = _OFFLINE_STATUS_RANK[_get(expected, "status")]
    t_status = _OFFLINE_STATUS_RANK[_get(top1, "status")]
    if e_status != t_status:
        return STATUS_LOSS

    e_pass, t_pass = _get(expected, "pass_count"), _get(top1, "pass_count")
    if e_pass != t_pass:
        return PASS_COUNT_LOSS

    e_unk, t_unk = _get(expected, "unknown_count"), _get(top1, "unknown_count")
    if e_unk != t_unk:
        return UNKNOWN_COUNT_LOSS

    e_fail, t_fail = _get(expected, "fail_count"), _get(top1, "fail_count")
    if e_fail != t_fail:
        return FAIL_COUNT_LOSS

    e_sim = _get(expected, "rag_similarity_score") or 0.0
    t_sim = _get(top1, "rag_similarity_score") or 0.0
    if e_sim != t_sim:
        return SIMILARITY_LOSS

    return CANDIDATE_ID_TIEBREAK


def classify_ranking_loss_reason_multi(expected_candidates: List[Any], top1: Any) -> str:
    """Multiple Expected Candidate(OR) 케이스에서 각 expected 후보의 개별 loss reason이
    서로 다르면 MULTIPLE_FACTORS로 보고한다(요청서 9절 MULTIPLE_FACTORS 정의)."""
    reasons = {classify_ranking_loss_reason(e, top1) for e in expected_candidates}
    if len(reasons) == 1:
        return reasons.pop()
    return "MULTIPLE_FACTORS"


# ==========================================
# 5. Ground Truth Ambiguity 분류 (요청서 16절) — PASS로 판정된 항목 집합만 비교한다.
# 둘 다 status=PASS인 경우에만 호출된다(RANKING_FAILURE 케이스 전용).
# ==========================================
EXPECTED_CLEARLY_BETTER = "EXPECTED_CLEARLY_BETTER"
BOTH_VALID = "BOTH_VALID"
TOP1_CLEARLY_BETTER = "TOP1_CLEARLY_BETTER"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def _pass_item_set(candidate: Any) -> set:
    matches = _get(candidate, "matches") or []
    result_set = set()
    for m in matches:
        item = m["item"] if isinstance(m, dict) else m.item
        result = m["result"] if isinstance(m, dict) else m.result
        if result == "PASS":
            result_set.add(item)
    return result_set


def classify_ambiguity(expected: Any, top1: Any) -> str:
    e_items = _pass_item_set(expected)
    t_items = _pass_item_set(top1)
    if e_items == t_items:
        return BOTH_VALID
    if e_items > t_items:  # expected가 top1이 만족하는 모든 항목 + 그 이상을 만족
        return EXPECTED_CLEARLY_BETTER
    if t_items > e_items:
        return TOP1_CLEARLY_BETTER
    return INSUFFICIENT_EVIDENCE


# ==========================================
# 6. Safety 지표 (요청서 13절)
# ==========================================
def status_priority_holds(ranked: List[Any]) -> bool:
    """PASS > PARTIAL > FAIL이 ranked 순서에서 위반되지 않는지(단조 비감소)."""
    ranks = [_OFFLINE_STATUS_RANK[_get(c, "status")] for c in ranked]
    return ranks == sorted(ranks)


def is_false_pass(no_match_top1_status: Optional[str]) -> bool:
    """Expected Candidate가 없는 케이스에서 최종 status가 PASS로 잘못 나왔는지."""
    return no_match_top1_status == "PASS"
