"""
Phase 9 -> 후속 개선(견적 통합) — POST /api/agent/generate-spec 응답의
quote_analyses가 "질문에 견적 키워드가 있었는가"가 아니라 "추천 후보에 실제로
연결된 QUOTE 데이터가 있는가"만으로 채워지는지 확인한다(agent.routes.
generate_spec_api). 예전에는 quote_intent.wants_quote_analysis(raw_text)로
게이팅해 "장비 찾아줘"처럼 견적 키워드가 없는 일반 질문에서는 연결된 QUOTE가
있어도 화면에 전혀 나타나지 않는 버그가 있었다 — 이 파일은 그 버그의 회귀
테스트다. Ollama 없이 결정론적으로 검증하기 위해 tests/regression_lib.py의
fake-embedding/empty-LLM 패턴을 그대로 재사용한다.
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


def test_spec_only_intent_still_populates_quote_analyses_when_linked_quote_exists(client):
    """회귀 테스트: 견적 키워드가 전혀 없는 일반 장비 검색 질문이라도, 추천 후보에
    실제로 연결된 QUOTE 데이터가 있으면 quote_analyses가 채워져야 한다 — 예전에는
    quote_intent 키워드가 없다는 이유만으로 이 값이 통째로 비어 있었다."""
    resp = _post_generate_spec(
        client,
        {
            "raw_text": "두께를 검사할 수 있는 장비를 찾아줘.",
            "inspection_items": ["thickness"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["quote_analyses"], "견적 키워드가 없다는 이유로 연결된 견적 데이터가 생략되었습니다"
    chosen = data["chosen_candidate"]
    assert chosen is not None
    assert chosen["source_document"] in data["quote_analyses"], (
        "추천된(chosen_candidate) 장비 자신의 견적이 응답에 연결되어 있지 않습니다"
    )
    analyses = data["quote_analyses"][chosen["source_document"]]
    assert analyses[0]["computed_grand_total"] is not None


def test_missing_raw_text_does_not_crash(client):
    """조건 선택 UI 등 raw_text가 없는 요청 경로도 안전해야 한다(예외 없이 dict 응답).
    quote_analyses는 이제 raw_text의 키워드가 아니라 실제 연결된 QUOTE 데이터
    유무로만 결정되므로, raw_text가 없다고 해서 비어 있어야 한다고 가정하지 않는다."""
    resp = _post_generate_spec(client, {"inspection_items": ["thickness"]})
    assert resp.status_code == 200
    assert isinstance(resp.json()["quote_analyses"], dict)
