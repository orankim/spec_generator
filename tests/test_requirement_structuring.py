"""
"AI가 이해한 요구사항" 화면에 측정 범위/정확도가 표시되지 않던 문제에 대한 회귀 테스트.

사용자가 실제로 보고한 질문:
    "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."

RequirementParser가(LLM 결과와 무관하게) agent.units의 정규식/단위 파싱으로
measurement_range/accuracy를 직접 채우는지, 그리고 이 값들이 이후 후보 장비를
PASS/FAIL로 비교하는 hard requirement(agent.units.evaluate_hard_requirements)로
코드 레벨에서 쓰일 수 있는지를 검증한다.
"""
import unittest.mock as mock

from agent.requirement_parser import apply_deterministic_extraction, parse_requirement_text
from agent.schemas import RequirementSchema, RequirementTarget
from agent.units import evaluate_hard_requirements

_REPORTED_QUERY = "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."


# ---------------------------------------------------------------
# 1. 사용자가 보고한 정확한 질문에 대해 실제 RequirementSchema 출력값 검증
# ---------------------------------------------------------------
def test_reported_query_structures_range_and_accuracy():
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
    )
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 5
    assert requirement.inspection_items == ["thickness"]

    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"

    assert requirement.accuracy is not None
    assert requirement.accuracy.value == 1.0
    assert requirement.accuracy.unit == "um"
    assert requirement.accuracy.operator == "<="
    assert requirement.required_accuracy_um == 1.0  # sync_legacy_fields()로 레거시 필드도 동기화

    assert requirement.measurement_method is None
    assert requirement.measurement_principle is None


def test_parse_requirement_text_applies_extraction_even_if_llm_misses_it():
    """
    소형 LLM이 measurement_range/accuracy를 놓치고 빈 RequirementSchema를
    반환해도(raw_text만 채워서), parse_requirement_text()가 결정론적 추출을
    거쳐 값을 채워야 한다 — LLM 품질에 의존하지 않는다는 것이 핵심.
    """
    llm_stub = RequirementSchema(
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        # measurement_range/accuracy는 LLM이 놓쳤다고 가정(비어 있음)
    )
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement = parse_requirement_text(_REPORTED_QUERY, model="test-model")

    assert requirement.raw_text == _REPORTED_QUERY
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"
    assert requirement.required_accuracy_um == 1.0


# ---------------------------------------------------------------
# 2. 이미 채워진 값은 덮어쓰지 않는다 (LLM/조건선택 UI가 이미 맞게 채웠다면 신뢰)
# ---------------------------------------------------------------
def test_deterministic_extraction_does_not_overwrite_existing_values():
    from agent.schemas import RequirementRange, RequirementValue

    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        measurement_range=RequirementRange(min=10.0, max=190.0, unit="um"),
        accuracy=RequirementValue(value=2.0, unit="um", operator="<="),
    )
    apply_deterministic_extraction(requirement)

    assert requirement.measurement_range.min == 10.0  # 원래 값 유지
    assert requirement.measurement_range.max == 190.0
    assert requirement.accuracy.value == 2.0


# ---------------------------------------------------------------
# 3. 다양한 표현 로버스트니스: "0~200", "0 - 200", "0 to 200", "200 이하",
#    "최대 200", "±1 μm 이하"
# ---------------------------------------------------------------
def test_various_range_expressions_all_parse_to_same_range():
    for text in ["0~200 μm 범위", "0 - 200 μm 범위", "0 to 200 μm 범위", "0부터 200 μm 범위"]:
        requirement = RequirementSchema(raw_text=text)
        apply_deterministic_extraction(requirement)
        assert requirement.measurement_range is not None, f"실패: {text!r}"
        assert requirement.measurement_range.min == 0.0, f"실패: {text!r}"
        assert requirement.measurement_range.max == 200.0, f"실패: {text!r}"
        assert requirement.measurement_range.unit == "um", f"실패: {text!r}"


def test_upper_bound_only_range_expressions_assume_zero_min():
    for text in ["200 μm 이하 측정 범위가 필요합니다", "최대 200 μm 범위까지 측정 가능해야 함"]:
        requirement = RequirementSchema(raw_text=text)
        apply_deterministic_extraction(requirement)
        assert requirement.measurement_range is not None, f"실패: {text!r}"
        assert requirement.measurement_range.min == 0.0, f"실패: {text!r}"
        assert requirement.measurement_range.max == 200.0, f"실패: {text!r}"


def test_accuracy_expression_variants():
    for text in ["±1 μm 이하 정확도가 필요하다", "정확도 1um 이하가 필요합니다", "accuracy 1um 이하"]:
        requirement = RequirementSchema(raw_text=text)
        apply_deterministic_extraction(requirement)
        assert requirement.accuracy is not None, f"실패: {text!r}"
        assert requirement.accuracy.value == 1.0, f"실패: {text!r}"
        assert requirement.accuracy.operator == "<=", f"실패: {text!r}"


def test_range_and_accuracy_numbers_do_not_bleed_into_each_other():
    """
    회귀: "200 μm 이하 측정 범위, 정확도는 언급 없음"처럼 범위 표현에 쓰인 숫자가
    마스킹되지 않으면, 뒤에 나오는 "정확도" 키워드가 엉뚱하게 그 200을 자기 값으로
    잘못 주워가는 버그가 있었다.
    """
    requirement = RequirementSchema(raw_text="200 μm 이하 측정 범위, 정확도는 언급 없음")
    apply_deterministic_extraction(requirement)
    assert requirement.measurement_range.max == 200.0
    assert requirement.accuracy is None  # 정확도는 실제로 언급되지 않았으므로 None이어야 함


def test_resolution_and_defect_size_extraction():
    requirement = RequirementSchema(raw_text="분해능 0.1um 이하, 최소 결함 크기 10um 이하")
    apply_deterministic_extraction(requirement)
    assert requirement.resolution.value == 0.1
    assert requirement.required_resolution_um == 0.1
    assert requirement.minimum_defect_size.value == 10.0
    assert requirement.minimum_defect_size_um == 10.0


# ---------------------------------------------------------------
# 4. Hard Requirement PASS/FAIL — Python 코드로 판정 (LLM 미개입)
# ---------------------------------------------------------------
def test_evaluate_hard_requirements_pass_when_both_conditions_met():
    ok, reasons = evaluate_hard_requirements(
        required_range=(0.0, 200.0, "um"),
        required_accuracy=(1.0, "um", "<="),
        candidate_range=(0.0, 200.0, "um"),
        candidate_accuracy=(1.0, "um"),
    )
    assert ok is True
    assert reasons == []


def test_evaluate_hard_requirements_fails_on_narrower_range():
    ok, reasons = evaluate_hard_requirements(
        required_range=(0.0, 200.0, "um"),
        required_accuracy=(1.0, "um", "<="),
        candidate_range=(0.0, 100.0, "um"),
        candidate_accuracy=(0.5, "um"),
    )
    assert ok is False
    assert any("측정 범위" in r for r in reasons)


def test_evaluate_hard_requirements_fails_on_worse_accuracy():
    ok, reasons = evaluate_hard_requirements(
        required_range=(0.0, 200.0, "um"),
        required_accuracy=(1.0, "um", "<="),
        candidate_range=(0.0, 300.0, "um"),
        candidate_accuracy=(2.0, "um"),
    )
    assert ok is False
    assert any("정확도" in r for r in reasons)


def test_evaluate_hard_requirements_handles_unit_conversion():
    """요구 범위는 um, 후보 범위는 mm로 표기돼도 canonical 변환 후 비교되어야 한다."""
    ok, reasons = evaluate_hard_requirements(
        required_range=(0.0, 200.0, "um"),
        candidate_range=(0.0, 0.5, "mm"),  # 0.5mm = 500um, 200um를 포함
    )
    assert ok is True
    assert reasons == []
