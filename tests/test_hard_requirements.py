"""
Hard Requirement Validation 전용 테스트 — agent.candidate_matcher.build_candidates가
PASS/FAIL/UNKNOWN을 올바르게 판정하는지, 이번 작업에서 수정한 정책(문제3/6/7
+ 회귀 테스트 작성 중 발견한 부가 버그들)을 중심으로 검증한다. 실제 문서
extraction은 tests/test_candidate_extraction.py가 이미 다루므로, 여기서는
합성(synthetic) 문서로 판정 로직 자체에 집중한다.

실행:
    pytest tests/test_hard_requirements.py -v
    pytest -m validation -v
"""
from __future__ import annotations

import pytest
from langchain_core.documents import Document

from agent.candidate_matcher import build_candidates, select_best_candidate
from agent.schemas import RequirementRange, RequirementSchema, RequirementTarget, RequirementValue

pytestmark = pytest.mark.validation


def _mk_doc(content: str, filename: str = "SPEC-TEST.md") -> Document:
    return Document(page_content=content, metadata={"filename": filename, "source": filename, "source_type": "markdown", "chunk_id": 0})


# ---------------------------------------------------------------
# 문제3: Measurement Range (Z)만 있다고 Thickness Measurement를 PASS로
# 판정하면 안 된다 — Equipment Type/Notes에 명시적 근거가 있어야 한다.
# ---------------------------------------------------------------
def test_thickness_unknown_when_only_range_field_present_no_explicit_evidence():
    requirement = RequirementSchema(inspection_items=["thickness"])
    doc = _mk_doc(
        "## General\n\n- Equipment Type: High Speed 3D Inspection System\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| Measurement Range (Z) | 0 ~ 1000 μm |\n\n"
        "## Notes\n\nPerforms continuous inline three-dimensional surface profiling.\n"
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Thickness Measurement"].result == "UNKNOWN"


def test_thickness_pass_when_equipment_type_mentions_thickness():
    requirement = RequirementSchema(inspection_items=["thickness"])
    doc = _mk_doc(
        "## General\n\n- Equipment Type: Thickness Inspection\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| Measurement Range (Z) | 0 ~ 800 μm |\n"
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Thickness Measurement"].result == "PASS"
    assert "0 ~ 800" in by_item["Thickness Measurement"].found_text


def test_thickness_pass_when_only_notes_mentions_thickness():
    """Equipment Type은 모호해도 Notes에 명시적 근거가 있으면 인정한다."""
    requirement = RequirementSchema(inspection_items=["thickness"])
    doc = _mk_doc(
        "## General\n\n- Equipment Type: Multi Inspection\n\n"
        "## Notes\n\nSupports combined electrode thickness and surface defect inspection.\n"
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Thickness Measurement"].result == "PASS"


def test_thickness_fail_when_explicitly_not_supported_even_with_range_field():
    requirement = RequirementSchema(inspection_items=["thickness"])
    doc = _mk_doc(
        "## General\n\n- Equipment Type: 2D Vision Inspection System\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| X Resolution | 25 μm |\n\n"
        "## Thickness Measurement\n\n- Not Supported\n"
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Thickness Measurement"].result == "FAIL"


# ---------------------------------------------------------------
# 문제2/6: 세부 결함 항목은 서로 독립적으로 AND 판정되어야 한다.
# ---------------------------------------------------------------
def test_scratch_and_contamination_verified_independently():
    requirement = RequirementSchema(inspection_items=["scratch", "contamination"])
    only_scratch = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Defect Types | Scratch, Crack, Particle |\n", filename="ONLY-SCRATCH.md"
    )
    both = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Defect Types | Scratch, Contamination |\n", filename="BOTH.md"
    )
    candidates = build_candidates(requirement, [only_scratch, both])
    by_source = {c.source_document: c for c in candidates}

    only_scratch_items = {m.item: m.result for m in by_source["ONLY-SCRATCH.md"].matches}
    assert only_scratch_items["Scratch Detection"] == "PASS"
    assert only_scratch_items["Contamination Detection"] == "FAIL"
    assert by_source["ONLY-SCRATCH.md"].status == "FAIL"

    both_items = {m.item: m.result for m in by_source["BOTH.md"].matches}
    assert both_items["Scratch Detection"] == "PASS"
    assert both_items["Contamination Detection"] == "PASS"
    assert by_source["BOTH.md"].status == "PASS"


# ---------------------------------------------------------------
# 문제5(구 요청서 문제4): 최소 검출 결함 크기 Hard Requirement.
# ---------------------------------------------------------------
def test_minimum_defect_size_pass_fail_unknown():
    requirement = RequirementSchema(minimum_defect_size=RequirementValue(value=5.0, unit="um", operator="<="))
    smaller = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 3 μm |\n", filename="SMALLER.md"
    )
    larger = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 15 μm |\n", filename="LARGER.md"
    )
    no_data = _mk_doc("## General\n\n- Manufacturer: X\n", filename="NO-DATA.md")
    candidates = build_candidates(requirement, [smaller, larger, no_data])
    by_source = {c.source_document: c for c in candidates}
    assert by_source["SMALLER.md"].matches[0].result == "PASS"
    assert by_source["LARGER.md"].matches[0].result == "FAIL"
    assert by_source["NO-DATA.md"].matches[0].result == "UNKNOWN"


def test_minimum_defect_size_not_added_when_user_did_not_request_it():
    requirement = RequirementSchema(inspection_items=["scratch"])
    doc = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 3 μm |\n| Defect Types | Scratch |\n"
    )
    candidates = build_candidates(requirement, [doc])
    items = {m.item for m in candidates[0].matches}
    assert "Minimum Defect Size" not in items


# ---------------------------------------------------------------
# 문제7: Accuracy를 요구하지 않았으면 Hard Requirement 목록에 없어야 한다.
# ---------------------------------------------------------------
def test_accuracy_not_evaluated_when_not_requested():
    requirement = RequirementSchema(target=RequirementTarget(width_mm=600.0))
    doc = _mk_doc(
        "## Inspection Target\n\n- Maximum Electrode Width: 800 mm\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n| Accuracy | ±5.0 μm |\n"
    )
    candidates = build_candidates(requirement, [doc])
    items = {m.item for m in candidates[0].matches}
    assert "Accuracy" not in items


# ---------------------------------------------------------------
# 문제6: PASS/PARTIAL/FAIL 3단계 우선순위 — PASS가 하나라도 있으면 PARTIAL은
# 최종 추천되지 않는다.
# ---------------------------------------------------------------
def test_pass_candidate_always_beats_partial_candidate_regardless_of_pass_count():
    requirement = RequirementSchema(
        target=RequirementTarget(width_mm=100.0),
        measurement_range=RequirementRange(min=0.0, max=100.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    full_pass = _mk_doc(
        "## Inspection Target\n\n- Maximum Electrode Width: 500 mm\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| Measurement Range | 0 ~ 200 μm |\n| Accuracy | ±0.5 μm |\n",
        filename="FULL-PASS.md",
    )
    partial_missing_accuracy = _mk_doc(
        "## Inspection Target\n\n- Maximum Electrode Width: 500 mm\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| Measurement Range | 0 ~ 200 μm |\n",
        filename="PARTIAL.md",
    )
    candidates = build_candidates(requirement, [full_pass, partial_missing_accuracy])
    best = select_best_candidate(candidates)
    assert best.source_document == "FULL-PASS.md"
    assert best.status == "PASS"


def test_no_pass_candidate_falls_back_to_best_partial_not_fail():
    requirement = RequirementSchema(target=RequirementTarget(width_mm=100.0))
    partial = _mk_doc(
        "## Inspection Target\n\n- Maximum Electrode Width: 500 mm\n", filename="PARTIAL.md"
    )  # Width 데이터는 없음(UNKNOWN 조건 없음이라 실제로는 PASS겠지만, 여기선 FAIL 후보와 비교 목적)
    outright_fail = _mk_doc(
        "## Inspection Target\n\n- Maximum Electrode Width: 50 mm\n", filename="FAIL.md"
    )
    candidates = build_candidates(requirement, [partial, outright_fail])
    by_source = {c.source_document: c for c in candidates}
    assert by_source["FAIL.md"].status == "FAIL"
    best = select_best_candidate(candidates)
    assert best.source_document != "FAIL.md"
