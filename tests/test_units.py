"""agent/units.py — 단위 파싱/변환/비교 (요청서 5절, 15절)."""
import pytest

from agent.units import (
    UnitError,
    compare_values,
    convert,
    parse_operator,
    parse_range,
    parse_value_unit,
    unit_dimension,
)


def test_parse_value_unit_basic():
    assert parse_value_unit("두께 정확도 1 μm 이하") == (1.0, "um")
    assert parse_value_unit("±0.5 μm") == (0.5, "um")
    assert parse_value_unit("800nm") == (800.0, "nm")
    assert parse_value_unit("1500 mm/s") == (1500.0, "mm/s")
    assert parse_value_unit("no numbers here") is None


def test_parse_value_unit_prefers_longest_unit_token():
    # "mm/s"가 "mm"보다 먼저 매칭되어야 한다 (부분 매칭으로 mm만 뽑히면 안 됨).
    assert parse_value_unit("scan speed 1200 mm/s") == (1200.0, "mm/s")


def test_parse_range():
    assert parse_range("0~200 μm") == (0.0, 200.0, "um")
    assert parse_range("0-200um") == (0.0, 200.0, "um")
    assert parse_range("200~0 μm") == (0.0, 200.0, "um")  # 순서 뒤바뀌어도 정렬
    assert parse_range("just text") is None


def test_parse_operator():
    assert parse_operator("정확도 1um 이하") == "<="
    assert parse_operator("accuracy <= 1um") == "<="
    assert parse_operator("해상도 10um 이상") == ">="
    assert parse_operator("no operator here") is None


def test_convert_same_dimension():
    assert convert(800, "nm", "um") == pytest.approx(0.8)
    assert convert(1, "mm", "um") == pytest.approx(1000)
    assert convert(1, "m", "mm") == pytest.approx(1000)
    assert convert(1, "m/min", "mm/s") == pytest.approx(1000 / 60)
    assert convert(1000, "ms", "s") == pytest.approx(1.0)


def test_convert_rejects_cross_dimension():
    with pytest.raises(UnitError):
        convert(1, "um", "s")


def test_unit_dimension():
    assert unit_dimension("um") == "length"
    assert unit_dimension("mm/s") == "speed"
    assert unit_dimension("s") == "time"
    assert unit_dimension("%") == "ratio"
    with pytest.raises(UnitError):
        unit_dimension("kg")


def test_compare_values_same_unit():
    assert compare_values(0.5, "um", 1.0, "um", "<=") is True
    assert compare_values(2.0, "um", 1.0, "um", "<=") is False


def test_compare_values_cross_unit_case4():
    """Edge Case 4 (요청서 43절): Requirement accuracy<=1um, Specification=800nm -> PASS."""
    assert compare_values(800, "nm", 1.0, "um", "<=") is True
    assert compare_values(1200, "nm", 1.0, "um", "<=") is False


def test_compare_values_operators():
    assert compare_values(10, "um", 10, "um", "=") is True
    assert compare_values(11, "um", 10, "um", ">") is True
    assert compare_values(9, "um", 10, "um", "<") is True
    assert compare_values(10, "um", 10, "um", ">=") is True
