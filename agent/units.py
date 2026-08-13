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
from typing import List, Literal, Optional, Tuple

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
# 단위 뒤에는 \b(단어 경계)가 아니라 "라틴 문자/숫자가 바로 이어지지 않으면 OK"를
# 요구한다 — \b는 Python 정규식에서 한글 음절도 "단어 문자"로 취급하므로,
# "200μm까지"처럼 단위 뒤에 공백 없이 한글 조사가 붙거나("m"과 "까" 둘 다 단어
# 문자라 경계가 형성되지 않음), "%"처럼 단위 자체가 비단어 문자로 끝나는 경우
# (뒤에 공백이 아니라 다른 비단어 문자가 오면 마찬가지로 경계가 형성되지 않음)
# 매칭이 조용히 실패한다(실측됨: "최대 200 μm까지" 같은 표현에서 measurement_range를
# 놓치는 원인이었다). (?![a-zA-Z0-9])는 "mm" 뒤에 다른 라틴 단위 문자가 이어지는
# 잘못된 부분매칭(예: "mmHg")만 막고, 한글/공백/구두점/문자열 끝은 모두 허용한다.
_VALUE_UNIT_RE = re.compile(rf"([+-]?\d+(?:\.\d+)?)\s*({_UNIT_ALTERNATION})(?![a-zA-Z0-9])")


def parse_value_unit_with_span(text: str) -> Optional[Tuple[float, str, int, int]]:
    """parse_value_unit()과 동일하지만 매치된 (start, end) span도 함께 반환한다 —
    호출부가 그 구간을 마스킹해서 다른 필드를 이어서 파싱할 때 같은 숫자가 중복으로
    잡히지 않게 하려는 용도(예: agent.requirement_parser)."""
    m = _VALUE_UNIT_RE.search(text)
    if not m:
        return None
    return float(m.group(1)), normalize_unit(m.group(2)), m.start(), m.end()


def parse_value_unit(text: str) -> Optional[Tuple[float, str]]:
    """
    자연어/사양서 텍스트에서 첫 번째 (숫자, 단위) 쌍을 뽑는다. 없으면 None.
    "±"는 부호가 아니라 오차 표기이므로 숫자 파싱에는 영향을 주지 않는다
    (정규식이 [+-]? 하나만 소비하고 ±의 나머지 문자는 무시됨).
    """
    result = parse_value_unit_with_span(text)
    if result is None:
        return None
    value, unit, _start, _end = result
    return value, unit


def iter_value_units(text: str):
    """텍스트에서 발견되는 모든 (숫자, 단위) 쌍을 순서대로 yield한다.
    parse_value_unit()은 첫 번째만 반환하는 반면, 이 함수는 사양서 표(테이블) 한
    청크 안에 여러 항목의 수치가 섞여 있을 때 그 값들을 문서 원문과 하나씩
    대조해야 하는 용도(예: SourcedNumber 검증)로 쓰인다."""
    for m in _VALUE_UNIT_RE.finditer(text):
        yield float(m.group(1)), normalize_unit(m.group(2))


_RANGE_RE = re.compile(
    rf"([+-]?\d+(?:\.\d+)?)\s*(?:~|-|to|부터)\s*([+-]?\d+(?:\.\d+)?)\s*({_UNIT_ALTERNATION})(?![a-zA-Z0-9])"
)


def parse_range_with_span(text: str) -> Optional[Tuple[float, float, str, int, int]]:
    """parse_range()와 동일하지만 매치된 (start, end) span도 함께 반환한다 — 호출부가
    그 구간을 마스킹해서 이후 다른 필드(정확도 등)를 파싱할 때 범위의 숫자가 섞여
    들어가지 않게 하려는 용도(예: agent.requirement_parser)."""
    m = _RANGE_RE.search(text)
    if not m:
        return None
    lo, hi = float(m.group(1)), float(m.group(2))
    unit = normalize_unit(m.group(3))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi, unit, m.start(), m.end()


def parse_range(text: str) -> Optional[Tuple[float, float, str]]:
    """"0~200 μm", "0-200um", "0 to 200 mm" 등에서 (min, max, unit)을 뽑는다."""
    result = parse_range_with_span(text)
    if result is None:
        return None
    lo, hi, unit, _start, _end = result
    return lo, hi, unit


def range_covers(
    candidate_range: Tuple[float, float, str],
    required_range: Tuple[float, float, str],
) -> bool:
    """
    candidate_range(예: 후보 장비가 실제로 측정 가능한 범위)가 required_range(요구
    범위)를 완전히 포함하면 True. 서로 단위가 달라도(예: mm vs um) canonical 변환
    후 비교한다. PASS/FAIL 판정을 LLM에게 맡기지 않고 코드로 수행하기 위한 함수다.
    """
    c_lo, c_hi, c_unit = candidate_range
    r_lo, r_hi, r_unit = required_range
    c_lo_conv = convert(c_lo, c_unit, r_unit)
    c_hi_conv = convert(c_hi, c_unit, r_unit)
    return c_lo_conv <= r_lo and c_hi_conv >= r_hi


def evaluate_hard_requirements(
    required_range: Optional[Tuple[float, float, str]] = None,
    required_accuracy: Optional[Tuple[float, str, str]] = None,
    candidate_range: Optional[Tuple[float, float, str]] = None,
    candidate_accuracy: Optional[Tuple[float, str]] = None,
) -> Tuple[bool, List[str]]:
    """
    측정 범위/정확도 같은 hard requirement를 LLM 판단이 아니라 Python 코드로
    PASS/FAIL 판정한다(요청서: "이 비교는 가능하면 LLM 판단이 아니라 Python 코드로
    수행해라"). required_accuracy는 (value, unit, operator) — operator는
    candidate_accuracy가 만족해야 하는 방향(예: "<="이면 candidate <= required).
    검사할 조건이 주어지지 않으면(None) 그 조건은 건너뛴다.

    반환값: (모든 주어진 조건을 충족하면 True, 실패 사유 목록 — 비어 있으면 전부 충족).
    """
    reasons: List[str] = []
    ok = True

    if required_range is not None:
        if candidate_range is None:
            ok = False
            reasons.append("측정 범위 조건 불충족: 후보의 측정 범위 정보가 없습니다.")
        elif not range_covers(candidate_range, required_range):
            ok = False
            c_lo, c_hi, c_unit = candidate_range
            r_lo, r_hi, r_unit = required_range
            reasons.append(
                f"측정 범위 조건 불충족: 후보 {c_lo}~{c_hi}{c_unit}는 요구 범위 "
                f"{r_lo}~{r_hi}{r_unit}를 포함하지 못합니다."
            )

    if required_accuracy is not None:
        req_value, req_unit, operator = required_accuracy
        if candidate_accuracy is None:
            ok = False
            reasons.append("정확도 조건 불충족: 후보의 정확도 정보가 없습니다.")
        else:
            cand_value, cand_unit = candidate_accuracy
            if not compare_values(cand_value, cand_unit, req_value, req_unit, operator):
                ok = False
                reasons.append(
                    f"정확도 조건 불충족: 후보 {cand_value}{cand_unit}는 요구 조건 "
                    f"{operator} {req_value}{req_unit}를 만족하지 못합니다."
                )

    return ok, reasons


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
