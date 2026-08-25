"""
회귀 테스트: 대화형 UI가 후속 메시지를 반영한 뒤 사용자에게 보여주는 문구가
내부 필드명(accuracy, raw_text, required_accuracy_um 등)을 그대로 노출하던
버그(실사용자 보고: "기존 요구사항에 다음 조건을 반영했습니다: accuracy, raw_text,
required_accuracy_um") — agent.routes._summarize_requirement_changes()가 이를
사람이 읽는 label/action(added/changed/removed)으로 정리해서 돌려주는지 검증한다.
"""
from agent.requirement_parser import apply_conversational_patch
from agent.routes import _summarize_requirement_changes
from agent.schemas import RequirementRange, RequirementSchema, RequirementTarget, RequirementValue


def test_removing_accuracy_never_exposes_internal_field_names():
    requirement = RequirementSchema(
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
        raw_text="초기 요구사항",
    )
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "정확도 조건은 빼줘.")
    after = requirement.model_dump()

    summary = _summarize_requirement_changes(before, after)
    labels = {s["label"] for s in summary}
    assert labels == {"정확도"}, summary  # accuracy/required_accuracy_um이 하나의 라벨로 합쳐져야 한다
    assert all(s["label"] not in ("accuracy", "required_accuracy_um", "raw_text") for s in summary)
    assert summary[0]["action"] == "removed"

    # 내부 필드명이 요약 어디에도 절대 등장하면 안 된다.
    flat = str(summary)
    for leaked in ("accuracy", "required_accuracy_um", "raw_text"):
        assert leaked not in flat


def test_raw_text_change_is_never_reported():
    """raw_text는 매 턴 누적되어 항상 바뀌지만, 이는 사용자에게 보여줄 "조건"이 아니다."""
    requirement = RequirementSchema(raw_text="첫 메시지")
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "Inline으로 사용할 거야.")
    after = requirement.model_dump()

    summary = _summarize_requirement_changes(before, after)
    assert {s["label"] for s in summary} == {"검사 모드"}


def test_width_change_action_is_changed_not_added():
    requirement = RequirementSchema(target=RequirementTarget(width_mm=500.0))
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "폭 조건을 800 mm 이상으로 변경해줘.")
    after = requirement.model_dump()

    summary = _summarize_requirement_changes(before, after)
    by_label = {s["label"]: s["action"] for s in summary}
    assert by_label["폭"] == "changed"


def test_width_first_set_action_is_added():
    requirement = RequirementSchema()
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "폭은 800 mm 이상이어야 해.")
    after = requirement.model_dump()

    summary = _summarize_requirement_changes(before, after)
    by_label = {s["label"]: s["action"] for s in summary}
    assert by_label["폭"] == "added"


def test_no_changes_returns_empty_summary():
    requirement = RequirementSchema(inspection_items=["thickness"])
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "아무 조건도 언급하지 않는 문장.")
    after = requirement.model_dump()

    # raw_text만 바뀌었을 뿐 실제 "조건"은 바뀌지 않았어야 한다.
    summary = _summarize_requirement_changes(before, after)
    assert summary == []


def test_multiple_concepts_changed_in_one_turn():
    requirement = RequirementSchema()
    before = requirement.model_dump()
    apply_conversational_patch(requirement, "폭은 600 mm 이상, 정확도는 ±1 um 이하로 해줘.")
    after = requirement.model_dump()

    summary = _summarize_requirement_changes(before, after)
    labels = {s["label"] for s in summary}
    assert "폭" in labels
    assert "정확도" in labels
