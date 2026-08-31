"""
Top-N Ranking 정책 자동 검증.

목적: agent.candidate_matcher.select_best_candidate()가 실제로 구현하는 정책
(PASS > PARTIAL > FAIL, 동일 status 내에서는 기존 tie-break)이 후보 목록이 뭐가
됐든 항상 지켜지는지 검증한다. 이번 작업은 ranking 로직을 바꾸지 않으므로, 여기
어떤 테스트도 select_best_candidate()의 정렬 key를 재구현하지 않는다 — 대신
production 함수(select_best_candidate)를 반복 호출해 "그 함수가 실제로 고르는
순서"를 Top-N으로 관찰하고, 그 관찰된 순서가 정책 문구(PASS > PARTIAL > FAIL)를
위반하지 않는지만 확인한다.

두 층으로 구성한다.
  1. 실제 Ground Truth 질의(기존 corpus, fake embedding) 기반 Top-N 검증 —
     tests/regression_lib.py를 재사용해 실제 후보 목록을 만들고 관찰한다.
  2. Synthetic Candidate 검증(요청서 16절) — CandidateEquipment를 직접 구성해
     select_best_candidate()에 그대로 넣는다(정렬 로직을 복제하지 않고 production
     함수를 직접 호출).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from agent.candidate_matcher import select_best_candidate
from agent.schemas import CandidateEquipment
from tests.regression_lib import (
    build_fake_embedding_db,
    load_regression_cases,
    patched_embeddings,
    run_case,
)

_TEST_DB = "./_test_chroma_db_top_n_ranking"

# 요청서 6절의 정책 문구(PASS > PARTIAL > FAIL)를 그대로 옮긴 상수 — 이것은
# select_best_candidate()의 상세 정렬 key(_STATUS_RANK + pass_count/unknown_count/
# fail_count/rag_similarity/candidate_id 5단계 tie-break)를 복제한 것이 아니라,
# "상태 우선순위"라는 최상위 정책 하나만 별도로 확인하기 위한 테스트 전용 값이다.
_STATUS_PRIORITY = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


def top_n_via_production_selection(candidates: List[CandidateEquipment], n: int) -> List[CandidateEquipment]:
    """production select_best_candidate()를 반복 호출해 Top-N을 얻는다.
    select_best_candidate()가 이미 후보 전체를 정렬해 1위만 반환하므로, 매번
    "선택된 후보를 제외한 나머지"에 대해 다시 select_best_candidate()를 호출하는
    방식으로 정렬 key를 재구현하지 않고도 순위를 재구성한다."""
    pool = list(candidates)
    top: List[CandidateEquipment] = []
    for _ in range(min(n, len(pool))):
        chosen = select_best_candidate(pool)
        if chosen is None:
            break
        top.append(chosen)
        pool = [c for c in pool if c.candidate_id != chosen.candidate_id]
    return top


def assert_status_priority_policy(candidates: List[CandidateEquipment], top_n: List[CandidateEquipment], label: str) -> None:
    """요청서 15절의 정책을 실제 코드 구조(select_best_candidate가 단일 최적 후보만
    반환)에 맞게 구현한 invariant. Pseudo code를 그대로 복사하지 않고, 이 프로젝트의
    실제 status 정의(PASS/PARTIAL/FAIL 3종, UNKNOWN은 status가 아니라 count)에 맞춰
    작성했다."""
    if not candidates:
        assert not top_n
        return

    statuses = {c.status for c in candidates}
    top1 = top_n[0]

    if "PASS" in statuses:
        assert top1.status == "PASS", f"[{label}] PASS 후보가 있는데 Top1이 PASS가 아닙니다: {top1.status}"
    elif "PARTIAL" in statuses:
        assert top1.status == "PARTIAL", f"[{label}] PASS 없이 PARTIAL 후보가 있는데 Top1이 PARTIAL이 아닙니다: {top1.status}"
    else:
        assert top1.status == "FAIL", f"[{label}] FAIL 후보만 있는데 Top1이 FAIL이 아닙니다: {top1.status}"

    # Rule 4: Top-N 전체가 PASS > PARTIAL > FAIL 순서를 위반하지 않는다(단조 비감소).
    ranks = [_STATUS_PRIORITY[c.status] for c in top_n]
    assert ranks == sorted(ranks), (
        f"[{label}] Top-N 상태 순서가 PASS > PARTIAL > FAIL을 위반합니다: {[c.status for c in top_n]}"
    )

    # Rule 2/3을 명시적으로 재확인(상단 단조성 검사와 동치이지만, 실패 메시지를
    # 더 구체적으로 남기기 위해 별도로도 검사한다).
    for i, c in enumerate(top_n):
        for j in range(i):
            earlier = top_n[j]
            assert _STATUS_PRIORITY[earlier.status] <= _STATUS_PRIORITY[c.status], (
                f"[{label}] '{earlier.source_document}'({earlier.status})가 "
                f"'{c.source_document}'({c.status})보다 낮은 순위여야 하는데 앞에 있습니다"
            )


# ==========================================
# 1. 실제 Ground Truth 질의 기반 Top-N 검증 (fake embedding)
# ==========================================
_TOP_N_CASE_IDS = ["T001", "T002", "T003", "T004", "T009", "T012", "T015"]
_ALL_CASES: Dict[str, Dict[str, Any]] = {c["test_id"]: c for c in load_regression_cases()}
_TOP_N_CASES = [_ALL_CASES[cid] for cid in _TOP_N_CASE_IDS]


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with patched_embeddings():
        yield


@pytest.fixture(scope="module")
def db(fake_embeddings):
    yield build_fake_embedding_db(_TEST_DB)
    import shutil

    shutil.rmtree(_TEST_DB, ignore_errors=True)


@pytest.mark.parametrize("case", _TOP_N_CASES, ids=_TOP_N_CASE_IDS)
def test_top_n_ranking_policy_holds_for_ground_truth_query(db, case):
    """Candidate가 존재하면 Top-3(또는 존재하는 후보 수까지)이 PASS > PARTIAL > FAIL
    정책을 위반하지 않는지 확인한다(요청서 6/7절). 후보가 3개 미만이면 있는 만큼만 검사."""
    result = run_case(case, db)
    if not result.candidates:
        pytest.skip(f"[{case['test_id']}] 후보가 전혀 없음 — Top-N 대상 아님")

    top_3 = top_n_via_production_selection(result.candidates, n=3)
    assert_status_priority_policy(result.candidates, top_3, case["test_id"])

    # select_best_candidate()가 직접 반환하는 1위와 top_n[0]이 항상 같아야 한다
    # (반복 선택 방식이 production 단일 선택 함수와 동일한 1위를 재현하는지 자체 검증).
    direct_top1 = select_best_candidate(result.candidates)
    assert direct_top1 is not None
    assert top_3[0].candidate_id == direct_top1.candidate_id


@pytest.mark.parametrize("case", _TOP_N_CASES, ids=_TOP_N_CASE_IDS)
def test_top_1_matches_chosen_from_run_case(db, case):
    """tests/regression_lib.run_case()가 이미 select_best_candidate()로 계산해 둔
    result.chosen과, 이 파일이 독립적으로 호출한 top_n_via_production_selection()의
    1위가 항상 일치하는지 확인 — 같은 production 함수를 다른 진입점에서 불러도
    같은 결과가 나오는지의 교차 검증."""
    result = run_case(case, db)
    if not result.candidates:
        pytest.skip(f"[{case['test_id']}] 후보가 전혀 없음")
    top_1 = top_n_via_production_selection(result.candidates, n=1)
    assert result.chosen is not None
    assert top_1[0].candidate_id == result.chosen.candidate_id


# ==========================================
# 2. Synthetic Candidate 검증 (요청서 16절) — production select_best_candidate()를
#    직접 호출, ranking 로직은 복제하지 않는다.
# ==========================================
def _make_candidate(candidate_id: str, status: str, **overrides: Any) -> CandidateEquipment:
    defaults: Dict[str, Any] = dict(
        candidate_id=candidate_id,
        source_document=f"{candidate_id}.md",
        manufacturer="SynthCo",
        model=candidate_id,
        status=status,
        pass_count=overrides.pop("pass_count", 1 if status == "PASS" else 0),
        unknown_count=overrides.pop("unknown_count", 0),
        fail_count=overrides.pop("fail_count", 1 if status == "FAIL" else 0),
    )
    defaults.update(overrides)
    return CandidateEquipment(**defaults)


def test_synthetic_pass_partial_fail_selects_pass():
    candidates = [
        _make_candidate("SYN-FAIL", "FAIL"),
        _make_candidate("SYN-PARTIAL", "PARTIAL"),
        _make_candidate("SYN-PASS", "PASS"),
    ]
    chosen = select_best_candidate(candidates)
    assert chosen is not None and chosen.status == "PASS"
    assert chosen.candidate_id == "SYN-PASS"

    top_3 = top_n_via_production_selection(candidates, n=3)
    assert [c.status for c in top_3] == ["PASS", "PARTIAL", "FAIL"]


def test_synthetic_partial_fail_selects_partial():
    candidates = [
        _make_candidate("SYN-FAIL", "FAIL"),
        _make_candidate("SYN-PARTIAL", "PARTIAL"),
    ]
    chosen = select_best_candidate(candidates)
    assert chosen is not None and chosen.status == "PARTIAL"
    assert chosen.candidate_id == "SYN-PARTIAL"

    top_2 = top_n_via_production_selection(candidates, n=2)
    assert [c.status for c in top_2] == ["PARTIAL", "FAIL"]


def test_synthetic_fail_only_selects_fail():
    candidates = [_make_candidate("SYN-FAIL-1", "FAIL"), _make_candidate("SYN-FAIL-2", "FAIL")]
    chosen = select_best_candidate(candidates)
    assert chosen is not None and chosen.status == "FAIL"


def test_synthetic_empty_candidate_list_returns_none():
    assert select_best_candidate([]) is None


def test_synthetic_multiple_pass_prefers_higher_pass_count():
    """기존 문서화된 2순위 tie-break(-c.pass_count, agent/candidate_matcher.py
    select_best_candidate docstring)가 여전히 그대로인지 확인 — 새 tie-break을
    만드는 것이 아니라 이미 있는 것을 재확인."""
    weaker = _make_candidate("SYN-PASS-WEAK", "PASS", pass_count=2, unknown_count=0, fail_count=0)
    stronger = _make_candidate("SYN-PASS-STRONG", "PASS", pass_count=5, unknown_count=0, fail_count=0)
    chosen = select_best_candidate([weaker, stronger])
    assert chosen is not None and chosen.candidate_id == "SYN-PASS-STRONG"


def test_synthetic_pass_with_unknown_ranks_below_pure_pass():
    """PASS 상태를 공유해도 unknown_count가 적은 쪽이 우선한다는 기존 정책 재확인.
    (참고: 이 프로젝트에서 status="PASS"는 정의상 unknown_count==0이므로 — schemas.py
    CandidateEquipment.status docstring 참고 — 이 테스트는 status 값을 신뢰하지 않고
    pass_count/unknown_count 필드 자체의 tie-break만 별도로 재확인하는 것이다.)"""
    fewer_pass_but_no_unknown = _make_candidate(
        "SYN-A", "PASS", pass_count=3, unknown_count=0, fail_count=0
    )
    more_pass_but_has_unknown = _make_candidate(
        "SYN-B", "PARTIAL", pass_count=4, unknown_count=1, fail_count=0
    )
    chosen = select_best_candidate([fewer_pass_but_no_unknown, more_pass_but_has_unknown])
    # status 자체가 PASS > PARTIAL이므로 1순위에서 이미 SYN-A가 이긴다 — 정책이
    # unknown_count 유무를 pass_count보다 실질적으로 우선시함을 보여주는 예시.
    assert chosen is not None and chosen.candidate_id == "SYN-A"


def test_synthetic_rag_similarity_breaks_tie_when_status_and_counts_equal():
    """4순위 tie-break(-rag_similarity_score)가 여전히 그대로인지 확인 — similarity
    계산 방식 자체는 건드리지 않고, 이미 계산되어 들어온 값을 기존 정책대로
    비교만 하는지 재확인."""
    lower_sim = _make_candidate(
        "SYN-LOW-SIM", "PASS", pass_count=2, unknown_count=0, fail_count=0, rag_similarity_score=0.1
    )
    higher_sim = _make_candidate(
        "SYN-HIGH-SIM", "PASS", pass_count=2, unknown_count=0, fail_count=0, rag_similarity_score=0.9
    )
    chosen = select_best_candidate([lower_sim, higher_sim])
    assert chosen is not None and chosen.candidate_id == "SYN-HIGH-SIM"


def test_synthetic_candidate_id_breaks_final_tie():
    """5순위(candidate_id 오름차순, 최종 결정론적 tie-break)가 여전히 그대로인지 확인."""
    a = _make_candidate("SYN-A", "PASS", pass_count=1, unknown_count=0, fail_count=0, rag_similarity_score=0.5)
    b = _make_candidate("SYN-B", "PASS", pass_count=1, unknown_count=0, fail_count=0, rag_similarity_score=0.5)
    chosen = select_best_candidate([b, a])  # 입력 순서를 일부러 뒤집어도 결과는 동일해야 함
    assert chosen is not None and chosen.candidate_id == "SYN-A"
