"""
Ground Truth 기반 자동 Regression Test — tests/ground_truth/regression_cases.json의
T001~T015를 실제 파이프라인(RAG 검색 -> Requirement Parsing -> Candidate 추출 ->
Hard Requirement 검증 -> PASS/PARTIAL/FAIL Ranking)으로 전부 실행한다.

실행:
    pytest tests/test_regression.py -v
    pytest -m regression -v
"""
from __future__ import annotations

from typing import Optional, Tuple

import pytest

from tests.regression_lib import (
    AmbiguousCandidateNameError,
    build_fake_embedding_db,
    check_requirement_field,
    format_case_failure,
    load_regression_cases,
    patched_embeddings,
    run_case,
)

_TEST_DB = "./_test_chroma_db_regression"

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with patched_embeddings():
        yield


@pytest.fixture(scope="module")
def db(fake_embeddings):
    yield build_fake_embedding_db(_TEST_DB)
    import shutil

    shutil.rmtree(_TEST_DB, ignore_errors=True)


_CASES = load_regression_cases()
_CASE_IDS = [c["test_id"] for c in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_regression_case(db, case):
    result = run_case(case, db)

    problems = []
    # 동일 Equipment Name의 후보가 corpus에 둘 이상 있을 때(예: SPEC-044.md/
    # SPEC-051.md의 "MultiInspect MI-800") 어느 SPEC 문서를 가리키는지 명시하는
    # 선택적 맵. 없으면 이름이 유일하다고 가정하고 기존과 동일하게 동작한다.
    spec_ids = case.get("candidate_spec_ids", {})

    for field, expected in case["expected_requirement"].items():
        problem = check_requirement_field(result.requirement, field, expected)
        if problem:
            problems.append(f"Requirement Parsing: {problem}")

    def _lookup(name: str) -> Tuple[object, Optional[str]]:
        """(candidate, ambiguity_error) — ambiguity_error가 있으면 candidate는
        항상 None이고, 그 문자열이 이미 사람이 읽을 수 있는 문제 설명이다."""
        try:
            return result.candidate(name, spec_id=spec_ids.get(name)), None
        except AmbiguousCandidateNameError as exc:
            return None, f"Candidate Extraction: {exc}"

    for name in case["expected_pass_candidates"]:
        c, ambiguity = _lookup(name)
        if ambiguity:
            problems.append(ambiguity)
        elif c is None:
            problems.append(f"Candidate Extraction: '{name}'이 후보로 발견되지 않았습니다")
        elif c.status != "PASS":
            problems.append(f"Hard Requirement: '{name}'의 status가 PASS여야 하는데 {c.status}입니다")

    for name in case["expected_partial_candidates"]:
        c, ambiguity = _lookup(name)
        if ambiguity:
            problems.append(ambiguity)
        elif c is None:
            problems.append(f"Candidate Extraction: '{name}'이 후보로 발견되지 않았습니다")
        elif c.status != "PARTIAL":
            problems.append(f"Hard Requirement: '{name}'의 status가 PARTIAL이어야 하는데 {c.status}입니다")

    for name in case["expected_fail_candidates"]:
        c, ambiguity = _lookup(name)
        if ambiguity:
            problems.append(ambiguity)
        elif c is None:
            problems.append(f"Candidate Extraction: '{name}'이 후보로 발견되지 않았습니다")
        elif c.status != "FAIL":
            problems.append(f"Hard Requirement: '{name}'의 status가 FAIL이어야 하는데 {c.status}입니다")

    chosen_name = None
    if result.chosen is not None:
        from tests.regression_lib import candidate_name

        chosen_name = candidate_name(result.chosen)

    for name in case["forbidden_candidates"]:
        if chosen_name == name:
            problems.append(f"Candidate Ranking: '{name}'이 최종 추천되면 안 됩니다")

    if result.chosen is None:
        if case["expected_final_status"] != "FAIL":
            problems.append(f"Candidate Ranking: 후보가 전혀 없습니다 (expected_final_status={case['expected_final_status']})")
    elif result.chosen.status != case["expected_final_status"]:
        problems.append(
            f"Candidate Ranking: 최종 상태가 {case['expected_final_status']}여야 하는데 {result.chosen.status}입니다"
        )

    if problems:
        pytest.fail("\n" + format_case_failure(case, result, problems), pytrace=False)
