"""
회귀 테스트: 사양서 생성 단계가 Ollama read timeout(180초)으로 실패하던 문제.

실제 원인(코드로 확인, 추측 아님): agent/spec_generator.py::generate_specification()이
candidate_matcher가 이미 "이 후보 하나"로 판정을 끝낸 뒤에도, retrieved_docs
전체(실측: 다중 검사항목 질의에서 10개 사양서 중 25개 chunk)를 그대로 LLM
프롬프트에 실어 보내고 있었다 — 정작 최종 사양서를 채워야 할 장비는 그 중
"선택된 후보 문서" 하나뿐인데도 관련 없는 문서까지 매번 함께 보내 프롬프트/
응답 시간을 불필요하게 늘렸다.

이 파일은 실제 Ollama 서버 없이(requests.post를 모킹) 다음을 검증한다:
- TEST 1: 정상 응답 → 성공
- TEST 2: 응답이 timeout보다 짧게 걸림 → 성공
- TEST 3: requests.exceptions.ReadTimeout → 재시도 후에도 실패하면 서버가
  500으로 죽지 않고 agent.ollama_client.OllamaError로 명확히 처리됨
  (agent/routes.py가 이를 502로 변환하는 것은 기존에 이미 구현되어 있었다)
- TEST 4: requests.exceptions.ConnectionError → 동일하게 명확히 처리됨
- TEST 5: 검색 chunk가 과도하게 많아도(25개) 실제 LLM 프롬프트에는 선택된
  후보 문서의 chunk만 전달됨(context 좁힘 적용 확인)
- TEST 6: [LLM DEBUG] 로그에 model/prompt_chars/context_chunks/timeout 등이
  실제로 기록되는지 확인
"""
import logging
import shutil
import time
import unittest.mock as mock

import pytest
import requests
from langchain_core.documents import Document
from pydantic import BaseModel

from agent import ollama_client
from agent.schemas import RequirementRange, RequirementSchema, SpecificationSchema
from agent.spec_generator import generate_specification


class _DummySchema(BaseModel):
    value: int = 0


def _fake_response(json_body):
    resp = mock.Mock()
    resp.raise_for_status = mock.Mock()
    resp.json = mock.Mock(return_value=json_body)
    return resp


# =================================================================
# TEST 1 — 정상 응답
# =================================================================
def test_1_normal_response_succeeds():
    ok_resp = _fake_response({"response": '{"value": 42}'})
    with mock.patch("agent.ollama_client.requests.post", return_value=ok_resp) as post:
        result = ollama_client.parse_structured("prompt", _DummySchema, timeout=30)
    assert result.value == 42
    assert post.call_count == 1


# =================================================================
# TEST 2 — 응답이 timeout보다 짧게 걸림
# =================================================================
def test_2_response_faster_than_timeout_succeeds():
    def _slow_but_ok(*args, **kwargs):
        time.sleep(0.01)  # timeout(30s)보다 훨씬 짧음
        return _fake_response({"response": '{"value": 7}'})

    with mock.patch("agent.ollama_client.requests.post", side_effect=_slow_but_ok):
        result = ollama_client.parse_structured("prompt", _DummySchema, timeout=30)
    assert result.value == 7


# =================================================================
# TEST 3 — ReadTimeout → 서버가 500으로 죽지 않고 OllamaError로 명확히 처리
# =================================================================
def test_3_read_timeout_raises_ollama_error_not_crash(caplog):
    with mock.patch(
        "agent.ollama_client.requests.post",
        side_effect=requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)"),
    ), mock.patch("agent.ollama_client.time.sleep"):  # 재시도 대기를 실제로 기다리지 않는다
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ollama_client.OllamaError) as exc_info:
                ollama_client.parse_structured("prompt", _DummySchema, timeout=180)
    assert "timeout" in str(exc_info.value).lower() or "180" in str(exc_info.value)
    assert any("[LLM TIMEOUT]" in r.message for r in caplog.records)


def test_3b_read_timeout_retries_once_then_succeeds():
    """1회 재시도(총 2회 시도) 안에 성공하면 최종적으로는 정상 반환되어야 한다."""
    call_count = {"n": 0}

    def _fail_once_then_succeed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise requests.exceptions.ReadTimeout("Read timed out.")
        return _fake_response({"response": '{"value": 99}'})

    with mock.patch("agent.ollama_client.requests.post", side_effect=_fail_once_then_succeed), \
         mock.patch("agent.ollama_client.time.sleep"):
        result = ollama_client.parse_structured("prompt", _DummySchema, timeout=30)
    assert result.value == 99
    assert call_count["n"] == 2


def test_3c_retry_is_bounded_not_infinite():
    """재시도가 무한 반복되지 않고 정해진 횟수(기본 1회 재시도 = 총 2회) 안에서 멈춰야 한다."""
    call_count = {"n": 0}

    def _always_timeout(*args, **kwargs):
        call_count["n"] += 1
        raise requests.exceptions.ReadTimeout("Read timed out.")

    with mock.patch("agent.ollama_client.requests.post", side_effect=_always_timeout), \
         mock.patch("agent.ollama_client.time.sleep"):
        with pytest.raises(ollama_client.OllamaError):
            ollama_client.parse_structured("prompt", _DummySchema, timeout=30)
    assert call_count["n"] == ollama_client._MAX_RETRIES + 1  # 정확히 상한만큼만 시도


# =================================================================
# TEST 4 — ConnectionError → 명확한 오류 처리
# =================================================================
def test_4_connection_error_raises_ollama_error():
    with mock.patch(
        "agent.ollama_client.requests.post",
        side_effect=requests.exceptions.ConnectionError("Connection refused"),
    ), mock.patch("agent.ollama_client.time.sleep"):
        with pytest.raises(ollama_client.OllamaError):
            ollama_client.parse_structured("prompt", _DummySchema, timeout=30)


def test_4b_analyze_and_generate_endpoints_return_502_not_500_on_ollama_error():
    """agent/routes.py가 OllamaError를 502로 변환하는지(500으로 죽지 않는지) 실제 HTTP 레벨로 확인."""
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    with mock.patch(
        "agent.requirement_parser.ollama_client.parse_structured",
        side_effect=ollama_client.OllamaError("Ollama 서버 호출 실패: Read timed out."),
    ):
        resp = client.post("/api/agent/analyze-requirement", json={"user_text": "전극 검사기를 찾아줘."})
    assert resp.status_code == 502
    assert "Ollama" in resp.json()["detail"]


# =================================================================
# TEST 5 — 검색 chunk가 과도하게 많아도 LLM에는 선택된 후보 문서만 전달
# =================================================================
def test_5_llm_context_narrowed_to_chosen_candidate_only():
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
    )
    # 서로 다른 5개 문서에서 25개 chunk가 검색되었다고 가정(실측 재현) — 그 중
    # SPEC-001만 요구 범위를 충족하는 유일한 후보라고 하자.
    docs = []
    for spec_id, (lo, hi) in enumerate(
        [(0, 200), (0, 50), (0, 30), (0, 10), (0, 5)], start=1
    ):
        name = f"SPEC-{spec_id:03d}.md"
        for chunk_i in range(5):  # 문서당 5개 chunk = 총 25개
            content = (
                f"## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
                f"| Measurement Range | {lo} ~ {hi} μm |\n"
                if chunk_i == 0
                else f"## Section {chunk_i}\n\n- 상세 설명 {chunk_i} (문서 {name})\n"
            )
            docs.append(Document(page_content=content, metadata={"filename": name, "source": name, "source_type": "markdown", "chunk_id": chunk_i}))

    assert len(docs) == 25

    captured = {}

    def _capture(prompt, model_cls, **kwargs):
        captured["prompt"] = prompt
        captured["context_chunk_count"] = kwargs.get("context_chunk_count")
        return SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", side_effect=_capture):
        generate_specification(requirement, docs, context_text="(사용되지 않음 — 아래에서 확인)")

    # SPEC-001(0~200, 요구 범위를 정확히 충족하는 유일한 후보)의 chunk 5개만 프롬프트에 실려야 한다.
    assert captured["context_chunk_count"] == 5
    assert "SPEC-002" not in captured["prompt"]
    assert "SPEC-003" not in captured["prompt"]
    assert "SPEC-001" in captured["prompt"]


def test_5b_no_candidate_falls_back_to_full_context():
    """검색 결과가 아예 없으면(회귀 방지) 기존과 동일하게 빈 컨텍스트로 정상 동작해야 한다."""
    requirement = RequirementSchema()
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=SpecificationSchema()) as m:
        spec = generate_specification(requirement, [], context_text="")
    assert spec is not None
    assert m.call_args.kwargs["context_chunk_count"] == 0


# =================================================================
# TEST 6 — [LLM DEBUG] 로그에 prompt 크기 등이 기록되는지 확인
# =================================================================
def test_6_debug_log_reports_prompt_size_and_config(caplog):
    ok_resp = _fake_response({"response": '{"value": 1}'})
    with mock.patch("agent.ollama_client.requests.post", return_value=ok_resp):
        with caplog.at_level(logging.INFO):
            ollama_client.parse_structured(
                "x" * 500, _DummySchema, model="test-model", host="http://localhost:11434",
                timeout=30, context_chunk_count=7,
            )
    debug_lines = [r.message for r in caplog.records if "[LLM DEBUG]" in r.message and "request_duration" not in r.message]
    assert debug_lines, "요청 시작 시점의 [LLM DEBUG] 로그가 없습니다"
    line = debug_lines[0]
    assert "model=test-model" in line
    assert "prompt_chars=500" in line
    assert "context_chunks=7" in line
    assert "timeout=30" in line
    duration_lines = [r.message for r in caplog.records if "request_duration" in r.message]
    assert duration_lines, "요청 완료 시점의 request_duration 로그가 없습니다"


def test_timeout_is_configurable_via_env_var():
    with mock.patch.dict("os.environ", {"OLLAMA_TIMEOUT": "45"}):
        assert ollama_client._default_timeout() == 45


def test_timeout_defaults_to_180_when_unset():
    with mock.patch.dict("os.environ", {}, clear=False):
        import os as _os
        _os.environ.pop("OLLAMA_TIMEOUT", None)
        assert ollama_client._default_timeout() == 180
