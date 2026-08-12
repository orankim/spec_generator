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
from typing import Any, Dict, Optional, Type, TypeVar

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _default_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _default_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")


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
    timeout: int = 180,
) -> Dict[str, Any]:
    """
    주어진 JSON Schema를 만족하는 JSON을 Ollama로부터 강제로 받아온다.
    """
    model = model or _default_model()
    host = host or _default_host()
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

    logger.info("Ollama structured generate 호출: model=%s, host=%s", model, host)
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
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
