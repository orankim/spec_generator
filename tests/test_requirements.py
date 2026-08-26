"""
Requirement Parsing 전용 Ground Truth 테스트 — tests/ground_truth/regression_cases.json
(T001~T015)의 user_query가 올바른 RequirementSchema로 파싱되는지만 검증한다.
RAG 검색/후보 추출/Hard Requirement 판정은 다루지 않는다(그건
tests/test_regression.py의 몫) — 그래서 벡터 DB가 필요 없어 훨씬 빠르다.

실행:
    pytest tests/test_requirements.py -v
    pytest -m requirement -v
"""
from __future__ import annotations

import pytest

from tests.regression_lib import check_requirement_field, load_regression_cases, parse_with_empty_llm

pytestmark = pytest.mark.requirement

_CASES = load_regression_cases()
_CASE_IDS = [c["test_id"] for c in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_requirement_parsing_case(case):
    requirement = parse_with_empty_llm(case["user_query"])

    problems = []
    for field, expected in case["expected_requirement"].items():
        problem = check_requirement_field(requirement, field, expected)
        if problem:
            problems.append(problem)

    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        pytest.fail(
            f"\n{case['test_id']} — {case['name']}\nQuery: {case['user_query']}\n\n"
            f"Requirement Parsing 불일치:\n{detail}",
            pytrace=False,
        )


# ---------------------------------------------------------------
# 문제7 회귀 방지: Accuracy를 사용자가 입력하지 않으면 절대 기본값을 만들지
# 않는다(예전에 ±1 μm 기본값을 자동 생성하던 버그가 있었다).
# ---------------------------------------------------------------
def test_accuracy_is_none_when_not_specified_by_user():
    requirement = parse_with_empty_llm(
        "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘."
    )
    assert requirement.accuracy is None
    assert requirement.required_accuracy_um is None


def test_minimum_defect_size_is_none_when_not_specified_by_user():
    requirement = parse_with_empty_llm("폭 800 mm 이상의 전극을 Inline으로 검사할 수 있는 두께 검사기를 찾아줘.")
    assert requirement.minimum_defect_size is None
    assert requirement.minimum_defect_size_um is None


def test_profile_3d_does_not_hallucinate_thickness():
    """문제3/4: "3D Profile 검사기"에서 thickness가 근거 없이 끼어들면 안 된다."""
    requirement = parse_with_empty_llm(
        "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘."
    )
    assert requirement.inspection_items == ["profile_3d"]


def test_fine_grained_defect_items_are_not_collapsed_into_surface_defect():
    """문제2: "스크래치와 오염" -> ["scratch", "contamination"], surface_defect로 뭉개지지 않는다."""
    requirement = parse_with_empty_llm(
        "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘."
    )
    assert set(requirement.inspection_items) == {"scratch", "contamination"}
    assert "surface_defect" not in requirement.inspection_items
    assert "surface_defect" in requirement.inspection_categories


def test_edge_defect_not_collapsed_when_edge_crack_also_mentioned():
    """이번 회귀 테스트 작성 중 발견한 버그: edge_crack이 edge_defect의 상위
    카테고리로 취급되어, 사용자가 Edge Defect를 직접 언급해도 categories로만
    밀려나고 inspection_items에서 사라지는 문제가 있었다."""
    requirement = parse_with_empty_llm(
        "폭 600 mm 이상의 전극 Edge에서 Edge Defect와 Edge Crack을 모두 검출할 수 있는 Inline 검사기를 찾아줘."
    )
    assert set(requirement.inspection_items) == {"edge_defect", "edge_crack"}


def test_edge_defect_text_does_not_leak_into_surface_defect():
    """이번 회귀 테스트 작성 중 발견한 버그: 바레 "defect" 키워드가 "Edge Defect"
    문구 안의 "Defect"에도 매칭되어 surface_defect가 잘못 함께 추가됐다."""
    requirement = parse_with_empty_llm(
        "폭 1000 mm 이상의 전극에서 Edge Defect와 Void를 모두 검사할 수 있는 Inline 검사기를 찾아줘."
    )
    assert "surface_defect" not in requirement.inspection_items
    assert set(requirement.inspection_items) == {"edge_defect", "void"}


def test_coating_non_uniformity_does_not_leak_generic_coating_item():
    """이번 회귀 테스트 작성 중 발견한 버그: "코팅 불균일"의 "코팅"이 별도의
    포괄적 "coating" 항목까지 잘못 함께 추가해, candidate_matcher에서 항상
    UNKNOWN으로 남는 무의미한 Hard Requirement가 하나 더 생겼다."""
    requirement = parse_with_empty_llm(
        "폭 500 mm 이상의 전극에서 코팅 불균일(Coating Non-uniformity)을 검출할 수 있는 Inline 검사기를 찾아줘."
    )
    assert requirement.inspection_items == ["coating_non_uniformity"]
