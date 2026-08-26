"""
대화형 Requirement State 누적 업데이트 Regression Tests (Conversation Test 1 ~ Conversation Test 5)

요청서 7절:
- Conversation Test 1: 누적 추가 (폭&Inline -> 정확도 1μm -> 표면결함 추가)
- Conversation Test 2: 조건 값 수정 (1μm -> 0.5μm 덮어쓰기)
- Conversation Test 3: 조건 삭제 ("정확도 조건은 빼줘" -> accuracy = None)
- Conversation Test 4: 검사 항목 추가 (Inline&표면결함 -> 스크래치&오염 추가)
- Conversation Test 5: 폭 조건 수정 + 속도 조건 유지 (폭 800mm -> 속도 500mm/s -> 폭 1000mm 변경)
"""
import pytest
from tests.regression_lib import parse_with_empty_llm
from agent.requirement_parser import apply_conversational_patch


def test_conversation_1_cumulative_addition():
    """
    Conversation Test 1:
    User 1: "폭 600mm 이상의 전극을 Inline으로 검사할 수 있는 장비를 찾아줘."
    User 2: "정확도는 1μm 이하야."
    User 3: "표면 결함도 검사해야 해."
    """
    req = parse_with_empty_llm("폭 600mm 이상의 전극을 Inline으로 검사할 수 있는 장비를 찾아줘.")
    assert req.target.width_mm == 600.0
    assert req.inline_offline == "inline"

    apply_conversational_patch(req, "정확도는 1μm 이하야.")
    assert req.target.width_mm == 600.0
    assert req.inline_offline == "inline"
    assert req.accuracy is not None
    assert req.accuracy.value == 1.0

    apply_conversational_patch(req, "표면 결함도 검사해야 해.")
    assert req.target.width_mm == 600.0
    assert req.inline_offline == "inline"
    assert req.accuracy.value == 1.0
    assert "surface_defect" in req.inspection_items or "surface_defect" in req.inspection_categories


def test_conversation_2_value_modification():
    """
    Conversation Test 2:
    User 1: "폭 600mm 이상의 Inline 두께 검사기를 찾아줘."
    User 2: "정확도는 1μm 이하로 해줘."
    User 3: "아니, 정확도는 0.5μm 이하야."
    """
    req = parse_with_empty_llm("폭 600mm 이상의 Inline 두께 검사기를 찾아줘.")
    apply_conversational_patch(req, "정확도는 1μm 이하로 해줘.")
    assert req.accuracy.value == 1.0

    apply_conversational_patch(req, "아니, 정확도는 0.5μm 이하야.")
    assert req.accuracy.value == 0.5
    assert req.required_accuracy_um == 0.5


def test_conversation_3_condition_removal():
    """
    Conversation Test 3:
    User 1: "폭 600mm 이상의 Inline 두께 검사기를 찾아줘. 정확도는 1μm 이하야."
    User 2: "정확도 조건은 빼줘."
    """
    req = parse_with_empty_llm("폭 600mm 이상의 Inline 두께 검사기를 찾아줘. 정확도는 1μm 이하야.")
    assert req.target.width_mm == 600.0
    assert req.inline_offline == "inline"
    assert req.accuracy.value == 1.0

    apply_conversational_patch(req, "정확도 조건은 빼줘.")
    assert req.target.width_mm == 600.0
    assert req.inline_offline == "inline"
    assert req.accuracy is None
    assert req.required_accuracy_um is None


def test_conversation_4_inspection_item_addition():
    """
    Conversation Test 4:
    User 1: "Inline으로 표면 결함을 검사할 수 있는 장비를 찾아줘."
    User 2: "스크래치와 오염도 검사해야 해."
    """
    req = parse_with_empty_llm("Inline으로 표면 결함을 검사할 수 있는 장비를 찾아줘.")
    assert req.inline_offline == "inline"

    apply_conversational_patch(req, "스크래치와 오염도 검사해야 해.")
    assert req.inline_offline == "inline"
    assert "scratch" in req.inspection_items
    assert "contamination" in req.inspection_items


def test_conversation_5_width_modification_with_speed():
    """
    Conversation Test 5:
    User 1: "폭 800mm 이상인 전극 검사기를 찾아줘."
    User 2: "속도는 500mm/s 이상이어야 해."
    User 3: "그런데 폭 조건은 1000mm 이상으로 바꿔줘."
    """
    req = parse_with_empty_llm("폭 800mm 이상인 전극 검사기를 찾아줘.")
    assert req.target.width_mm == 800.0

    apply_conversational_patch(req, "속도는 500mm/s 이상이어야 해.")
    assert req.target.width_mm == 800.0
    assert req.measurement_speed is not None
    assert req.measurement_speed.value == 500.0

    apply_conversational_patch(req, "그런데 폭 조건은 1000mm 이상으로 바꿔줘.")
    assert req.target.width_mm == 1000.0
    assert req.measurement_speed.value == 500.0
