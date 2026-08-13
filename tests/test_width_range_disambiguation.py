"""
회귀 테스트: target.width_mm으로 쓰인 값이 measurement_range로 잘못 재사용되던 버그.

사용자가 실제로 보고한 질문:
    "양극 폭 10 mm의 두께를 최대 200 μm까지 측정할 수 있고 정확도는 ±1 μm 이내인
    검사기를 찾아줘."

이 문장에서 measurement_range가 "0~10 mm"(폭 값을 잘못 재사용)로 잘못 구조화되고,
기대값인 "0~200 μm"으로 채워지지 않는 버그가 있었다.

원인: agent/requirement_parser.py의 _find_keyword_value()가 "최대" 키워드
주변 ±20자 윈도 안에서 값+단위를 찾을 때, 윈도에 우연히 폭 값("10 mm")까지
함께 걸려 있으면 그 값을 measurement_range로 잘못 소비했다(문장 앞쪽에서 이미
width_mm으로 추출된 숫자가 마스킹되지 않고 그대로 남아 있었기 때문).

수정: apply_deterministic_extraction()이 width_mm을 추출한 직후, 그 값이
매치된 span을 working_text에서 마스킹한 뒤 measurement_range를 찾도록
순서를 조정했다. 또한 _find_keyword_value()는 (키워드에 가장 가까운 값이 아니라)
윈도 안에서 왼쪽부터 첫 번째로 발견되는 값을 쓰는 단순한 규칙으로 되돌렸다
— "키워드에 더 가까운 값"을 우선하는 방식은 콤마로 분리된 별개의 절(예: "...측정
범위, ±1 μm 이하 정확도...")에서 엉뚱하게 다음 절의 값을 골라오는 새로운 회귀를
일으켰기 때문이다. width처럼 이미 다른 필드로 소비된 숫자는 masking으로,
서로 다른 절의 숫자는 애초에 원인이 된 폭 값이 사라졌으므로 문제가 되지 않는다.

추가로 "폭"/"width" 키워드 없이 "양극 10 mm의 thickness를..."처럼 재질명 바로
뒤에 숫자+길이단위가 바로 붙는 경우도 width_mm으로 인식하도록
_extract_width_mm_with_span()에 좁은 범위의 폴백을 추가했다(TEST 2).
"""
from agent.requirement_parser import apply_deterministic_extraction
from agent.schemas import RequirementSchema


def test_1_width_and_measurement_range_do_not_collide():
    text = "양극 폭 10 mm의 두께를 최대 200 μm까지 측정할 수 있고 정확도는 ±1 μm 이내인 검사기를 찾아줘."
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "양극"
    assert requirement.target.width_mm == 10.0

    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"

    assert requirement.accuracy is not None
    assert requirement.accuracy.value == 1.0
    assert requirement.accuracy.unit == "um"
    assert requirement.required_accuracy_um == 1.0


def test_2_bare_width_without_explicit_keyword_and_no_range_mentioned():
    text = "양극 10 mm의 thickness를 ±1 μm 이하 정확도로 측정할 수 있는 검사기를 찾아줘."
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "양극"
    assert requirement.target.width_mm == 10.0

    # 이 문장에는 측정 범위 표현이 전혀 없으므로 measurement_range는 None이어야 한다
    # (폭 값 "10 mm"을 measurement_range로 잘못 추정해서는 안 된다).
    assert requirement.measurement_range is None

    assert requirement.accuracy is not None
    assert requirement.accuracy.value == 1.0
    assert requirement.required_accuracy_um == 1.0


def test_3_width_and_explicit_full_range_both_present():
    text = "양극 폭 10 mm의 두께를 0~200 μm 범위에서 ±1 μm 이하 정확도로 측정할 수 있는 검사기를 찾아줘."
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.target.width_mm == 10.0
    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"
    assert requirement.accuracy.value == 1.0
    assert requirement.required_accuracy_um == 1.0


def test_4_width_and_upper_bound_only_range_no_accuracy_mentioned():
    text = "양극 폭 10 mm의 두께를 최대 200 μm까지 측정"
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.target.width_mm == 10.0
    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"


def test_expression_e_range_and_accuracy_across_comma_do_not_bleed():
    """
    "closest keyword" 방식으로 되돌렸을 때 발생했던 회귀에 대한 직접적인 방지 테스트.
    콤마로 분리된 두 절("측정 범위" 절과 "정확도" 절) 사이에서 값이 잘못 넘어오지
    않아야 한다.
    """
    text = "200 μm 이하 측정 범위, ±1 μm 이하 정확도가 필요해."
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.measurement_range is not None
    assert requirement.measurement_range.max == 200.0
    assert requirement.accuracy is not None
    assert requirement.accuracy.value == 1.0
