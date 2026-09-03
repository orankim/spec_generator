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
    """
    "마크다운 사양서 생성" 버튼은 이제 /api/agent/build-markdown(LLM이 채운
    SpecificationSchema 기반)이 아니라 /api/agent/build-candidate-markdown(RAG로
    찾은 CandidateEquipment 원본 사양 기반, LLM을 거치지 않음)을 호출한다 — 버튼
    클릭 시 아무 동작도 하지 않던 문제를 고치면서 함께 정리했다. build-markdown
    라우트 자체는 하위 호환을 위해 그대로 남겨뒀다(위 다른 테스트들이 계속 검증).
    """
    client = _client()
    body = client.get("/agent").text
    assert "마크다운 사양서" in body
    assert "PPTX 사양서" not in body
    assert "/api/agent/build-candidate-markdown" in body
