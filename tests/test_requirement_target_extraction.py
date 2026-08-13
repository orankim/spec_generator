"""
회귀 테스트: "AI가 이해한 요구사항"에서 measurement_range/accuracy는 정상 구조화되는데
target.material/target.width_mm이 채워지지 않던 문제.

사용자가 실제로 보고한 질문:
    "음극 폭 5 mm의 두께를 0~300 μm 범위에서 ±0.5 μm 이하 정확도로 측정할 수 있는
    검사기를 찾아줘."

원인: agent/requirement_parser.py의 apply_deterministic_extraction()이
measurement_range/accuracy/resolution/minimum_defect_size만 raw_text에서 직접
추출하고, target.material/target.width_mm은 전혀 다루지 않아 LLM이 놓치면 그대로
None으로 남았다. 이 테스트는 apply_deterministic_extraction()이 이제 이 두 필드도
raw_text에서 결정론적으로 추출하는지 검증한다.
"""
import unittest.mock as mock

from agent.pipeline import analyze_requirement
from agent.requirement_parser import apply_deterministic_extraction, parse_requirement_text
from agent.schemas import RequirementSchema

_REPORTED_QUERY = "음극 폭 5 mm의 두께를 0~300 μm 범위에서 ±0.5 μm 이하 정확도로 측정할 수 있는 검사기를 찾아줘."


# ---------------------------------------------------------------
# TEST 1 — 사용자가 실제 입력한 문장 (raw_text만으로 직접 검증)
# ---------------------------------------------------------------
def test_1_reported_query_extracts_material_and_width():
    requirement = RequirementSchema(raw_text=_REPORTED_QUERY, inspection_items=["thickness"])
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 5.0
    assert requirement.inspection_items == ["thickness"]
    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 300.0
    assert requirement.required_accuracy_um == 0.5

    # measurement_method/measurement_principle은 언급되지 않았으므로 미정이어도 된다.
    assert requirement.measurement_method is None
    assert requirement.measurement_principle is None


# ---------------------------------------------------------------
# TEST 2 — material만 있는 경우
# ---------------------------------------------------------------
def test_2_material_only():
    requirement = RequirementSchema(raw_text="음극의 두께를 측정할 수 있는 검사기를 찾아줘.")
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm is None


# ---------------------------------------------------------------
# TEST 3 — width만 있는 경우
# ---------------------------------------------------------------
def test_3_width_only():
    requirement = RequirementSchema(raw_text="폭 5 mm인 전극의 두께를 측정할 수 있는 검사기를 찾아줘.")
    apply_deterministic_extraction(requirement)

    assert requirement.target.width_mm == 5.0
    # "전극"이 문장에 실제로 등장하므로 material이 채워져도 무방(허용). 강제하지는 않는다.


# ---------------------------------------------------------------
# TEST 4 — 양극
# ---------------------------------------------------------------
def test_4_material_positive_electrode():
    requirement = RequirementSchema(raw_text="양극 폭 10 mm의 두께를 측정하는 검사기를 찾아줘.")
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "양극"
    assert requirement.target.width_mm == 10.0


# ---------------------------------------------------------------
# TEST 5 — 분리막
# ---------------------------------------------------------------
def test_5_material_separator():
    requirement = RequirementSchema(raw_text="분리막 폭 20 mm의 두께를 측정하는 검사기를 찾아줘.")
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "분리막"
    assert requirement.target.width_mm == 20.0


# ---------------------------------------------------------------
# TEST 6 — LLM이 material/width_mm을 누락시키는 상황을 모킹 (parse_requirement_text 경로)
# ---------------------------------------------------------------
def test_6_llm_omits_material_and_width_deterministic_extraction_fills_them():
    llm_stub = RequirementSchema(inspection_items=["thickness"])  # material/width_mm 둘 다 None
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement = parse_requirement_text(_REPORTED_QUERY)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 5.0
    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 300.0
    assert requirement.required_accuracy_um == 0.5


# ---------------------------------------------------------------
# TEST 7 — 추가 질문 판단: material/width 관련 질문이 더 이상 나오면 안 된다
# ---------------------------------------------------------------
def test_7_no_material_or_width_followup_questions():
    llm_stub = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text=_REPORTED_QUERY)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 5.0
    assert "target.material" not in validation.missing_fields
    assert "target.width_mm" not in validation.missing_fields
    assert "검사 대상이 무엇인가요? (예: 양극, 음극, 분리막, 전극 전반)" not in validation.questions
    assert "검사 대상의 폭(width, mm)은 얼마인가요?" not in validation.questions


# ---------------------------------------------------------------
# 이미 채워진 값이 raw_text에 근거가 없으면 그대로 유지되는지(과도한 override 방지)
# ---------------------------------------------------------------
def test_does_not_override_when_raw_text_has_no_clear_match():
    llm_stub = RequirementSchema(target={"material": "전극", "width_mm": 400.0}, inspection_items=["profile_3d"])
    with mock.patch(
        "agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub
    ):
        requirement = parse_requirement_text("3D 표면 형상을 측정하고 최소 10um 크기의 표면 결함을 검출할 수 있는 검사기가 필요하다.")

    # raw_text에 material/width에 대한 명확한 근거가 없으므로 LLM 결과가 그대로 유지되어야 한다.
    assert requirement.target.material == "전극"
    assert requirement.target.width_mm == 400.0
