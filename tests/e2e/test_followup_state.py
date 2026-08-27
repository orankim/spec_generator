"""
요청서 3절 섹션 4 — 후속 질문 및 대화 상태.

첫 질문으로 조건(Width/Inline/Thickness/Surface Defect/Measurement Range/Accuracy)을
설정한 뒤 "정확도 조건은 빼줘."라고 요청하면, accuracy만 제거되고 나머지 조건은
유지되는지 검증한다. main.py는 후속 메시지를 LLM 없이 /api/agent/update-requirement로
보내고(agent.requirement_parser.apply_conversational_patch), 그 결과 requirement를
다음 /api/agent/generate-spec 호출에 그대로 실어 보낸다 — 이 두 호출의 실제 payload를
가로채 확인한다(요청서: "API 요청 payload 또는 Requirement Schema를 확인하여 실제로
accuracy 조건만 제거되었는지도 검증").
"""
from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_generate_spec_response, make_requirement, make_update_response

FIRST_QUESTION = (
    "폭 600 mm 이상의 전극을 Inline으로 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 "
    "장비를 찾아줘. 측정 범위는 0~300 μm이고 정확도는 ±1 μm 이하여야 해."
)
FOLLOWUP_QUESTION = "정확도 조건은 빼줘."


def _first_requirement():
    from agent.schemas import RequirementRange, RequirementTarget, RequirementValue

    return make_requirement(
        raw_text=FIRST_QUESTION,
        target=RequirementTarget(width_mm=600.0, material="전극"),
        inspection_items=["thickness", "surface_defect"],
        inline_offline="inline",
        measurement_range=RequirementRange(min=0.0, max=300.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        measurement_speed=None,
    )


def _requirement_with_accuracy_removed():
    req = dict(_first_requirement())
    req["accuracy"] = None
    req["required_accuracy_um"] = None
    return req


def test_followup_removes_only_accuracy_keeps_other_conditions(agent_page: Page, mock_api):
    before = _first_requirement()
    after = _requirement_with_accuracy_removed()

    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response(requirement=before))
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", FIRST_QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.ai").last).to_be_visible(timeout=10000)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    # 후속 메시지는 update-requirement(패치)를 호출한다 — analyze-requirement(LLM 전체
    # 파싱)를 다시 호출하지 않는다.
    mock_api.mock(
        "**/api/agent/update-requirement",
        make_update_response(after, changed_summary=[{"label": "정확도", "action": "removed"}]),
    )
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    agent_page.fill("#chatInput", FOLLOWUP_QUESTION)
    agent_page.click("#sendBtn")
    expect(agent_page.locator(".msg-row.user").last).to_contain_text(FOLLOWUP_QUESTION)
    agent_page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)

    # 1) 후속 메시지가 analyze-requirement가 아니라 update-requirement로 갔는지.
    assert mock_api.call_count("**/api/agent/update-requirement") == 1
    assert mock_api.call_count("**/api/agent/analyze-requirement") == 1, "후속 메시지가 새 대화로 잘못 인식되어 analyze-requirement가 다시 호출됨"

    # 2) update-requirement에 실제로 보낸 payload를 검사 — 이전 대화의 전체 조건이
    #    current_requirement로 유지된 채 전달됐는지(새로운 대화로 오인해 조건이
    #    통째로 날아가지 않았는지).
    sent_payload = mock_api.last_payload("**/api/agent/update-requirement")
    sent_requirement = sent_payload["current_requirement"]
    assert sent_requirement["target"]["width_mm"] == 600.0
    assert sent_requirement["inline_offline"] == "inline"
    assert sorted(sent_requirement["inspection_items"]) == ["surface_defect", "thickness"]
    assert sent_requirement["measurement_range"] == {"min": 0.0, "max": 300.0, "unit": "um"}
    assert sent_requirement["accuracy"] == {"value": 1.0, "unit": "um", "operator": "<="}
    assert sent_payload["message"] == FOLLOWUP_QUESTION

    # 3) 그 다음 generate-spec 호출에 실린 requirement — accuracy만 사라지고 나머지는 유지.
    generate_payload = mock_api.last_payload("**/api/agent/generate-spec")
    final_requirement = generate_payload["requirement"]
    assert final_requirement["accuracy"] is None, "accuracy 조건이 제거되지 않음"
    assert final_requirement["required_accuracy_um"] is None
    assert final_requirement["target"]["width_mm"] == 600.0, "Width 조건이 사라짐"
    assert final_requirement["inline_offline"] == "inline", "Inline 조건이 사라짐"
    assert sorted(final_requirement["inspection_items"]) == ["surface_defect", "thickness"], "검사 항목 조건이 사라짐"
    assert final_requirement["measurement_range"] == {"min": 0.0, "max": 300.0, "unit": "um"}, "측정 범위 조건이 사라짐"

    # 4) 화면에도 "삭제됐다"는 사실이 드러나야 한다(새 대화로 오인되지 않았다는 사용자 확인).
    full_text = agent_page.locator("#messages").inner_text()
    assert "정확도" in full_text
