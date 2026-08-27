"""
회귀 테스트: "마크다운 사양서 생성" 버튼을 클릭해도 아무 동작을 하지 않던 문제.

원인: 프론트엔드(main.py)는 버튼을 누르면 /api/agent/build-markdown을 호출하도록
이미 배선돼 있었지만, 그 라우트는 SpecificationSchema(LLM이 채운 사양서) 기반
Markdown만 생성할 수 있었다. 사용자가 요청한 형식(Equipment Name/Manufacturer/
Model/Equipment Type/... 같은 CandidateEquipment 필드 기반의 간단한 사양서)과
맞지 않아 별도 경로(/api/agent/build-candidate-markdown, renderers.markdown_
renderer.render_candidate_markdown)를 새로 만들고 버튼을 그쪽으로 연결했다.

이 테스트는:
1. render_candidate_markdown()이 요청서 예시 형식(General/Inspection Performance/
   Inspection Items/Defect Inspection/Sources)을 그대로 만드는지
2. 근거 없는 필드는 UNKNOWN으로 정직하게 남기는지(추측해서 채우지 않는지)
3. /api/agent/build-candidate-markdown이 실제로 파일을 만들고 다운로드까지
   되는지(엔드투엔드)
를 검증한다.
"""
from fastapi.testclient import TestClient

import main
from agent.schemas import CandidateEquipment, CandidateEquipmentFact, RequirementSchema
from renderers.markdown_renderer import render_candidate_markdown


def _client():
    return TestClient(main.app)


def _full_candidate() -> CandidateEquipment:
    return CandidateEquipment(
        candidate_id="cand-1",
        manufacturer="MultiSense",
        model="MS-600",
        source_document="SPEC-010.md",
        equipment_fact=CandidateEquipmentFact(
            equipment_type="Multi-Modal Electrode Inspection System",
            measurement_principle="3D Laser + Vision",
            inline_offline="inline",
            measurement_method="non_contact",
            width_mm=800.0,
            range_min=0.0,
            range_max=300.0,
            range_unit="um",
            accuracy_value=0.8,
            accuracy_unit="um",
            resolution_value=0.2,
            resolution_unit="um",
            speed_value=500.0,
            speed_unit="mm/s",
            defect_types=["Scratch", "Crack", "Particle", "Coating Defect"],
            min_defect_size_value=15.0,
            min_defect_size_unit="um",
        ),
    )


def test_render_candidate_markdown_matches_requested_format():
    candidate = _full_candidate()
    requirement = RequirementSchema(inspection_items=["thickness", "surface_defect"])

    md = render_candidate_markdown(candidate, requirement=requirement)

    assert md.startswith("# Equipment Specification\n")
    assert "## General" in md
    assert "- Equipment Name: MultiSense MS-600" in md
    assert "- Manufacturer: MultiSense" in md
    assert "- Model: MS-600" in md
    assert "- Equipment Type: Multi-Modal Electrode Inspection System" in md
    assert "- Measurement Principle: 3D Laser + Vision" in md
    assert "- Inspection Mode: inline" in md
    assert "- Measurement Type: non_contact" in md

    assert "## Inspection Performance" in md
    assert "| Maximum Electrode Width | 800.0 mm |" in md
    assert "| Measurement Range | 0.0 ~ 300.0 um |" in md
    assert "| Accuracy | ±0.8 um |" in md
    assert "| Resolution | 0.2 um |" in md
    assert "| Measurement Speed | 500.0 mm/s |" in md

    assert "## Inspection Items" in md
    assert "- Thickness" in md
    assert "- Surface Defect" in md

    assert "## Defect Inspection" in md
    assert "| Minimum Detectable Defect | 15.0 um |" in md
    assert "| Defect Types | Scratch, Crack, Particle, Coating Defect |" in md

    assert "## Sources" in md
    assert "- SPEC-010.md" in md


def test_render_candidate_markdown_leaves_missing_fields_as_unknown():
    """근거 없는 값을 지어내지 않는다 — 최소 정보만 있는 후보도 안전하게 렌더링된다."""
    candidate = CandidateEquipment(candidate_id="cand-1", source_document="SPEC-999.md")
    md = render_candidate_markdown(candidate, requirement=None)

    assert "- Manufacturer: UNKNOWN" in md
    assert "- Equipment Type: UNKNOWN" in md
    assert "| Maximum Electrode Width | UNKNOWN |" in md
    assert "| Measurement Range | UNKNOWN |" in md
    assert "| Defect Types | UNKNOWN |" in md
    assert "- SPEC-999.md" in md


def test_build_candidate_markdown_route_returns_file_and_downloads():
    client = _client()
    candidate = _full_candidate()
    resp = client.post(
        "/api/agent/build-candidate-markdown",
        json={"candidate": candidate.model_dump(), "requirement": {"inspection_items": ["thickness"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["file_name"].endswith(".md")
    assert data["download_url"] == f"/api/download/{data['file_name']}"

    download = client.get(data["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    body = download.text
    assert "MultiSense MS-600" in body
    assert "SPEC-010.md" in body


def test_build_candidate_markdown_route_works_without_requirement():
    """requirement를 안 보내도(선택 인자) 에러 없이 생성돼야 한다."""
    client = _client()
    candidate = CandidateEquipment(candidate_id="cand-1", manufacturer="X", model="Y", source_document="SPEC-001.md")
    resp = client.post("/api/agent/build-candidate-markdown", json={"candidate": candidate.model_dump()})
    assert resp.status_code == 200
