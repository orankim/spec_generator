"""
Ollama 네이티브 구조화 출력(Structured Output) 클라이언트.

langchain_community.llms.Ollama의 `format` 필드는 문자열만 받을 수 있어
"json" 모드(아무 JSON이나 허용)까지만 강제할 수 있고, 필드 이름/타입까지
강제하는 JSON Schema 기반 구조화 출력은 지원하지 않는다. Ollama 서버 자체는
`/api/generate`의 `format`에 JSON Schema 객체를 그대로 전달하면 그 스키마를
만족하는 JSON만 생성하도록 강제하는 기능을 제공하므로, 이 모듈은 그 REST API를
직접 호출한다.

모델/서버 주소는 환경변수로 설정한다 (OLLAMA_HOST, OLLAMA_MODEL).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Type, TypeVar

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _default_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _default_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")


def _default_timeout() -> int:
    """
    read timeout(초). 과거에는 generate_structured()의 기본 인자값(180)으로만
    하드코딩되어 있어 서버 재시작 없이 조정할 방법이 없었다 — OLLAMA_TIMEOUT
    환경변수로 오버라이드 가능하게 한다(.env.example에 문서화). 값이 없거나
    잘못된 값이면 기존 기본값 180을 그대로 쓴다(하위호환).
    """
    raw = os.environ.get("OLLAMA_TIMEOUT")
    if not raw:
        return 180
    try:
        return int(raw)
    except ValueError:
        logger.warning("OLLAMA_TIMEOUT=%r 가 정수가 아니어서 무시하고 기본값 180을 사용합니다.", raw)
        return 180


# read timeout(연결 문제가 아니라 순수 응답 대기 시간)에서만 재시도한다 — 재시도로
# 해결되지 않는 오류(JSON 스키마 불일치, 400 등)까지 반복 호출하면 같은 요청이
# "무한 반복"되는 것과 다를 바 없어진다(요청서 5절: "retry 시 동일 요청이 무한
# 반복되지 않도록 방지"). 기본 1회 재시도(총 2회 시도)로 상한을 둔다.
_MAX_RETRIES = 1
_RETRY_DELAY_SECONDS = 2.0
_RETRYABLE_EXCEPTIONS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


class OllamaError(RuntimeError):
    """Ollama 서버 호출 또는 응답 파싱 실패."""


def generate_structured(
    prompt: str,
    schema: Dict[str, Any],
    model: Optional[str] = None,
    host: Optional[str] = None,
    temperature: float = 0.1,
    num_ctx: int = 8192,
    num_predict: int = 2048,
    timeout: Optional[int] = None,
    context_chunk_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    주어진 JSON Schema를 만족하는 JSON을 Ollama로부터 강제로 받아온다.

    context_chunk_count는 호출부(RequirementParser/SpecificationGenerator)가
    프롬프트에 실제로 얼마나 많은 RAG chunk를 실어 보냈는지 로그에 남기기
    위한 선택적 인자다(생성 자체에는 관여하지 않음) — timeout 원인 분석 시
    "chunk가 너무 많아서 느린가"를 prompt 크기와 함께 바로 확인할 수 있게 한다.
    """
    model = model or _default_model()
    host = host or _default_host()
    timeout = timeout if timeout is not None else _default_timeout()
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    prompt_chars = len(prompt)

    attempt = 0
    while True:
        attempt += 1
        request_start = time.monotonic()
        logger.info(
            "[LLM DEBUG] model=%s host=%s timeout=%s prompt_chars=%s context_chunks=%s "
            "num_predict=%s num_ctx=%s attempt=%s/%s request_start=%s",
            model, host, timeout, prompt_chars, context_chunk_count,
            num_predict, num_ctx, attempt, _MAX_RETRIES + 1, request_start,
        )
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            elapsed = time.monotonic() - request_start
            logger.info("[LLM DEBUG] request_duration=%.2f seconds (attempt=%s)", elapsed, attempt)
            resp.raise_for_status()
            break
        except _RETRYABLE_EXCEPTIONS as e:
            elapsed = time.monotonic() - request_start
            logger.warning(
                "[LLM TIMEOUT] model=%s prompt_chars=%s context_chunks=%s timeout=%s elapsed=%.2f attempt=%s/%s error=%s",
                model, prompt_chars, context_chunk_count, timeout, elapsed, attempt, _MAX_RETRIES + 1, e,
            )
            if attempt > _MAX_RETRIES:
                raise OllamaError(
                    f"Ollama 서버 호출 실패 ({url}): {e} "
                    f"(model={model}, prompt_chars={prompt_chars}, context_chunks={context_chunk_count}, "
                    f"timeout={timeout}s, {attempt}회 시도 후 포기)"
                ) from e
            time.sleep(_RETRY_DELAY_SECONDS)
            continue
        except requests.exceptions.RequestException as e:
            raise OllamaError(f"Ollama 서버 호출 실패 ({url}): {e}") from e

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama 응답이 JSON이 아님: {e}\n원문: {resp.text[:500]}") from e

    raw_text = data.get("response", "")
    if not raw_text:
        raise OllamaError(f"Ollama 응답에 'response' 필드가 없음: {data}")

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama가 스키마를 만족하는 JSON을 반환하지 않음: {e}\n원문: {raw_text[:500]}") from e


def parse_structured(prompt: str, model_cls: Type[T], **kwargs) -> T:
    """
    generate_structured의 결과를 바로 Pydantic 모델로 검증/변환한다.
    """
    schema = model_cls.model_json_schema()
    data = generate_structured(prompt, schema, **kwargs)
    return model_cls(**data)


def check_ollama_available(host: Optional[str] = None, timeout: int = 5) -> bool:
    """서버 기동 시 Ollama 연결 가능 여부를 가볍게 확인하기 위한 헬스체크."""
    host = host or _default_host()
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False
