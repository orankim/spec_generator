"""
회귀 테스트: 사용자 화면에서 "사양서 제작하기"/"사양서 업로드하기"가 제거되고
"전극 검사기 AI"만 남아 있는지 확인한다. FastAPI TestClient로 실제 라우트를
호출해서 검증한다 (문자열 grep이 아니라 실제 HTTP 응답 기준).
"""
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def test_root_redirects_to_agent(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/agent"


def test_agent_page_serves_and_shows_only_electrode_ai(client):
    resp = client.get("/agent")
    assert resp.status_code == 200
    body = resp.text
    assert "전극 검사기 AI" in body
    assert "사양서 제작하기" not in body
    assert "사양서 업로드하기" not in body


def test_legacy_generate_page_removed(client):
    assert client.get("/", follow_redirects=True).url.path == "/agent"
    # 예전 "/" 페이지 자체(사양서 제작하기 폼)는 더 이상 어떤 경로로도 서빙되지 않는다.
    resp = client.get("/agent")
    assert "promptInput" not in resp.text  # 예전 자연어 PPTX 생성 폼의 input id


def test_upload_page_removed(client):
    resp = client.get("/upload")
    assert resp.status_code == 404


def test_legacy_generate_spec_api_removed(client):
    resp = client.post("/api/generate-spec", json={"prompt": "test"})
    assert resp.status_code == 404


def test_legacy_upload_specs_api_removed(client):
    resp = client.post("/api/upload-specs", files={"files": ("x.pptx", b"fake", "application/octet-stream")})
    assert resp.status_code == 404


def test_download_endpoint_still_exists_for_agent_pptx(client):
    """agent/routes.py의 build-pptx가 쓰는 다운로드 엔드포인트는 반드시 유지되어야 한다."""
    resp = client.get("/api/download/does_not_exist.pptx")
    assert resp.status_code == 404  # 라우트는 존재하되, 파일이 없어서 404 (405/501이 아님)


def test_agent_api_routes_untouched(client):
    resp = client.post("/api/agent/analyze-requirement", json={})
    assert resp.status_code == 400  # user_text/selection 둘 다 없어서 400 — 라우트 자체는 살아있음
    assert resp.status_code != 404
