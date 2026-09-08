"""
견적 통합 작업 2/12단계 회귀 테스트 — "폭 5mm 양극의 절연부를 프로파일 형태로
측정할 수 있는 장비를 찾아줘."가 5mm(5.0)로 정확히 파싱되는지 확인한다.

배경: 이 작업의 이전 테스트 라운드에서 "폭 5m ..."(단위 오타)를 실제 의도인
"폭 5mm ..."로 정정했다. "m"과 "mm"은 agent/units.py의 단위 변환 배율이
1,000배 차이 나므로(m=1,000,000 canonical, mm=1,000 canonical) 단위 파싱이
잘못되면 5mm가 5000mm 또는 5m(=5000mm와 동일한 스케일 오류)로 둔갑할 수 있다.
이 파일은 LLM 없이(결정론적 추출 계층만으로) 그 값이 항상 5.0으로 고정되는지
지키는 회귀 테스트다 — 실제로는 코드에 버그가 없었음을 확인했지만(조사 결과),
향후 units.py/requirement_parser.py가 바뀌어도 이 계약이 깨지지 않도록 고정한다.
"""
from __future__ import annotations

import unittest.mock as mock

from agent.requirement_parser import apply_deterministic_extraction, parse_requirement_text
from agent.schemas import RequirementSchema
from agent.units import convert

_TEXT = "폭 5mm 양극의 절연부를 프로파일 형태로 측정할 수 있는 장비를 찾아줘."


def test_width_extracted_as_5mm_not_5000mm_not_bare_5():
    requirement = RequirementSchema(raw_text=_TEXT)
    apply_deterministic_extraction(requirement, trust_llm_guess=False)
    assert requirement.target.width_mm == 5.0
    assert requirement.target.width_mm != 5000.0
    assert requirement.target.material == "양극"


def test_width_extraction_survives_llm_hallucinating_5000mm():
    """소형 LLM이 raw_text에 없는 값(예: 5000mm)을 환각으로 채우더라도,
    trust_llm_guess=False 결정론적 추출이 raw_text의 실제 근거(5mm)로 덮어써야
    한다(agent/requirement_parser.py 상단 주석에 명시된 기존 정책)."""
    requirement = RequirementSchema(raw_text=_TEXT)
    requirement.target.width_mm = 5000.0  # LLM이 잘못 채웠다고 가정.
    apply_deterministic_extraction(requirement, trust_llm_guess=False)
    assert requirement.target.width_mm == 5.0


def test_inspection_item_profile_3d_detected_without_llm():
    requirement = RequirementSchema(raw_text=_TEXT)
    apply_deterministic_extraction(requirement, trust_llm_guess=False)
    # apply_deterministic_extraction 자체는 inspection_items를 채우지 않으므로
    # (그 책임은 parse_requirement_text의 hallucination 방지 필터에 있다) 여기서는
    # 그 필터가 쓰는 것과 동일한 키워드 테이블로 "프로파일" -> profile_3d 매핑이
    # 실제로 존재하는지 직접 확인한다.
    from agent.requirement_parser import _INSPECTION_ITEM_KEYWORDS

    assert any(kw in _TEXT for kw in _INSPECTION_ITEM_KEYWORDS["profile_3d"])


def test_full_parse_requirement_text_with_llm_stubbed_empty():
    """parse_requirement_text() 전체 경로(LLM 호출부만 빈 응답으로 스텁 — worst
    case)로도 5mm/양극/profile_3d가 살아남는지 확인한다."""
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=RequirementSchema()):
        requirement = parse_requirement_text(_TEXT)
    assert requirement.target.width_mm == 5.0
    assert requirement.target.material == "양극"
    assert "profile_3d" in requirement.inspection_items


def test_unit_table_sanity_mm_is_not_m():
    """단위 배율 회귀 고정 — mm과 m을 혼동하면 5mm가 5000mm로 등가 취급된다."""
    assert convert(5.0, "mm", "mm") == 5.0
    assert convert(5.0, "m", "mm") == 5000.0
    assert convert(5.0, "mm", "mm") != convert(5.0, "m", "mm")
