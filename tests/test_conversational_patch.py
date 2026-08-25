"""
챗봇 UI가 여러 턴에 걸쳐 조건을 추가/변경/삭제할 때 쓰는
agent.requirement_parser.apply_conversational_patch()에 대한 테스트.

핵심 시나리오(요청서 7/8절, 사용자가 직접 예시로 든 대화 흐름):
  1. "전극 두께 검사기를 찾아줘." -> inspection_items=["thickness"]
  2. "Inline으로 사용할 거야." -> inline_offline="inline" (1단계에서 정한 값은 유지)
  3. "측정 범위는 0~300 μm야." -> measurement_range=0~300 (1/2단계 값은 유지)

  최종적으로 세 조건이 모두 RequirementSchema에 함께 남아 있어야 한다.

  변경: "폭 조건을 1000 mm 이상으로 변경해줘." / "정확도는 ±2 μm 이하로 변경해줘."
  삭제: "폭 조건은 빼줘." / "속도 조건은 빼줘."

절대로 발생하면 안 되는 회귀(요청서 6절): 사용자가 말하지 않은 accuracy를
conversational patch가 스스로 만들어내는 것.
"""
from agent.requirement_parser import apply_conversational_patch
from agent.schemas import RequirementRange, RequirementSchema, RequirementTarget, RequirementValue


def test_multi_turn_conditions_accumulate_without_losing_earlier_turns():
    requirement = RequirementSchema(raw_text="전극 두께 검사기를 찾아줘.", inspection_items=["thickness"])

    apply_conversational_patch(requirement, "Inline으로 사용할 거야.")
    assert requirement.inline_offline == "inline"
    assert requirement.inspection_items == ["thickness"]  # 1단계 값 보존

    apply_conversational_patch(requirement, "측정 범위는 0~300 μm야.")
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 300.0
    # 앞선 두 턴에서 확정한 값이 세 번째 턴 이후에도 그대로 남아 있어야 한다.
    assert requirement.inline_offline == "inline"
    assert requirement.inspection_items == ["thickness"]


def test_second_turn_alone_never_wipes_unrelated_fields_from_first_turn():
    """회귀 방지: "Inline으로 사용할 거야."만 패치해도 이미 있던 material/width가 지워지면 안 된다."""
    requirement = RequirementSchema(
        raw_text="양극 폭 200mm 검사기",
        target=RequirementTarget(material="양극", width_mm=200.0),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    apply_conversational_patch(requirement, "Inline으로 사용할 거야.")
    assert requirement.target.material == "양극"
    assert requirement.target.width_mm == 200.0
    assert requirement.accuracy.value == 1.0
    assert requirement.inline_offline == "inline"


def test_patch_never_invents_accuracy_the_user_never_mentioned():
    """요청서 6절 핵심 회귀 방지: accuracy를 언급하지 않은 메시지가 accuracy를 만들어내면 안 된다."""
    requirement = RequirementSchema(inspection_items=["thickness"])
    apply_conversational_patch(requirement, "Inline으로 사용할 거야.")
    assert requirement.accuracy is None
    assert requirement.required_accuracy_um is None


def test_change_width_condition():
    requirement = RequirementSchema(target=RequirementTarget(width_mm=500.0))
    apply_conversational_patch(requirement, "폭 조건을 1000 mm 이상으로 변경해줘.")
    assert requirement.target.width_mm == 1000.0


def test_change_accuracy_condition_overwrites_existing_value():
    requirement = RequirementSchema(accuracy=RequirementValue(value=1.0, unit="um", operator="<="), required_accuracy_um=1.0)
    apply_conversational_patch(requirement, "정확도는 ±2 μm 이하로 변경해줘.")
    assert requirement.accuracy.value == 2.0
    assert requirement.required_accuracy_um == 2.0


def test_remove_width_condition():
    requirement = RequirementSchema(target=RequirementTarget(material="전극", width_mm=800.0))
    apply_conversational_patch(requirement, "폭 조건은 빼줘.")
    assert requirement.target.width_mm is None
    assert requirement.target.material == "전극"  # 폭만 지워지고 다른 필드는 유지


def test_remove_measurement_range_condition():
    requirement = RequirementSchema(measurement_range=RequirementRange(min=0.0, max=300.0, unit="um"))
    apply_conversational_patch(requirement, "측정 범위 조건은 삭제해줘.")
    assert requirement.measurement_range is None


def test_remove_speed_condition_is_a_safe_noop_when_nothing_was_set():
    """요청서 예시("속도 조건은 빼줘")를 그대로 보내도, 애초에 속도 조건이 없으면 에러 없이 조용히 무시된다."""
    requirement = RequirementSchema(inspection_items=["thickness"])
    apply_conversational_patch(requirement, "속도 조건은 빼줘.")
    assert requirement.measurement_speed is None
    assert requirement.inspection_items == ["thickness"]


def test_inspection_items_are_added_not_replaced():
    requirement = RequirementSchema(inspection_items=["thickness"])
    apply_conversational_patch(requirement, "표면 결함도 같이 검사해줘.")
    assert set(requirement.inspection_items) == {"thickness", "surface_defect"}


def test_add_speed_filter_after_initial_search_per_item15_example():
    """요청서 15절 시나리오: 기존 조건(Width>=800, Inline, 0~500um, 3D Profile)에
    속도 조건을 추가해도 기존 조건이 전부 유지되어야 한다."""
    requirement = RequirementSchema(
        target=RequirementTarget(width_mm=800.0),
        inline_offline="inline",
        measurement_range=RequirementRange(min=0.0, max=500.0, unit="um"),
        inspection_items=["profile_3d"],
    )
    apply_conversational_patch(requirement, "속도는 500 mm/s 이상인 장비만 보여줘.")
    assert requirement.target.width_mm == 800.0
    assert requirement.inline_offline == "inline"
    assert requirement.measurement_range.min == 0.0 and requirement.measurement_range.max == 500.0
    assert requirement.inspection_items == ["profile_3d"]


def test_raw_text_accumulates_across_turns_for_audit_trail():
    requirement = RequirementSchema(raw_text="전극 두께 검사기를 찾아줘.")
    apply_conversational_patch(requirement, "Inline으로 사용할 거야.")
    assert "전극 두께 검사기를 찾아줘." in requirement.raw_text
    assert "Inline으로 사용할 거야." in requirement.raw_text
