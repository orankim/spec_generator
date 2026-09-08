"""
Spatial Performance(X/Y/Z Range·Resolution/FOV/Working Distance/Pixel Size)
데이터 보강 작업 — agent/candidate_matcher.py의 새 추출 로직과, 그로 인해
드러난 격리 버그(요청서 1절: "사양서에 존재해도 구조적으로 읽히지 않는 문제")에
대한 회귀 테스트.

핵심 배경 1: "## Spatial Performance" 절을 sample_specs에 추가하자, RAG chunk가
"## Measurement Performance"/"## Spatial Performance"를 서로 다른 chunk로
나누고 검색 관련도 순으로 재배열할 수 있어(원본 문서 순서 비보장), "X Range:
0 ~ 800 mm"(전극 폭, mm) 같은 행이 fact.range(Hard Requirement가 실제로 비교하는
"주" 측정 범위, 보통 μm 단위 두께/깊이)에 잘못 섞여 들어가는 사고가 실제로
발생했다(tests/test_regression.py의 T020/QA019가 잡아냄) — "0~5000 μm 측정
가능?"라는 두께 조건이 mm 단위 전극 폭과 잘못 비교되어 엉뚱하게 PASS 판정됨.
수정: agent.candidate_matcher._is_range_label이 x/y/z range 라벨을 제외한다.

핵심 배경 2: Z Range/Z Resolution은 sample_specs 원문에 중복으로 쓰지 않는다 —
Measurement Performance의 주 측정 범위/해상도(fact.range/fact.resolution)를
CandidateEquipmentFact 조립 시점에 그대로 재사용한다(코드 레벨 기본값). 문자
그대로 같은 값을 "## Spatial Performance"에도 다시 적으면 heading 기반 RAG
chunking이 새 chunk를 만들어 fake-hash 임베딩 기반 결정론적 테스트의 검색
순위가 흔들리는 부작용이 있었다.
"""
from __future__ import annotations

from langchain_core.documents import Document

from agent.candidate_matcher import build_candidates
from agent.schemas import RequirementRange, RequirementSchema


def _doc(text: str) -> Document:
    return Document(page_content=text, metadata={"filename": "SPEC-TEST.md"})


_SAMPLE_TEXT = """# Equipment Specification

## General

- Manufacturer: TestCo
- Model: TC-1
- Equipment Type: Electrode 3D Inspection System
- Measurement Principle: 3D Laser Profilometry
- Inspection Mode: Inline

## Inspection Target

- Target: Battery Electrode
- Maximum Electrode Width: 800 mm

## Measurement Performance

| Item | Specification |
|---|---|
| Measurement Range (Z) | 0 ~ 300 um |
| Accuracy | +/-1.0 um |
| Z Resolution | 0.1 um |

## Spatial Performance

| Item | Specification |
|---|---|
| X Range | 0 ~ 800 mm |

## Notes

Designed for continuous inline electrode thickness measurement.
"""


def _fact():
    candidates = build_candidates(RequirementSchema(), [_doc(_SAMPLE_TEXT)])
    return candidates[0].equipment_fact


# ---------------------------------------------------------------------------
# 회귀: X/Y/Z Range(mm, 전극 폭)가 Hard Requirement용 "주" 측정 범위(fact.range,
# 보통 um 단위 두께/깊이)에 절대 섞이면 안 된다.
# ---------------------------------------------------------------------------
def test_spatial_x_range_does_not_pollute_primary_hard_requirement_range():
    requirement = RequirementSchema(
        raw_text="0~5000 um 범위를 측정할 수 있는 장비를 찾아줘.",
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=5000.0, unit="um"),
    )
    candidates = build_candidates(requirement, [_doc(_SAMPLE_TEXT)])
    by_item = {m.item: m for m in candidates[0].matches}
    # 실제 두께 범위(0~300um)는 요구 범위(0~5000um)를 포함하지 못하므로 FAIL이어야
    # 한다 — X Range(0~800mm=800,000um)와 섞이면 잘못 PASS가 된다(실제 있었던 버그).
    assert by_item["Measurement Range"].result == "FAIL"


def test_candidate_equipment_fact_x_range_populated_from_spatial_section():
    fact = _fact()
    assert fact.x_range_min == 0.0 and fact.x_range_max == 800.0 and fact.x_range_unit == "mm"


def test_z_range_and_resolution_fall_back_to_primary_measurement_performance():
    """sample_specs 원문에는 "Z Range"/"Z Resolution" 행이 없어도(위 _SAMPLE_TEXT
    참고 — Spatial Performance에는 X Range만 있다), Measurement Performance의
    주 범위/해상도가 Z Range/Z Resolution 기본값으로 코드에서 그대로 재사용되어야
    한다(agent.candidate_matcher._extract_candidate_fact의 CandidateEquipmentFact
    조립부)."""
    fact = _fact()
    assert fact.z_range_min == 0.0 and fact.z_range_max == 300.0
    assert fact.z_resolution_value == 0.1


def test_spatial_fields_absent_when_no_spatial_performance_section_and_no_width():
    text = (
        _SAMPLE_TEXT.split("## Inspection Target")[0]
        + "## Inspection Target\n\n- Target: Battery Electrode\n\n"
        + _SAMPLE_TEXT.split("## Measurement Performance")[1].split("## Spatial Performance")[0]
        + "## Notes\n\nNo spatial section, no width.\n"
    )
    candidates = build_candidates(RequirementSchema(), [_doc(text)])
    fact = candidates[0].equipment_fact
    assert fact.x_range_min is None
    assert fact.y_range_min is None
    assert fact.working_distance_value is None
    assert fact.pixel_size_value is None
    # Z 값은 Measurement Performance 자체에서 여전히 정상적으로 재사용되어야 한다.
    assert fact.z_range_min == 0.0 and fact.z_range_max == 300.0


def test_lateral_resolution_captured_directly_from_measurement_performance():
    """카메라 비전 계열 사양서는 X/Y Resolution을 "## Measurement Performance"
    표에 직접 적는다(예: SPEC-006) — sample_specs에는 이 값을 "## Spatial
    Performance"에 중복으로 적지 않으므로, agent.candidate_matcher가 Measurement
    Performance에서 직접 뽑아 fact.x_resolution/y_resolution에 채워야 한다. 동시에
    fact.resolution(주 Resolution, Hard Requirement용)에는 여전히 섞이면 안 된다
    (agent.candidate_matcher._is_primary_resolution_label의 기존 보호)."""
    text = _SAMPLE_TEXT.replace(
        "| Z Resolution | 0.1 um |\n",
        "| Z Resolution | 0.1 um |\n| X Resolution | 20 um |\n| Y Resolution | 20 um |\n",
        1,
    )
    candidates = build_candidates(RequirementSchema(), [_doc(text)])
    fact = candidates[0].equipment_fact
    assert fact.resolution_value == 0.1  # 여전히 Z(주) Resolution
    assert fact.x_resolution_value == 20.0
    assert fact.y_resolution_value == 20.0


def test_xy_resolution_single_row_fills_both_axes():
    """SPEC-002/007처럼 "XY Resolution" 한 행으로 X/Y를 함께 표기하는 기존 관행도
    지원해야 한다."""
    text = _SAMPLE_TEXT.replace(
        "## Spatial Performance\n\n| Item | Specification |\n|---|---|\n| X Range | 0 ~ 800 mm |\n",
        "## Spatial Performance\n\n| Item | Specification |\n|---|---|\n| XY Resolution | 0.8 um |\n",
    )
    candidates = build_candidates(RequirementSchema(), [_doc(text)])
    fact = candidates[0].equipment_fact
    assert fact.x_resolution_value == 0.8
    assert fact.y_resolution_value == 0.8
