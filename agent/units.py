"""
단위 변환/파싱/비교를 전담하는 순수 Python 모듈. LLM에게 단위 비교를 맡기지 않는다
(요청서 5절, 15절, 45절 — "PASS/FAIL 같은 중요한 판단을 LLM에게 전적으로 맡기지 않는다").

자연어의 숫자+단위를 구조화된 (value, unit) 또는 (min, max, unit)으로 뽑아내고,
서로 다른 단위(예: nm vs um)라도 같은 물리량이면 변환 후 비교할 수 있게 한다.

지원 단위(요청서 5절 명시 최소 목록):
  길이: nm, um(μm), mm, m
  속도: mm/s, m/s, m/min
  시간: ms, s
  비율: %

이 모듈은 순수 함수만 제공한다 — 어떤 Pydantic 스키마도 import하지 않으므로
RequirementSchema/SpecificationSchema 양쪽에서 안전하게 재사용할 수 있다.
"""
from __future__ import annotations

import re
from typing import Literal, Optional, Tuple

Dimension = Literal["length", "speed", "time", "ratio"]

# 각 단위 -> (차원, 그 차원의 canonical 단위로 변환하는 배율)
# canonical: length=um, speed=mm/s, time=s, ratio=%
_UNIT_TABLE = {
    "nm": ("length", 0.001),
    "um": ("length", 1.0),
    "μm": ("length", 1.0),
    "mm": ("length", 1000.0),
    "m": ("length", 1_000_000.0),
    "mm/s": ("speed", 1.0),
    "m/s": ("speed", 1000.0),
    "m/min": ("speed", 1000.0 / 60.0),
    "ms": ("time", 0.001),
    "s": ("time", 1.0),
    "sec": ("time", 1.0),
    "%": ("ratio", 1.0),
}

_CANONICAL_UNIT = {"length": "um", "speed": "mm/s", "time": "s", "ratio": "%"}

_OPERATOR_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("<=", "<="), ("≤", "<="), ("이하", "<="),
    (">=", ">="), ("≥", ">="), ("이상", ">="),
    ("<", "<"), ("미만", "<"),
    (">", ">"), ("초과", ">"),
)


class UnitError(ValueError):
    """단위 파싱/변환 실패."""


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    """단위 표기를 canonical 별칭으로 정규화한다 (μm -> um, 공백 제거 등)."""
    if unit is None:
        return None
    u = unit.strip()
    if u == "μm":
        u = "um"
    if u == "sec":
        u = "s"
    return u or None


def unit_dimension(unit: str) -> Dimension:
    u = normalize_unit(unit)
    if u not in _UNIT_TABLE:
        raise UnitError(f"지원하지 않는 단위입니다: {unit!r}")
    return _UNIT_TABLE[u][0]  # type: ignore[return-value]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """같은 차원(length/speed/time/ratio) 안에서만 변환 가능하다."""
    fu, tu = normalize_unit(from_unit), normalize_unit(to_unit)
    if fu not in _UNIT_TABLE or tu not in _UNIT_TABLE:
        raise UnitError(f"지원하지 않는 단위입니다: {from_unit!r} -> {to_unit!r}")
    dim_from, factor_from = _UNIT_TABLE[fu]
    dim_to, factor_to = _UNIT_TABLE[tu]
    if dim_from != dim_to:
        raise UnitError(f"서로 다른 차원의 단위는 변환할 수 없습니다: {from_unit!r}({dim_from}) vs {to_unit!r}({dim_to})")
    canonical_value = value * factor_from
    return canonical_value / factor_to


def to_canonical(value: float, unit: str) -> Tuple[float, str]:
    dim = unit_dimension(unit)
    canonical_unit = _CANONICAL_UNIT[dim]
    return convert(value, unit, canonical_unit), canonical_unit


def parse_operator(text: str) -> Optional[str]:
    for token, op in _OPERATOR_PATTERNS:
        if token in text:
            return op
    return None


# "±0.5 μm", "1.0um", "≤ 1 μm", "800nm", "1500 mm/s", "0.8 sec" 등을 잡는다.
# 단위는 길이/속도/시간/비율 토큰 중 가장 긴 것부터 매칭한다(mm/s가 mm보다 먼저 매칭되도록).
_UNIT_ALTERNATION = "|".join(
    sorted((re.escape(u) for u in _UNIT_TABLE), key=len, reverse=True)
)
_VALUE_UNIT_RE = re.compile(rf"([+-]?\d+(?:\.\d+)?)\s*({_UNIT_ALTERNATION})\b")


def parse_value_unit(text: str) -> Optional[Tuple[float, str]]:
    """
    자연어/사양서 텍스트에서 첫 번째 (숫자, 단위) 쌍을 뽑는다. 없으면 None.
    "±"는 부호가 아니라 오차 표기이므로 숫자 파싱에는 영향을 주지 않는다
    (정규식이 [+-]? 하나만 소비하고 ±의 나머지 문자는 무시됨).
    """
    m = _VALUE_UNIT_RE.search(text)
    if not m:
        return None
    return float(m.group(1)), normalize_unit(m.group(2))


_RANGE_RE = re.compile(
    rf"([+-]?\d+(?:\.\d+)?)\s*(?:~|-|to|부터)\s*([+-]?\d+(?:\.\d+)?)\s*({_UNIT_ALTERNATION})\b"
)


def parse_range(text: str) -> Optional[Tuple[float, float, str]]:
    """"0~200 μm", "0-200um", "0 to 200 mm" 등에서 (min, max, unit)을 뽑는다."""
    m = _RANGE_RE.search(text)
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    unit = normalize_unit(m.group(3))
    return (lo, hi, unit) if lo <= hi else (hi, lo, unit)


def compare_values(
    spec_value: float,
    spec_unit: Optional[str],
    req_value: float,
    req_unit: Optional[str],
    operator: str,
) -> bool:
    """
    spec_value(장비의 실제 사양)가 req_value(요구사항)를 만족하는지 판정한다.
    단위가 다르면(예: nm vs um) canonical 단위로 변환한 뒤 비교한다. 단위가 아예
    없으면(둘 다 None) 같은 스케일이라고 가정하고 그대로 비교한다.
    """
    if spec_unit and req_unit and normalize_unit(spec_unit) != normalize_unit(req_unit):
        spec_value = convert(spec_value, spec_unit, req_unit)
    if operator == "<=":
        return spec_value <= req_value
    if operator == ">=":
        return spec_value >= req_value
    if operator == "<":
        return spec_value < req_value
    if operator == ">":
        return spec_value > req_value
    if operator == "=":
        return spec_value == req_value
    raise UnitError(f"지원하지 않는 operator입니다: {operator!r}")
