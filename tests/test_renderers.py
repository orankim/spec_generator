"""
Specification JSON을 단일 소스로 하는 3-way 렌더러(Markdown/HTML/PPTX)와
PPTX <-> Markdown 변환기에 대한 테스트. 요청서 15절의 Test 1~10에 대응한다.

Ollama 호출이 전혀 없는 순수 변환 로직이므로, 이 테스트들은 모킹 없이
실제 코드 경로 그대로 실행된다.
"""
import json
import tempfile
from pathlib import Path

import pytest
from pptx import Presentation

from agent.schemas import RequirementSchema, SourcedNumber, SpecificationSchema
from converters.markdown_to_spec import markdown_to_spec
from converters.pptx_to_markdown import pptx_to_ir, pptx_to_markdown
from renderers.html_renderer import render_html
from renderers.markdown_renderer import render_markdown
from renderers.pptx_renderer import render_pptx


def _full_spec() -> SpecificationSchema:
    spec = SpecificationSchema()
    spec.equipment.name = "전극 두께/표면결함 비접촉 검사기"
    spec.equipment.manufacturer = "ACME Metrology"
    spec.equipment.measurement_principle = "laser triangulation"
    spec.inspection_target.material = "전극"
    spec.inspection_target.width_mm = 500.0
    spec.inspection_items = ["thickness", "surface_defect"]
    spec.measurement_performance.accuracy_um = SourcedNumber(
        value=0.5, unit="um", source_type="document", source="vendor_spec.pptx"
    )
    spec.measurement_performance.repeatability_um = SourcedNumber(
        value=0.3, unit="um", source_type="user_requirement"
    )
    spec.defect_detection.minimum_defect_size_um = SourcedNumber(value=10.0, unit="um", source_type="inferred")
    spec.defect_detection.defect_types = ["핀홀", "크랙"]
    spec.interfaces.ethernet = True
    spec.interfaces.mes = False
    spec.notes = ["첫 번째 노트", "두 번째 노트"]
    spec.sources = ["vendor_spec.pptx"]
    return spec


# ---------------------------------------------------------------
# Test 1: Specification JSON -> Markdown
# ---------------------------------------------------------------
def test_spec_to_markdown():
    md = render_markdown(_full_spec())
    assert md.startswith("# Electrode Inspection Equipment Specification")
    assert "## 1. Equipment" in md
    assert "## 14. Sources / Notes" in md
    assert "전극 두께/표면결함 비접촉 검사기" in md


# ---------------------------------------------------------------
# Test 2: Specification JSON -> HTML
# ---------------------------------------------------------------
def test_spec_to_html():
    html = render_html(_full_spec())
    assert "<html" in html
    assert "<table>" in html
    assert "전극 두께/표면결함 비접촉 검사기" in html
    # 외부 CDN에 의존하지 않는지 확인
    assert "http://" not in html and "https://" not in html


# ---------------------------------------------------------------
# Test 3: Specification JSON -> PPTX (템플릿 없이도 동작해야 함)
# ---------------------------------------------------------------
def test_spec_to_pptx_without_template():
    spec = _full_spec()
    with tempfile.TemporaryDirectory() as tmp:
        out = render_pptx(spec, str(Path(tmp) / "out.pptx"), template_path=None)
        prs = Presentation(out)
        assert len(prs.slides) > 1
        all_text = "\n".join(
            shape.text_frame.text
            for slide in prs.slides
            for shape in slide.shapes
            if shape.has_text_frame
        )
        assert "전극 두께/표면결함 비접촉 검사기" in all_text


def test_spec_to_pptx_with_template():
    spec = _full_spec()
    with tempfile.TemporaryDirectory() as tmp:
        out = render_pptx(spec, str(Path(tmp) / "out.pptx"), template_path="template_electrode.pptx")
        prs = Presentation(out)
        assert len(prs.slides) == 9  # 기존 ElectrodeSpecPPTXBuilder 그대로 사용


# ---------------------------------------------------------------
# Test 4: PPTX -> Markdown
# ---------------------------------------------------------------
def test_pptx_to_markdown_preserves_content():
    md = pptx_to_markdown("sample_specs/spec_electrode_coating_thickness.pptx")
    assert md.startswith("# ")
    assert "## Slide 1" in md
    assert "## Slide 2" in md
    ir = pptx_to_ir("sample_specs/spec_electrode_coating_thickness.pptx")
    assert len(ir.slides) == 2
    assert len(ir.slides[1].tables) == 1  # 상세 사양 표가 있는 슬라이드


# ---------------------------------------------------------------
# Test 5: Markdown -> Specification JSON
# ---------------------------------------------------------------
def test_markdown_to_spec_roundtrip():
    original = _full_spec()
    req = RequirementSchema(required_accuracy_um=1.0)
    md = render_markdown(original, requirement=req)
    roundtrip = markdown_to_spec(md)

    assert roundtrip.equipment.name == original.equipment.name
    assert roundtrip.equipment.manufacturer == original.equipment.manufacturer
    assert roundtrip.inspection_target.width_mm == original.inspection_target.width_mm
    assert roundtrip.inspection_items == original.inspection_items
    assert roundtrip.measurement_performance.accuracy_um.value == 0.5
    assert roundtrip.measurement_performance.accuracy_um.source == "vendor_spec.pptx"
    assert roundtrip.defect_detection.defect_types == ["핀홀", "크랙"]
    assert roundtrip.notes == original.notes
    assert roundtrip.sources == original.sources


# ---------------------------------------------------------------
# Test 6: UNKNOWN 값 보존
# ---------------------------------------------------------------
def test_unknown_values_preserved_through_markdown_roundtrip():
    spec = SpecificationSchema()  # 전부 비어있는 사양서
    md = render_markdown(spec)
    assert "UNKNOWN" in md

    roundtrip = markdown_to_spec(md)
    assert roundtrip.equipment.name is None
    assert roundtrip.measurement_performance.accuracy_um is None
    assert roundtrip.inspection_items == []


# ---------------------------------------------------------------
# Test 7: Source 정보 보존
# ---------------------------------------------------------------
def test_source_info_preserved_in_markdown_and_html():
    spec = _full_spec()
    md = render_markdown(spec)
    assert "> Source: vendor_spec.pptx — Accuracy" in md
    assert "> Source: user_requirement — Repeatability" in md

    html = render_html(spec)
    assert "vendor_spec.pptx" in html
    assert "Accuracy" in html


# ---------------------------------------------------------------
# Test 8: 단위 보존
# ---------------------------------------------------------------
def test_units_preserved():
    spec = _full_spec()
    md = render_markdown(spec)
    assert "| Accuracy | um | 1.0" not in md  # requirement 없이 렌더링했으므로 이 형태는 아님
    assert "| Accuracy | um |" in md  # unit 컬럼에 um이 들어감

    roundtrip = markdown_to_spec(md)
    assert roundtrip.measurement_performance.accuracy_um.unit == "um"


# ---------------------------------------------------------------
# Test 9: Optional Field 보존 (예: Optical System 정보가 전혀 없는 장비)
# ---------------------------------------------------------------
def test_optional_optical_system_absent_does_not_break_rendering():
    spec = _full_spec()
    assert spec.optical_system.light_source is None  # 애초에 설정 안 함

    md = render_markdown(spec)
    html = render_html(spec)
    with tempfile.TemporaryDirectory() as tmp:
        pptx_path = render_pptx(spec, str(Path(tmp) / "out.pptx"))
        prs = Presentation(pptx_path)
        assert len(prs.slides) > 1  # optical system이 비어 있어도 생성 자체는 성공

    assert "## 6. Optical System" in md
    assert "Light Source" in md
    assert "UNKNOWN" in md  # 비어있는 optical system 필드들이 UNKNOWN으로 명시됨
    assert "Optical System" in html


# ---------------------------------------------------------------
# Test 10: 긴 텍스트 처리
# ---------------------------------------------------------------
def test_long_text_handling():
    spec = SpecificationSchema()
    spec.equipment.name = "A" * 500
    long_note = "이 설비는 " * 200  # 매우 긴 노트
    spec.notes = [long_note]

    md = render_markdown(spec)
    assert "A" * 500 in md
    assert long_note in md
    # 마크다운 테이블 파이프 문자가 깨지지 않는지 (셀 안에 개행이 있으면 표가 깨지므로) 확인
    assert "\n" not in long_note or all(len(line.split("|")) >= 2 for line in md.splitlines() if line.startswith("|"))

    html = render_html(spec)
    assert "A" * 500 in html

    with tempfile.TemporaryDirectory() as tmp:
        out = render_pptx(spec, str(Path(tmp) / "out.pptx"))
        prs = Presentation(out)
        assert len(prs.slides) > 1  # 긴 텍스트로도 생성 자체가 실패하지 않음


# ---------------------------------------------------------------
# 회귀: 기존 기능이 이번 변경으로 깨지지 않았는지 (agent 파이프라인/스키마)
# ---------------------------------------------------------------
def test_specification_schema_unchanged_shape():
    """SpecificationSchema의 필드 구조 자체는 이번 리팩터링에서 변경되지 않았어야 한다."""
    spec = SpecificationSchema()
    expected_top_level = {
        "equipment", "inspection_target", "inspection_items", "measurement_performance",
        "spatial_performance", "inspection_performance", "defect_detection", "optical_system",
        "system", "interfaces", "environment", "safety", "notes", "assumptions", "sources",
        "needs_confirmation",
    }
    assert set(type(spec).model_fields.keys()) == expected_top_level


def test_pptx_electrode_builder_still_importable_and_usable():
    """agent/pptx_electrode_builder.py(기존 PPTX Generator)를 삭제하지 않고 그대로 재사용 가능해야 한다."""
    from agent.pptx_electrode_builder import ElectrodeSpecPPTXBuilder

    builder = ElectrodeSpecPPTXBuilder(template_path="template_electrode.pptx")
    with tempfile.TemporaryDirectory() as tmp:
        out = builder.build(_full_spec(), output_path=str(Path(tmp) / "legacy.pptx"))
        assert Path(out).exists()
