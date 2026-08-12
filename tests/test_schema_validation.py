"""
SpecificationSchema 자체(필드 구조, Optional 처리, Status/Source 구조)에 대한
검증 테스트. 요청서 26절 Test 1~8에 대응한다.
"""
import pytest
from pydantic import ValidationError

from agent.schemas import (
    ComplianceRecord,
    DefectDetection,
    OpticalSystem,
    SourcedNumber,
    SourceRef,
    SpecificationSchema,
)


# ---------------------------------------------------------------
# Test 1: 정상적인 Specification JSON
# ---------------------------------------------------------------
def test_valid_specification_json_parses():
    data = {
        "equipment": {"name": "전극 두께 검사기", "measurement_principle": "laser"},
        "inspection_target": {"material": "전극", "width_mm": 500},
        "inspection_items": ["thickness"],
        "measurement_performance": {
            "accuracy_um": {"value": 0.5, "unit": "um", "operator": "<=", "status": "VERIFIED"}
        },
    }
    spec = SpecificationSchema(**data)
    assert spec.equipment.name == "전극 두께 검사기"
    assert spec.measurement_performance.accuracy_um.value == 0.5


# ---------------------------------------------------------------
# Test 2: 필수 필드 누락 — SpecificationSchema 자체는 전부 Optional이라
# pydantic 레벨 에러가 아니라 SpecificationValidator(agent/spec_validator.py)가
# 잡아야 한다 (요청서 3절 "모든 필드를 필수로 만들지 않는다"와 일관).
# ---------------------------------------------------------------
def test_missing_required_business_fields_caught_by_validator_not_pydantic():
    from agent.spec_validator import validate_specification

    spec = SpecificationSchema()  # material, inspection_items 등 전부 비어있음
    result = validate_specification(spec)
    assert result.is_valid is False
    assert any(i.field == "inspection_target.material" for i in result.issues)
    assert any(i.field == "inspection_items" for i in result.issues)


# ---------------------------------------------------------------
# Test 3: 잘못된 unit — SpecificationValidator가 필드명과 unit 불일치를 경고로 잡는다
# ---------------------------------------------------------------
def test_wrong_unit_flagged_as_warning():
    from agent.spec_validator import validate_specification

    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.measurement_performance.accuracy_um = SourcedNumber(value=0.5, unit="mm", status="VERIFIED")

    result = validate_specification(spec)
    assert any("단위" in i.message and i.field == "measurement_performance.accuracy_um" for i in result.issues)


def test_compound_unit_suffix_not_falsely_flagged():
    """
    회귀: '_mm_s'로 끝나는 필드(line_speed_mm_s 등)가 실제로 'mm/s' 단위를 갖고 있으면
    '_s' 접미사 규칙에도 다시 걸려서 거짓 경고("s를 기대하는데 mm/s")를 내면 안 된다.
    """
    from agent.spec_validator import validate_specification

    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.inspection_performance.line_speed_mm_s = SourcedNumber(value=1500.0, unit="mm/s", status="VERIFIED")

    result = validate_specification(spec)
    assert not any(i.field == "inspection_performance.line_speed_mm_s" and "단위" in i.message for i in result.issues)


# ---------------------------------------------------------------
# Test 4: 잘못된 숫자 범위 (분해능 > 측정 범위, 음수 값 등)
# ---------------------------------------------------------------
def test_invalid_numeric_range_flagged():
    from agent.spec_validator import validate_specification

    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.measurement_performance.resolution_um = SourcedNumber(value=500, unit="um", status="VERIFIED")
    spec.measurement_performance.measurement_range = SourcedNumber(value=200, unit="um", status="VERIFIED")

    result = validate_specification(spec)
    assert result.is_valid is False
    assert any("분해능" in i.message for i in result.issues)

    spec2 = SpecificationSchema()
    spec2.inspection_target.material = "전극"
    spec2.inspection_items = ["thickness"]
    spec2.equipment.name = "테스트 장비"
    spec2.measurement_performance.accuracy_um = SourcedNumber(value=-1.0, unit="um", status="VERIFIED")
    result2 = validate_specification(spec2)
    assert any("음수" in i.message for i in result2.issues)


# ---------------------------------------------------------------
# Test 5: UNKNOWN — 값도 status도 채워지지 않으면 기본값이 UNKNOWN이어야 한다
# ---------------------------------------------------------------
def test_unknown_is_default_status():
    sn = SourcedNumber()
    assert sn.status == "UNKNOWN"
    assert sn.value is None

    spec = SpecificationSchema()
    assert spec.measurement_performance.accuracy_um is None  # 아예 안 채워지면 필드 자체가 None


# ---------------------------------------------------------------
# Test 6: INFERRED — 추정값은 status="INFERRED"로 명확히 구분되고,
# needs_confirmation에 자동으로 잡혀야 한다
# ---------------------------------------------------------------
def test_inferred_status_flows_into_needs_confirmation():
    from agent.spec_generator import _collect_needs_confirmation

    spec = SpecificationSchema()
    spec.measurement_performance.accuracy_um = SourcedNumber(value=0.7, unit="um", status="INFERRED")
    spec.measurement_performance.resolution_um = SourcedNumber(value=0.1, unit="um", status="VERIFIED")

    needs_confirmation = _collect_needs_confirmation(spec)
    assert "measurement_performance.accuracy_um" in needs_confirmation
    assert "measurement_performance.resolution_um" not in needs_confirmation


# ---------------------------------------------------------------
# Test 7: Source 포함 — document/page/slide/section 등 세부 근거가 보존되는지
# ---------------------------------------------------------------
def test_source_ref_preserves_detailed_location():
    source = SourceRef(document="vendor_spec.pdf", page=12, section="Measurement Performance", source_type="vendor_document")
    sn = SourcedNumber(value=0.5, unit="um", status="VERIFIED", source=source)

    dumped = sn.model_dump()
    assert dumped["source"]["document"] == "vendor_spec.pdf"
    assert dumped["source"]["page"] == 12
    assert dumped["source"]["section"] == "Measurement Performance"
    assert dumped["source"]["source_type"] == "vendor_document"

    # PPTX에서 온 경우 slide 번호도 보존되어야 한다
    pptx_source = SourceRef(document="internal_spec.pptx", slide=4)
    sn2 = SourcedNumber(value=1.0, status="VERIFIED", source=pptx_source)
    assert sn2.source.slide == 4


# ---------------------------------------------------------------
# Test 8: Optional optical field 누락 — Optical System이 없는 장비도
# Schema validation을 통과해야 한다 (요청서 26절 명시)
# ---------------------------------------------------------------
def test_optional_optical_system_fields_all_absent_still_validates():
    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "접촉식 두께 게이지"
    spec.equipment.measurement_principle = "contact"
    # optical_system은 완전히 비워둠 (접촉식 장비이므로 광학계 자체가 없음)
    assert spec.optical_system == OpticalSystem()

    from agent.spec_validator import validate_specification

    result = validate_specification(spec)
    # optical_system이 비어 있다는 이유로 에러가 나면 안 된다 (선택 필드이므로)
    assert not any("optical_system" in i.field for i in result.issues)


# ---------------------------------------------------------------
# 추가: ComplianceRecord / defect_types 임의 추가 금지 원칙 관련 회귀
# ---------------------------------------------------------------
def test_compliance_record_shape():
    record = ComplianceRecord(
        item="Accuracy", unit="um", requirement=1.0, specification=0.5,
        operator="<=", result="PASS", reason="0.5um <= 1.0um",
    )
    assert record.result == "PASS"


def test_defect_types_default_empty_not_invented():
    dd = DefectDetection()
    assert dd.defect_types == []  # AI가 임의로 채우지 않는 한 항상 빈 리스트
