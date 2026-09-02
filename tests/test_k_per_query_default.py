"""
k_per_query Production Default(10 -> 15) 변경 검증. 전부 Mock 기반 — 실제
Ollama 호출 없이(네트워크 연결 시도조차 없이) 결정론적으로 실행된다.

agent/pipeline.py::retrieve_and_generate()와 agent/spec_retriever.py::
retrieve_for_requirement() 자체는 재구현하지 않는다 — SimpleChromaStore와
generate_specification만 얇게 stub해 "실제로 어떤 k 값이 전달되는지"만 관찰한다.
"""
from __future__ import annotations

import inspect

import pytest

from agent import pipeline, spec_retriever
from agent.schemas import RequirementSchema, SpecificationSchema


class _RecordingVectorStore:
    """SimpleChromaStore 대체 — similarity_search_with_score에 전달된 k만 기록하고
    검색 자체는 항상 빈 결과를 반환한다(임베딩 호출도, 실제 DB 접근도 없음)."""

    last_k_values = []

    def __init__(self, *args, **kwargs):
        pass

    def similarity_search_with_score(self, query, k):
        _RecordingVectorStore.last_k_values.append(k)
        return []


@pytest.fixture(autouse=True)
def _reset_recorder():
    _RecordingVectorStore.last_k_values = []
    yield


@pytest.fixture
def patched_vector_store(monkeypatch):
    monkeypatch.setattr(spec_retriever, "SimpleChromaStore", _RecordingVectorStore)
    return _RecordingVectorStore


def _minimal_requirement() -> RequirementSchema:
    return RequirementSchema(raw_text="두께를 측정할 수 있는 장비를 찾아줘.")


# ---------------------------------------------------------------------------
# 5-3 / Backward Compatibility (5-4): retrieve_for_requirement() 자체의 기본값/오버라이드
# ---------------------------------------------------------------------------


def test_retriever_default_is_15(patched_vector_store):
    spec_retriever.retrieve_for_requirement(_minimal_requirement(), db_path="unused")
    assert patched_vector_store.last_k_values, "similarity_search_with_score가 호출되지 않았습니다"
    assert all(k == 15 for k in patched_vector_store.last_k_values)


@pytest.mark.parametrize("explicit_k", [5, 10, 20])
def test_retriever_explicit_override_is_preserved(patched_vector_store, explicit_k):
    spec_retriever.retrieve_for_requirement(_minimal_requirement(), db_path="unused", k_per_query=explicit_k)
    assert all(k == explicit_k for k in patched_vector_store.last_k_values)


# ---------------------------------------------------------------------------
# 5-1 / Propagation Invariant: Pipeline default(15) -> Retriever까지 그대로 전달
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_pipeline(monkeypatch):
    """retrieve_and_generate()가 실제 LLM(generate_specification)까지 타지 않도록
    그 부분만 얇게 stub한다 — retrieve_for_requirement 호출 자체는 실제 함수를
    그대로 쓰고, 그 안의 vector store만 _RecordingVectorStore로 대체한다."""
    monkeypatch.setattr(spec_retriever, "SimpleChromaStore", _RecordingVectorStore)
    monkeypatch.setattr(pipeline, "generate_specification", lambda *a, **kw: SpecificationSchema())
    return _RecordingVectorStore


def test_pipeline_default_propagates_15_to_retriever(patched_pipeline):
    pipeline.retrieve_and_generate(_minimal_requirement(), db_path="unused")
    assert patched_pipeline.last_k_values, "retrieve_for_requirement가 호출되지 않았습니다"
    assert all(k == 15 for k in patched_pipeline.last_k_values), (
        f"Pipeline 기본 호출에서 Retriever까지 전달된 k 값이 15가 아닙니다: {patched_pipeline.last_k_values}"
    )


def test_pipeline_explicit_override_not_overwritten_by_default(patched_pipeline):
    """Production Default를 15로 올린 것이 명시적 k_per_query=5 호출을 무시하면 안 된다."""
    pipeline.retrieve_and_generate(_minimal_requirement(), db_path="unused", k_per_query=5)
    assert all(k == 5 for k in patched_pipeline.last_k_values), (
        f"Explicit override(k_per_query=5)가 Production Default(15)에 의해 덮어써졌습니다: {patched_pipeline.last_k_values}"
    )


@pytest.mark.parametrize("explicit_k", [5, 10, 20])
def test_pipeline_backward_compatibility_various_k(patched_pipeline, explicit_k):
    pipeline.retrieve_and_generate(_minimal_requirement(), db_path="unused", k_per_query=explicit_k)
    assert all(k == explicit_k for k in patched_pipeline.last_k_values)


# ---------------------------------------------------------------------------
# Default Invariant / Signature 자체(정적 검증, 회귀 가드로 이중 확인)
# ---------------------------------------------------------------------------


def test_signature_defaults_are_exactly_15():
    assert inspect.signature(spec_retriever.retrieve_for_requirement).parameters["k_per_query"].default == 15
    assert inspect.signature(pipeline.retrieve_and_generate).parameters["k_per_query"].default == 15
