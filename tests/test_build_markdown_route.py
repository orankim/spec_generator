"""
회귀/신규 기능 테스트: 사양서 최종 산출물을 PPTX가 아니라 Markdown으로 생성하도록
변경한 것을 검증한다.

배경: 기존에는 agent/routes.py의 "/api/agent/build-pptx"가 ElectrodeSpecPPTXBuilder로
PPTX 파일을 만들었다. 이미 renderers/markdown_renderer.py에 구현되어 있던(CLI
`render-md` 서브커맨드로만 쓰이던) render_markdown()을 재사용해 "/api/agent/
build-markdown"으로 대체했다 — 새 렌더러를 만들지 않고 기존 표준 Markdown 포맷
(docs/SPECIFICATION_MARKDOWN_FORMAT.md)을 그대로 재사용한다.
"""
from fastapi.testclient import TestClient

import main
from agent.pptx_electrode_builder import ElectrodeSpecPPTXBuilder  # noqa: F401  (기존 모듈은 삭제하지 않았음을 명시)

_SAMPLE_SPEC = {
    "equipment": {"name": "OptiScan ES-200", "manufacturer": "OptiScan", "model": "ES-200"},
    "inspection_target": {"material": "음극", "width_mm": 5.0},
    "measurement_performance": {
        "measurement_range_full": {"min": 0.0, "max": 200.0, "unit": "um", "status": "VERIFIED"},
        "equipment_accuracy_um": {"value": 1.0, "unit": "um", "status": "VERIFIED"},
    },
}


def _client():
    return TestClient(main.app)


def test_build_markdown_route_returns_md_file_and_download_url():
    client = _client()
    resp = client.post("/api/agent/build-markdown", json={"specification": _SAMPLE_SPEC})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["file_name"].endswith(".md")
    assert data["download_url"] == f"/api/download/{data['file_name']}"


def test_build_markdown_route_is_now_used_instead_of_pptx():
    """"/api/agent/build-pptx"는 더 이상 존재하지 않아야 한다(완전히 대체됨)."""
    client = _client()
    resp = client.post("/api/agent/build-pptx", json={"specification": _SAMPLE_SPEC})
    assert resp.status_code == 404


def test_downloaded_markdown_file_has_correct_content_and_media_type():
    client = _client()
    build_resp = client.post("/api/agent/build-markdown", json={"specification": _SAMPLE_SPEC})
    download_url = build_resp.json()["download_url"]

    resp = client.get(download_url)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    body = resp.text
    assert "OptiScan ES-200" in body
    assert "# " in body  # 마크다운 제목
    assert "|" in body  # 표 형식 유지


def test_build_markdown_with_requirement_includes_compliance_table():
    """requirement를 함께 보내면 Hard Requirement/Compliance 비교 표까지 포함되어야 한다."""
    client = _client()
    requirement = {
        "measurement_range": {"min": 0.0, "max": 200.0, "unit": "um"},
        "accuracy": {"value": 1.0, "unit": "um", "operator": "<="},
        "required_accuracy_um": 1.0,
    }
    resp = client.post(
        "/api/agent/build-markdown",
        json={"specification": _SAMPLE_SPEC, "requirement": requirement},
    )
    assert resp.status_code == 200
    download_url = resp.json()["download_url"]
    body = client.get(download_url).text
    assert "Compliance" in body or "compliance" in body.lower()


def test_agent_page_offers_markdown_download_not_pptx():
    client = _client()
    body = client.get("/agent").text
    assert "마크다운 사양서" in body
    assert "PPTX 사양서" not in body
    assert "/api/agent/build-markdown" in body
