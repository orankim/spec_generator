"""
Phase 9 — POST /api/agent/generate-spec 응답에 quote_analyses가 올바른 조건에서만
채워지는지 확인한다(agent.routes.generate_spec_api). Ollama 없이 결정론적으로
검증하기 위해 tests/regression_lib.py의 fake-embedding/empty-LLM 패턴을 그대로
재사용한다.
"""
from __future__ import annotations

import shutil
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient

import main
from agent.schemas import SpecificationSchema

from .regression_lib import build_fake_embedding_db, patched_embeddings

TEST_DB_PATH = "./_test_chroma_db_generate_spec_quote_route"


@pytest.fixture(scope="module", autouse=True)
def indexed_db():
    with patched_embeddings():
        build_fake_embedding_db(TEST_DB_PATH)
    yield
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("agent.routes.DB_PATH", TEST_DB_PATH)
    return TestClient(main.app)


def _post_generate_spec(client, requirement_dict):
    with patched_embeddings(), mock.patch(
        "agent.spec_generator.ollama_client.parse_structured", return_value=SpecificationSchema()
    ):
        return client.post("/api/agent/generate-spec", json={"requirement": requirement_dict})


def test_quote_intent_populates_quote_analyses(client):
    resp = _post_generate_spec(
        client,
        {
            "raw_text": "두께를 검사할 수 있는 장비 중 견적을 비교해줘.",
            "inspection_items": ["thickness"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quote_analyses"], "견적 의도가 있는 질문인데 quote_analyses가 비었습니다"


def test_spec_only_intent_leaves_quote_analyses_empty(client):
    resp = _post_generate_spec(
        client,
        {
            "raw_text": "두께를 검사할 수 있는 장비를 찾아줘.",
            "inspection_items": ["thickness"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quote_analyses"] == {}, "사양만 물었는데 견적 분석이 채워졌습니다"


def test_missing_raw_text_does_not_crash_and_skips_quote_analysis(client):
    """조건 선택 UI 등 raw_text가 없는 요청 경로도 안전해야 한다(예외 없이 빈 결과)."""
    resp = _post_generate_spec(client, {"inspection_items": ["thickness"]})
    assert resp.status_code == 200
    assert resp.json()["quote_analyses"] == {}
