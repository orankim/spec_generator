"""
회귀 테스트: "AI가 이해한 요구사항" 화면에서 target.material이 "미정"으로 표시되고
"검사 대상이 무엇인가요?" 추가 질문이 불필요하게 다시 나오던 문제.

사용자가 실제로 보고한 질문:
    "음극 폭 300 mm의 두께와 3D 프로파일을 0~500 μm 범위에서 ±2 μm 이하
    정확도로 측정할 수 있는 검사기를 찾아줘."

원인: agent/requirement_parser.py::apply_deterministic_extraction()의 material
추출(_extract_material)이 `keyword in text` 리터럴 부분 문자열 비교인데, 이
비교는 Unicode 정규화 형태(NFC/NFD)에 민감하다. 한글 "음극"이 완성형(NFC,
코드포인트 2개: U+110B U+1173 U+11B7 U+1100... 등 자모 4개로 분해되는 NFD와
달리 U+C74C U+ADF9 형태)이 아니라 자모 분해형(NFD)으로 들어오면, 소스 코드의
리터럴 "음극"(NFC로 저장됨)과 바이트 단위로 달라 매칭이 조용히 실패한다.
사용자가 다른 앱/문서에서 "음극"이라는 단어를 복사해 문장 중간에 붙여넣는
경우 등 실제 브라우저/OS 조합에서 NFD가 전달될 수 있다. 폭/측정범위/정확도는
숫자+단위 정규식이라 한글 정규화와 무관해 영향을 받지 않았다 — 그래서 사용자가
"폭/측정범위/정확도는 정상, 검사 대상만 미정"이라고 정확히 보고한 것과 일치한다.

수정: apply_deterministic_extraction()이 매칭에 쓰는 로컬 text 변수를 함수
시작 시 unicodedata.normalize("NFC", ...)로 정규화한다. requirement.raw_text
필드 자체(사용자 원문 표시/감사 목적)는 건드리지 않는다.
"""
import unicodedata
import unittest.mock as mock

from agent.pipeline import analyze_requirement
from agent.requirement_parser import apply_deterministic_extraction
from agent.schemas import RequirementSchema

_REPORTED_QUERY = (
    "음극 폭 300 mm의 두께와 3D 프로파일을 0~500 μm 범위에서 ±2 μm 이하 "
    "정확도로 측정할 수 있는 검사기를 찾아줘."
)


# ---------------------------------------------------------------
# TEST 1
# ---------------------------------------------------------------
def test_1_simple_positive_electrode_width_no_material_followup():
    llm_stub = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text="양극 폭 100 mm의 두께를 측정")

    assert requirement.target.material == "양극"
    assert "target.material" not in validation.missing_fields
    assert "검사 대상이 무엇인가요? (예: 양극, 음극, 분리막, 전극 전반)" not in validation.questions


# ---------------------------------------------------------------
# TEST 2 — 사용자가 실제로 보고한 질문 그대로
# ---------------------------------------------------------------
def test_2_reported_query_material_width_range_accuracy_no_material_followup():
    llm_stub = RequirementSchema(inspection_items=["thickness", "profile_3d"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text=_REPORTED_QUERY)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 300.0
    assert set(requirement.inspection_items) == {"thickness", "profile_3d"}
    assert requirement.measurement_range is not None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 500.0
    assert requirement.required_accuracy_um == 2.0

    assert "target.material" not in validation.missing_fields
    assert "검사 대상이 무엇인가요? (예: 양극, 음극, 분리막, 전극 전반)" not in validation.questions


# ---------------------------------------------------------------
# TEST 3
# ---------------------------------------------------------------
def test_3_separator_material_no_followup():
    llm_stub = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text="분리막의 두께를 검사하는 장비")

    assert requirement.target.material == "분리막"
    assert "target.material" not in validation.missing_fields


# ---------------------------------------------------------------
# TEST 4 — 이 요청서는 원래 "전극 표면을 검사하는 장비" -> material="전극",
# 추가 질문 없음을 요구했다. 그러나 이는 바로 이전 작업(PR #19)에서 사용자가
# 명시적으로 요구해 이미 구현/테스트된 반대 정책("전극"은 양극/음극/분리막 같은
# 구체적 소재명이 아니라 이 앱의 도메인 범용어이므로 material=None/미정으로
# 남아야 한다 — tests/test_llm_hallucination_and_categorical_hardreq.py의
# test_llm_hallucinated_material_is_cleared_test2 등)와 정면으로 충돌해,
# 사용자에게 확인한 결과 "기존 정책 유지"로 결정되었다. 그래서 이 테스트는
# 요청서의 TEST 4를 그대로 구현하지 않고, 기존 정책이 이번 변경으로 깨지지
# 않았음을 확인하는 회귀 테스트로 남긴다.
# ---------------------------------------------------------------
def test_4_generic_electrode_alone_stays_unset_per_existing_policy():
    llm_stub = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text="전극 표면을 검사하는 장비")

    assert requirement.target.material is None
    assert "target.material" in validation.missing_fields


# ---------------------------------------------------------------
# TEST 5 — material 근거가 전혀 없으면 여전히 미정 + 추가 질문 가능
# ---------------------------------------------------------------
def test_5_no_material_evidence_stays_none_and_followup_possible():
    llm_stub = RequirementSchema(inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text="두께를 0~200 μm 범위에서 측정")

    assert requirement.target.material is None
    assert "target.material" in validation.missing_fields
    assert "검사 대상이 무엇인가요? (예: 양극, 음극, 분리막, 전극 전반)" in validation.questions


# =================================================================
# Unicode 정규화(NFC/NFD) 회귀 테스트 — 실제 원인에 대한 직접 검증
# =================================================================
def test_material_matches_regardless_of_full_text_normalization_form():
    """전체 원문이 NFD로 정규화되어 들어와도(예: 특정 OS/IME 조합) material이 정상 추출되어야 한다."""
    text_nfd = unicodedata.normalize("NFD", _REPORTED_QUERY)
    requirement = RequirementSchema(raw_text=text_nfd)
    apply_deterministic_extraction(requirement)
    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 300.0
    assert requirement.measurement_range.max == 500.0


def test_material_matches_when_only_the_material_word_is_nfd_pasted_mid_sentence():
    """
    사용자가 다른 앱에서 복사한 "음극"(NFD)만 문장 중간에 붙여넣고 나머지는 정상
    타이핑(NFC)한 경우를 재현한다 — 사용자가 보고한 정확한 증상(재질만 실패,
    폭/범위/정확도는 정상)과 일치하는 시나리오.
    """
    material_nfd = unicodedata.normalize("NFD", "음극")
    text = material_nfd + " 폭 300 mm의 두께와 3D 프로파일을 0~500 μm 범위에서 ±2 μm 이하 정확도로 측정할 수 있는 검사기를 찾아줘."
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)

    assert requirement.target.material == "음극"
    assert requirement.target.width_mm == 300.0
    assert requirement.measurement_range.max == 500.0
    assert requirement.required_accuracy_um == 2.0


def test_raw_text_field_itself_is_not_mutated_by_normalization():
    """정규화는 매칭에만 쓰이고, requirement.raw_text(사용자 원문)는 그대로 보존되어야 한다."""
    material_nfd = unicodedata.normalize("NFD", "음극")
    text = material_nfd + " 폭 300 mm의 두께를 측정"
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)
    assert requirement.raw_text == text  # 원문 그대로 유지(정규화된 형태로 바뀌면 안 됨)
