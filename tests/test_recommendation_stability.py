"""
Recommendation Stability 테스트 (Level 1 — Deterministic Pipeline Stability).

목적: Ranking 로직을 바꾸는 것이 아니라, "동일한 입력을 반복 실행했을 때 현재
파이프라인(Requirement Parsing -> Retrieval -> Candidate Extraction -> Hard
Requirement Validation -> Ranking -> Recommendation Reason)이 결정론적으로
동일한 결과를 내는가"를 검증한다. tests/test_regression.py와 완전히 동일한
인프라(tests/regression_lib.py, tests/ground_truth/regression_cases.json)를
재사용한다 — 새 테스트 프레임워크나 새 corpus를 만들지 않는다.

Stability != "항상 같은 장비명 하나". 같은 질의를 3번 실행했을 때 매번 같은
파이프라인 코드가 같은 입력(fake-hash 임베딩은 텍스트의 결정론적 함수, LLM은
"빈 응답" worst-case 스텁)을 거치므로 결과가 완전히 같아야 한다는 뜻이다 — 이건
"어떤 장비가 이겨야 하는가"(Ground Truth) 문제가 아니라 "같은 입력이면 같은
출력이 나오는가"(순수성/결정성) 문제다. 실제 Ollama 환경에서의 "여러 PASS
후보 중 어느 쪽이 선택되어도 정책상 정상"인 시나리오는
tests/test_real_rag_stability.py(Level 2)가 별도로 다룬다.

선택한 질의 유형(요청서 9절, 기존 Ground Truth 재사용, 새 질의 추가 없음):
  T001 — Thickness(Width+Speed+Range+Accuracy), PASS 후보 2개 이상 가능
  T002 — Multiple Inspection Items(Thickness+Surface Defect)
  T003 — Vision Defect(Scratch+Contamination+Minimum Detectable Defect)
  T004 — 3D Profile 단독
  T009 — AND 조건(Edge Defect+Edge Crack)
  T012 — 존재하지 않는 조건(Width 2000mm) -> PARTIAL
  T015 — AND 조건 중 어느 쪽도 완전히 만족 못함(Edge Defect+Void) -> FAIL
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from agent.schemas import CandidateEquipment
from tests.regression_lib import (
    build_fake_embedding_db,
    candidate_name,
    load_regression_cases,
    patched_embeddings,
    run_case,
)

_TEST_DB = "./_test_chroma_db_recommendation_stability"
_REPEAT_COUNT = 3

_STABILITY_CASE_IDS = ["T001", "T002", "T003", "T004", "T009", "T012", "T015"]
_ALL_CASES: Dict[str, Dict[str, Any]] = {c["test_id"]: c for c in load_regression_cases()}
_STABILITY_CASES = [_ALL_CASES[cid] for cid in _STABILITY_CASE_IDS]


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with patched_embeddings():
        yield


@pytest.fixture(scope="module")
def db(fake_embeddings):
    yield build_fake_embedding_db(_TEST_DB)
    import shutil

    shutil.rmtree(_TEST_DB, ignore_errors=True)


def _run_n_times(case: Dict[str, Any], db_path: str, n: int = _REPEAT_COUNT):
    return [run_case(case, db_path) for _ in range(n)]


def _requirement_snapshot(result) -> Dict[str, Any]:
    """timing 등 비결정 필드가 애초에 없는 RequirementSchema를 그대로 dict화."""
    return result.requirement.model_dump()


def _candidate_pool_snapshot(result) -> Tuple[Tuple[str, str, int, int, int], ...]:
    """(source_document, status, pass_count, unknown_count, fail_count)의 정렬된
    튜플 — 후보 집합 자체(개수/각 후보의 판정)가 반복 실행마다 같은지 확인."""
    return tuple(
        sorted(
            (c.source_document, c.status, c.pass_count, c.unknown_count, c.fail_count)
            for c in result.candidates
        )
    )


def _hard_requirement_snapshot(result) -> Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]:
    """후보별 (field_key, result) 판정 집합 — evidence_text/source 등 근거 위치까지
    포함하면 정렬 방식에 따라 소음이 생길 수 있어, PASS/FAIL/UNKNOWN 판정 자체만
    비교한다(요청서 4-1절: "Candidate별 Hard Requirement 결과")."""
    return tuple(
        sorted(
            (
                c.source_document,
                tuple(sorted((m.field_key, m.result) for m in c.matches)),
            )
            for c in result.candidates
        )
    )


def _chosen_snapshot(result) -> Optional[Tuple[str, str, str]]:
    if result.chosen is None:
        return None
    return (candidate_name(result.chosen), result.chosen.source_document, result.chosen.status)


def _recommendation_reason_snapshot(result) -> Optional[Tuple[str, ...]]:
    if result.chosen is None:
        return None
    return tuple(result.chosen.recommendation_reasons)


# ==========================================
# 필수 3종 (요청서 4-1절 명시)
# ==========================================
@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_same_query_produces_same_top_candidate_across_repeated_runs(db, case):
    runs = _run_n_times(case, db)
    snapshots = [_chosen_snapshot(r) for r in runs]
    assert snapshots[0] == snapshots[1] == snapshots[2], (
        f"[{case['test_id']}] 동일 질의를 {_REPEAT_COUNT}회 반복 실행했는데 최종 Top Candidate가 "
        f"달랐습니다(결정론적 파이프라인에서는 발생하면 안 됨): {snapshots}"
    )


@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_same_query_produces_same_candidate_statuses_across_repeated_runs(db, case):
    runs = _run_n_times(case, db)
    snapshots = [_candidate_pool_snapshot(r) for r in runs]
    assert snapshots[0] == snapshots[1] == snapshots[2], (
        f"[{case['test_id']}] 후보 전체(status/pass/unknown/fail count)가 반복 실행마다 달랐습니다"
    )


@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_same_query_produces_same_hard_requirement_results_across_repeated_runs(db, case):
    runs = _run_n_times(case, db)
    snapshots = [_hard_requirement_snapshot(r) for r in runs]
    assert snapshots[0] == snapshots[1] == snapshots[2], (
        f"[{case['test_id']}] 후보별 Hard Requirement PASS/FAIL/UNKNOWN 판정이 반복 실행마다 달랐습니다"
    )


# ==========================================
# 추가 2종 — 요청서 4-1절 상단 목록의 나머지 항목(Parsed Requirements, Recommendation Reason)
# ==========================================
@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_same_query_produces_same_parsed_requirement_across_repeated_runs(db, case):
    runs = _run_n_times(case, db)
    snapshots = [_requirement_snapshot(r) for r in runs]
    assert snapshots[0] == snapshots[1] == snapshots[2], (
        f"[{case['test_id']}] Requirement Parsing 결과가 반복 실행마다 달랐습니다"
    )


@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_same_query_produces_same_recommendation_reason_across_repeated_runs(db, case):
    runs = _run_n_times(case, db)
    snapshots = [_recommendation_reason_snapshot(r) for r in runs]
    assert snapshots[0] == snapshots[1] == snapshots[2], (
        f"[{case['test_id']}] Recommendation Reason 목록이 반복 실행마다 달랐습니다"
    )


# ==========================================
# Candidate Pool 구조 검증 (요청서 14절) — CandidateEquipment 구조를 그대로 사용,
# 새 필드/스키마를 만들지 않는다.
# ==========================================
def _assert_candidate_pool_integrity(candidates: List[CandidateEquipment], case_id: str) -> None:
    for c in candidates:
        assert isinstance(c.source_document, str) and c.source_document, (
            f"[{case_id}] candidate_id={c.candidate_id}: source_document이 비어 있습니다"
        )
        assert isinstance(c.candidate_id, str) and c.candidate_id, (
            f"[{case_id}] source_document={c.source_document}: candidate_id가 비어 있습니다"
        )
        assert c.status in ("PASS", "PARTIAL", "FAIL"), (
            f"[{case_id}] {c.source_document}: status={c.status!r}가 PASS/PARTIAL/FAIL 중 하나가 아닙니다"
        )
        assert isinstance(c.matches, list), f"[{case_id}] {c.source_document}: matches(hard requirement 목록)가 list가 아닙니다"
        # equipment_name에 해당하는 정보는 manufacturer/model 두 필드로 나뉘어 있다(CandidateEquipment
        # 구조를 그대로 사용 — 새 필드를 추가하지 않음). candidate_name()이 둘 다 None이어도 "?  ?"로
        # 안전하게 표시하지만, 최소한 candidate_name() 호출 자체가 예외 없이 되는지만 확인한다.
        assert candidate_name(c) is not None


@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_candidate_pool_structure_is_well_formed(db, case):
    result = run_case(case, db)
    _assert_candidate_pool_integrity(result.candidates, case["test_id"])


# ==========================================
# Recommendation Reason 검증 (요청서 13절) — 기존 정책이 fake-embedding 파이프라인
# 에서도 유지되는지 확인. 새 production 로직을 만들지 않고 기존 CandidateFieldMatch/
# recommendation_reasons/unconfirmed_items를 그대로 검사한다.
# ==========================================
@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_recommendation_reason_only_reflects_pass_items_with_evidence(db, case):
    result = run_case(case, db)
    if result.chosen is None:
        pytest.skip(f"[{case['test_id']}] 후보 없음 — 이 검증 대상 아님")
    chosen = result.chosen

    # 1) PASS로 판정된 항목만 recommendation_reasons에 들어간다(UNKNOWN이 PASS처럼 표현되지 않음).
    pass_items = {m.item for m in chosen.matches if m.result == "PASS"}
    for reason in chosen.recommendation_reasons:
        # recommendation_reasons 각 줄은 "✓ {item}: ..." 형식(agent/candidate_matcher.py)이다.
        assert reason.startswith("✓"), (
            f"[{case['test_id']}] recommendation_reasons에 PASS 표시(✓)가 아닌 항목이 있습니다: {reason!r}"
        )
        matched_item = next((item for item in pass_items if reason.startswith(f"✓ {item}")), None)
        assert matched_item is not None, (
            f"[{case['test_id']}] recommendation_reasons의 항목이 실제 PASS 목록에 없습니다: {reason!r} "
            f"(PASS 항목: {sorted(pass_items)})"
        )

    # 2) UNKNOWN 항목은 "?"로만 unconfirmed_items에 들어가고, PASS(✓) 문구로 표현되지 않는다.
    unknown_items = {m.item for m in chosen.matches if m.result == "UNKNOWN"}
    for item in unknown_items:
        assert not any(r.startswith(f"✓ {item}") for r in chosen.recommendation_reasons), (
            f"[{case['test_id']}] UNKNOWN 항목 '{item}'이 PASS(✓) 문구로 추천 이유에 포함되었습니다"
        )

    # 3) PASS 항목은 반드시 근거(evidence_text 또는 source)를 가진다 — 문서에 없는 값을
    #    추천 이유로 만들어내지 않았는지 확인.
    for m in chosen.matches:
        if m.result == "PASS":
            assert m.source is not None or m.evidence_text is not None, (
                f"[{case['test_id']}] '{m.item}'이 PASS인데 근거(evidence_text/source)가 없습니다"
            )


@pytest.mark.parametrize("case", _STABILITY_CASES, ids=_STABILITY_CASE_IDS)
def test_hard_requirement_only_covers_user_requested_conditions(db, case):
    """사용자가 요구하지 않은 조건은 Hard Requirement에 포함되지 않는다(요청서 2/13절).
    예: case의 expected_requirement에 accuracy가 없으면(즉 사용자가 요구하지 않았으면)
    Hard Requirement 목록에도 accuracy 항목이 없어야 한다."""
    requirement_present = case["expected_requirement"]
    result = run_case(case, db)
    if result.chosen is None:
        pytest.skip(f"[{case['test_id']}] 후보 없음 — 이 검증 대상 아님")

    field_keys = {m.field_key for m in result.chosen.matches}
    if "accuracy" not in requirement_present:
        assert "accuracy" not in field_keys, (
            f"[{case['test_id']}] 사용자가 accuracy를 요구하지 않았는데 Hard Requirement에 포함되었습니다"
        )
    if "measurement_speed" not in requirement_present:
        assert "speed" not in field_keys, (
            f"[{case['test_id']}] 사용자가 속도를 요구하지 않았는데 Hard Requirement에 포함되었습니다"
        )
    if "measurement_range" not in requirement_present:
        assert "measurement_range" not in field_keys, (
            f"[{case['test_id']}] 사용자가 측정 범위를 요구하지 않았는데 Hard Requirement에 포함되었습니다"
        )
