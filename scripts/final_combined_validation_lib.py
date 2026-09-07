"""
Strategy A/B/C를 ranking_failure_cache.json과 동일한 스키마(by_k 구조)로 합쳐,
기존 scripts/ground_truth_ambiguity_lib.py / scripts/evaluation_framework_lib.py
함수를 그대로 재사용할 수 있게 만드는 순수 함수 모듈. Ollama 호출 없음 — 이미
만들어진 두 캐시(ranking_failure_cache.json, final_combined_validation_cache.json)만
합친다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RANKING_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_STRATEGY_C_CACHE_PATH = _REPO_ROOT / "benchmark_results" / "final_combined_validation_cache.json"


def load_ranking_cache() -> Dict[str, Any]:
    return json.loads(_RANKING_CACHE_PATH.read_text(encoding="utf-8"))


def load_strategy_c_raw() -> Dict[str, Any]:
    return json.loads(_STRATEGY_C_CACHE_PATH.read_text(encoding="utf-8"))


def build_strategy_a_cache() -> Dict[str, Any]:
    """Strategy A = ranking_failure_cache.json의 k=15 슬라이스를 그대로 단일 k
    캐시로 재포장(재계산 없음)."""
    ranking_cache = load_ranking_cache()
    cases = {}
    for cid, case in ranking_cache["cases"].items():
        cases[cid] = {
            "expected_spec_ids": case["expected_spec_ids"],
            "expected_final_status": case["expected_final_status"],
            "by_k": {"0": case["by_k"]["15"]},
        }
    return {"environment": ranking_cache["environment"], "k_values": [0], "cases": cases}


def build_strategy_b_cache() -> Dict[str, Any]:
    """Strategy B = ranking_failure_cache.json의 k=20 슬라이스."""
    ranking_cache = load_ranking_cache()
    cases = {}
    for cid, case in ranking_cache["cases"].items():
        cases[cid] = {
            "expected_spec_ids": case["expected_spec_ids"],
            "expected_final_status": case["expected_final_status"],
            "by_k": {"0": case["by_k"]["20"]},
        }
    return {"environment": ranking_cache["environment"], "k_values": [0], "cases": cases}


def build_strategy_c_cache() -> Dict[str, Any]:
    """Strategy C = 48개 미영향 케이스는 Strategy A(k=15) 그대로 복사(수학적으로
    동일함이 scripts/strategy_c_blast_radius.py로 이미 증명됨), 8개 영향 케이스만
    실제 real RAG 재실행 결과(final_combined_validation_cache.json)로 교체."""
    ranking_cache = load_ranking_cache()
    strategy_c_raw = load_strategy_c_raw()
    affected_ids = set(strategy_c_raw["affected_case_ids"])

    cases = {}
    for cid, case in ranking_cache["cases"].items():
        if cid in affected_ids:
            real = strategy_c_raw["results"][cid]
            cases[cid] = {
                "expected_spec_ids": case["expected_spec_ids"],  # ranking_cache 쪽 정의를 그대로 써 일관성 유지
                "expected_final_status": case["expected_final_status"],
                "by_k": {"0": {"candidates": real["candidates"]}},
            }
        else:
            cases[cid] = {
                "expected_spec_ids": case["expected_spec_ids"],
                "expected_final_status": case["expected_final_status"],
                "by_k": {"0": case["by_k"]["15"]},
            }
    return {"environment": ranking_cache["environment"], "k_values": [0], "cases": cases}
