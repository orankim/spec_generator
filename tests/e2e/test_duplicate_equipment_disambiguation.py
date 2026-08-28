"""
중복 Equipment Name Disambiguation UX 테스트.

배경: sample_specs Corpus 무결성 조사(직전 작업)에서 서로 다른 두 사양서
(SPEC-044.md/SPEC-051.md)가 우연히 같은 Equipment Name("MultiInspect MI-800")을
쓰는 사례가 발견됐다. 실제 파이프라인으로 재현한 결과, 대화 중 후속 질문으로
요구사항이 바뀌면(예: 정확도를 더 엄격하게) 실제로 서로 다른 SPEC 문서가
chosen_candidate로 선택될 수 있었다(scripts 재현: 정확도 <=1.0um 질의는
SPEC-051, Multi-sensor 원리를 강조한 <=0.8um 질의는 SPEC-044를 선택). 두 결과가
같은 대화 화면에 함께 나타나면 사용자는 "같은 장비가 중복 추천된 것"인지 "실제로
다른 장비"인지 이름만으로 구분할 수 없다 — 이 파일은 그 상황에서 main.py가
추가하는 조건부 Disambiguation Label(Card Subtitle)이 실제로 동작하는지, 그리고
중복이 없는 정상적인 경우에는 기존 UI가 전혀 바뀌지 않는지를 검증한다.

후속 작업(동일 장비명 재등장 시 대화 UX 검증)에서, 실제 브라우저로 재현한 결과
Card Subtitle(구분 정보)만으로는 "이 값 차이가 서로 다른 장비를 가리킨다"는 사실
자체가 사용자에게 명확히 전달되지 않는 문제(값만 다르고 왜 다른지 설명이 없음)를
확인했다 — 이를 보완하기 위해 짧은 Contextual Hint("ℹ️ 이전 추천과 이름은
같지만, 서로 다른 장비입니다.")를 "새로 등장해 기존 그룹과 충돌하는" 카드에만
추가했다. ("...다른 사양의 장비입니다"라는 초안 문구는 한국어에서 "같은 제품의
다른 옵션/구성"으로도 흔히 읽힐 수 있어 — 예: "다른 사양의 노트북" = 같은 모델의
RAM/SSD 구성만 다름 — 실제로 다른 제품이라는 의미를 명확히 하기 위해 "서로 다른
장비"로 재확인 후 교체했다.) 과거에 이미 표시된 카드에 Hint를 소급 삽입하지
않는다 — Subtitle은
그룹이 확정될 때마다 대칭적으로 다시 계산되는 것이 맞지만(그래야 그룹 구성이
바뀌어도 항상 올바른 구분 필드를 쓸 수 있다), Hint까지 과거 카드에 끼워 넣으면
과거 메시지가 두 번(Subtitle + Hint) 바뀌는 셈이라 오히려 혼란을 키우기
때문이다 — 이 파일의 "historical re-render" 테스트가 이 결정을 명시적으로
검증한다.

main.py의 computeEquipmentDisambiguation()/pickDisambiguationLabels()/
pickContextualHints() JS 로직을 그대로 통해서만 검증한다(별도 재구현 없음) — 이
테스트가 커버하는 것은 "Backend가 이미 돌려주는 데이터만으로 Frontend가 올바르게
조건부 표시를 하는가"이다.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from fixtures import make_analyze_response, make_candidate, make_generate_spec_response, make_specification

QUESTION_1 = "폭 600 mm 이상의 전극을 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 Inline 복합 검사기를 찾아줘. 측정 범위는 0~300 μm이고 정확도는 ±1 μm 이하여야 해."
QUESTION_2 = "폭 800 mm 전극을 Inline으로, Multi-sensor 방식으로 두께와 표면 결함을 검사할 수 있는 복합 검사기를 찾아줘. 정확도는 ±0.8 μm 이하여야 해."

DUPLICATE_NAME = "MultiInspect MI-800"


def _duplicate_spec_and_candidate_a() -> tuple[dict, dict]:
    """SPEC-051.md 쪽 후보 — 실제 재현에서 확인한 값(정확도 1.0, 3D Laser
    Profilometry, Scratch/Crack/Particle/Coating Defect)을 그대로 반영한다."""
    spec = make_specification(name=DUPLICATE_NAME, manufacturer="MultiInspect", model="MI-800")
    candidate = make_candidate(
        status="PASS",
        candidate_id="cand-51",
        manufacturer="MultiInspect",
        model="MI-800",
        source_document="SPEC-051.md",
        # 실제 재현(SPEC-044.md/SPEC-051.md)에서 Measurement Type은 둘 다
        # "Non-contact"로 동일했다 — 우선순위 2단계(Measurement Method/Principle)가
        # 실제로 "같다"고 판단해 3단계(Inspection Item)로 넘어가는 상황을 그대로
        # 재현하려면 이 필드를 동일하게 맞춰야 한다(Measurement Principle만 다르면
        # 2단계에서 먼저 걸린다 — 별도로 그 경우도 검증하고 싶다면 principle을
        # 다르게 두면 된다. 이 테스트는 문제 상황에서 실제로 관찰된 값을 그대로 쓴다).
        measurement_method="Non-contact",
        measurement_principle="3D Laser Profilometry",
        defect_types=["Scratch", "Crack", "Particle", "Coating Defect"],
        width_mm=800.0,
        range_min=0.0,
        range_max=500.0,
        range_unit="um",
        accuracy_value=1.0,
        accuracy_unit="um",
    )
    return spec, candidate


def _duplicate_spec_and_candidate_b() -> tuple[dict, dict]:
    """SPEC-044.md 쪽 후보 — 실제 재현에서 확인한 값(정확도 0.8, Multi-sensor,
    Surface Defect)을 그대로 반영한다."""
    spec = make_specification(name=DUPLICATE_NAME, manufacturer="MultiInspect", model="MI-800")
    candidate = make_candidate(
        status="PASS",
        candidate_id="cand-44",
        manufacturer="MultiInspect",
        model="MI-800",
        source_document="SPEC-044.md",
        measurement_method="Non-contact",
        measurement_principle="Multi-sensor",
        defect_types=["Surface Defect"],
        width_mm=800.0,
        range_min=0.0,
        range_max=500.0,
        range_unit="um",
        accuracy_value=0.8,
        accuracy_unit="um",
    )
    return spec, candidate


def _send(page: Page, text: str) -> None:
    page.fill("#chatInput", text)
    page.click("#sendBtn")
    expect(page.locator(".msg-row.ai .card-header").last).to_be_visible(timeout=10000)
    page.wait_for_function("() => !document.getElementById('sendBtn').disabled", timeout=10000)


def _mock_turn(mock_api, spec: dict, candidate: dict) -> None:
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response(specification=spec, candidate=candidate))


# ----- Test A: Normal Equipment (중복 없음) -----


def test_normal_equipment_has_no_disambiguation_subtitle(agent_page: Page, mock_api):
    """이름이 유일한 정상 케이스는 기존 UI를 그대로 유지해야 한다 — Card Subtitle이
    전혀 나타나지 않아야 한다(불필요한 Disambiguation 금지)."""
    mock_api.mock("**/api/agent/analyze-requirement", make_analyze_response())
    mock_api.mock("**/api/agent/generate-spec", make_generate_spec_response("pass"))
    _send(agent_page, "두께 검사기 찾아줘.")

    header = agent_page.locator(".card-header", has_text="ThicknessPro TP-800")
    expect(header).to_be_visible()
    assert agent_page.locator(".card-subtitle").count() == 0
    assert agent_page.locator(".card-hint").count() == 0


# ----- Test B: Duplicate Equipment Name -----


def test_duplicate_equipment_name_shows_both_candidates_with_disambiguation(agent_page: Page, mock_api):
    """같은 이름의 서로 다른 SPEC 문서가 한 대화 안에 등장하면: (1) 두 후보 모두
    화면에 남아 있고(하나가 사라지지 않음), (2) 서로 다른 구분 정보가 표시되어야
    한다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)

    spec_b, candidate_b = _duplicate_spec_and_candidate_b()
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)

    headers = agent_page.locator(".card-header", has_text=DUPLICATE_NAME)
    expect(headers).to_have_count(2)  # 두 Candidate 모두 유지됨 — 하나로 합쳐지거나 사라지지 않음

    subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    assert len(subtitles) == 2, f"Disambiguation Label이 두 카드 모두에 있어야 함: {subtitles}"
    assert subtitles[0] != subtitles[1], f"서로 다른 후보인데 같은 구분 정보가 표시됨: {subtitles}"
    # 이번 조합은 Manufacturer(둘 다 MultiInspect)/Measurement Method(둘 다 미기재)가
    # 같고 Measurement Principle이 실제로 갈리므로, 우선순위상 그 다음 필드인
    # Inspection Item(defect_types)에서 구분되어야 한다(요청서 5절 우선순위 예시).
    assert "Scratch" in subtitles[0] or "Scratch" in subtitles[1]
    assert "Surface Defect" in subtitles[0] or "Surface Defect" in subtitles[1]
    # 내부 SPEC 파일명이 굳이 필요하지 않은 상황에서는 노출되지 않아야 한다(요청서 3/4절).
    assert not any("SPEC-" in s for s in subtitles)

    # Contextual Hint(요청서: "실제로 서로 다른 장비"임을 사용자가 이해할 수 있는 안내)는
    # 새로 등장해 충돌을 일으킨 두 번째 카드에만, 정확히 1회 나타나야 한다 — 첫 번째
    # 카드(등장 시점에는 비교 대상이 없었음)에는 붙지 않는다(아래 historical re-render
    # 테스트에서 더 구체적으로 검증).
    hints = agent_page.locator(".card-hint").all_text_contents()
    assert len(hints) == 1, f"Contextual Hint는 정확히 1개(새로 등장한 카드)여야 함: {hints}"
    assert "서로 다른 장비" in hints[0]
    # "사양이 다르다"는 한국어에서 "같은 제품의 다른 구성(옵션)"으로도 흔히 읽혀
    # 실제로 다른 제품이라는 의미가 약해질 수 있으므로 이 표현은 쓰지 않는다.
    assert "다른 사양" not in hints[0], hints[0]
    # 내부 데이터 구조 용어를 사용자에게 노출하지 않는다(요청서 4절 금지어).
    forbidden_terms = ["source_document", "SPEC ID", "spec_id", "candidate collision", "Duplicate equipment detected"]
    assert not any(term in hints[0] for term in forbidden_terms), hints[0]


def test_duplicate_equipment_name_with_identical_source_is_not_flagged(agent_page: Page, mock_api):
    """이름도 같고 source_document(실제 문서)도 같다면 "진짜 같은 추천이 반복된
    것"이므로 Disambiguation을 붙이지 않는다 — 서로 다른 문서일 때만 조건부로
    나타나야 한다는 정책을 정확히 구분해서 검증한다."""
    spec, candidate = _duplicate_spec_and_candidate_a()
    _mock_turn(mock_api, spec, candidate)
    _send(agent_page, QUESTION_1)
    _mock_turn(mock_api, spec, candidate)  # 완전히 동일한 candidate(같은 source_document)를 다시 추천
    _send(agent_page, QUESTION_1)

    headers = agent_page.locator(".card-header", has_text=DUPLICATE_NAME)
    expect(headers).to_have_count(2)
    assert agent_page.locator(".card-subtitle").count() == 0
    assert agent_page.locator(".card-hint").count() == 0, "완전히 같은 장비가 반복 추천된 것이므로 안내 문구도 필요 없다"


def test_duplicate_equipment_name_reverse_order_shows_hint_on_the_new_card(agent_page: Page, mock_api):
    """등장 순서를 바꿔도(SPEC-044 먼저, SPEC-051 나중) 동작이 대칭적이어야 한다 —
    Hint는 항상 "나중에 새로 등장한" 카드에만 붙어야 하며, 어느 물리적 SPEC 파일이
    먼저인지에 의존하면 안 된다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()  # SPEC-051.md
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()  # SPEC-044.md

    _mock_turn(mock_api, spec_b, candidate_b)  # SPEC-044를 먼저 보냄(역순)
    _send(agent_page, QUESTION_2)
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)

    cards = agent_page.locator(".card", has=agent_page.locator(".card-header", has_text=DUPLICATE_NAME))
    expect(cards).to_have_count(2)
    assert cards.nth(0).locator(".card-hint").count() == 0, "먼저 등장한 카드(SPEC-044)에는 Hint가 없어야 함"
    assert cards.nth(1).locator(".card-hint").count() == 1, "나중에 등장한 카드(SPEC-051)에만 Hint가 있어야 함"
    subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    assert len(subtitles) == 2 and subtitles[0] != subtitles[1]


def test_three_equipment_sharing_the_same_name_are_all_distinguishable(agent_page: Page, mock_api):
    """향후 동일 Equipment Name을 가진 세 번째 장비가 추가되는 경우를 가정한
    synthetic 검증(요청서 3절) — corpus를 건드리지 않고 fixture로만 구성한다.
    세 후보 모두 일관된 구분 필드로 구분되어야 하고(우선순위 로직이 그룹 크기에
    상관없이 동작), 처음 등장한 후보에는 Hint가 없고 두 번째/세 번째에는 각각
    Hint가 있어야 한다."""
    name = "TripleTest TT-900"
    spec = make_specification(name=name, manufacturer="TripleTest", model="TT-900")
    common = dict(
        manufacturer="TripleTest", model="TT-900", width_mm=800.0,
        range_min=0.0, range_max=500.0, range_unit="um", accuracy_value=1.0, accuracy_unit="um",
    )
    candidate_a = make_candidate(status="PASS", candidate_id="cand-a", source_document="SPEC-A.md",
        measurement_method="Laser Triangulation", **common)
    candidate_b = make_candidate(status="PASS", candidate_id="cand-b", source_document="SPEC-B.md",
        measurement_method="White Light Interferometry", **common)
    candidate_c = make_candidate(status="PASS", candidate_id="cand-c", source_document="SPEC-C.md",
        measurement_method="Confocal", **common)

    for candidate in (candidate_a, candidate_b, candidate_c):
        _mock_turn(mock_api, spec, candidate)
        _send(agent_page, f"{name} 후보 질문 ({candidate['source_document']})")

    cards = agent_page.locator(".card", has=agent_page.locator(".card-header", has_text=name))
    expect(cards).to_have_count(3)  # 세 후보 모두 화면에 유지됨 — 하나로 합쳐지거나 사라지지 않음

    subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    assert len(subtitles) == 3
    assert len(set(subtitles)) == 3, f"세 후보 모두 서로 다른 구분 정보를 가져야 함: {subtitles}"
    assert all("측정 방식" in s for s in subtitles), subtitles

    assert cards.nth(0).locator(".card-hint").count() == 0, "맨 처음 등장한 후보는 비교 대상이 없어 Hint가 없어야 함"
    assert cards.nth(1).locator(".card-hint").count() == 1
    assert cards.nth(2).locator(".card-hint").count() == 1
    # 안내 문구가 여러 번(2회) 나타나도 문구 자체는 항상 동일해 대화가 산만해지지 않는다.
    hints = agent_page.locator(".card-hint").all_text_contents()
    assert hints[0] == hints[1]


# ----- Test C: Deterministic Disambiguation -----


def test_disambiguation_label_is_deterministic_across_repeated_renders(agent_page: Page, mock_api):
    """같은 Input을 여러 번 렌더링해도(요청서: 최소 3회) 항상 같은 Disambiguation
    필드/값이 선택되어야 한다 — Random이나 렌더링 순서에 의존하면 안 된다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()

    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)

    first_subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    first_hints = agent_page.locator(".card-hint").all_text_contents()

    for _ in range(3):
        # renderAll()을 강제로 다시 태워도(예: 사이드바 전환 후 복귀) 동일한
        # 대화 데이터로부터 항상 같은 Label/Hint가 나와야 한다.
        agent_page.evaluate("window.dispatchEvent(new Event('resize'))")
        agent_page.evaluate("renderAll()")
        repeated_subtitles = agent_page.locator(".card-subtitle").all_text_contents()
        repeated_hints = agent_page.locator(".card-hint").all_text_contents()
        assert repeated_subtitles == first_subtitles, f"반복 렌더링 결과가 달라짐: {first_subtitles} vs {repeated_subtitles}"
        assert repeated_hints == first_hints, f"Contextual Hint가 반복 렌더링마다 달라짐: {first_hints} vs {repeated_hints}"


# ----- Test: Historical Re-render (동일 장비명 재등장 시 대화 UX 검증, 요청서 1/5절) -----


def test_first_card_gains_subtitle_but_never_a_hint_when_second_candidate_appears(agent_page: Page, mock_api):
    """실제 재현(요청서 1/5절)에서 확인된 사실: 두 번째 후보가 등장하면
    renderAll()이 전체 대화를 다시 그리므로 첫 번째 카드도 다시 렌더링된다.
    이때 Subtitle(구분 정보)은 그룹이 확정되는 대로 두 카드 모두에 대칭적으로
    나타나는 것이 맞다(그래야 두 카드가 같은 기준으로 비교된다) — 하지만
    Contextual Hint는 "새로 등장한" 카드에만 붙어야 한다. 첫 번째 카드에 Hint까지
    소급 삽입되면 사용자가 이미 본 카드가 두 가지 방식으로 바뀌는 셈이라 오히려
    혼란을 키운다는 판단(TESTING.md "과거 메시지 처리 방식" 참고)을 그대로
    검증한다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)

    first_card = agent_page.locator(".card", has=agent_page.locator(".card-header", has_text=DUPLICATE_NAME)).first
    assert first_card.locator(".card-subtitle").count() == 0, "첫 카드 단독 등장 시점에는 구분할 대상이 없어 Subtitle도 없어야 한다"
    assert first_card.locator(".card-hint").count() == 0

    spec_b, candidate_b = _duplicate_spec_and_candidate_b()
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)

    cards_with_name = agent_page.locator(".card", has=agent_page.locator(".card-header", has_text=DUPLICATE_NAME))
    expect(cards_with_name).to_have_count(2)
    first_card_after = cards_with_name.nth(0)
    second_card_after = cards_with_name.nth(1)

    # 첫 번째 카드: Subtitle은 새로 생겼지만(정상 — 이제 비교 대상이 생겼으므로),
    # Hint는 여전히 없어야 한다.
    assert first_card_after.locator(".card-subtitle").count() == 1, "두 번째 후보 등장 후 첫 카드도 구분 정보를 가져야 한다"
    assert first_card_after.locator(".card-hint").count() == 0, "과거 카드에 안내 문구가 소급 삽입되면 안 된다"

    # 두 번째(새로 등장한) 카드: Subtitle과 Hint 둘 다 있어야 한다.
    assert second_card_after.locator(".card-subtitle").count() == 1
    assert second_card_after.locator(".card-hint").count() == 1, "새로 등장한 카드에는 안내 문구가 있어야 한다"

    # 의도하지 않은 다른 정보 변경이 없는지 확인 — 첫 카드의 헤더/본문 핵심 수치는
    # 그대로여야 한다(Subtitle 추가 외에는 바뀌지 않음).
    assert "MultiInspect MI-800" in first_card_after.locator(".card-header").text_content()


# ----- Test: New Conversation Isolation (요청서 7절) -----


def test_new_conversation_does_not_inherit_disambiguation_from_previous_conversation(agent_page: Page, mock_api):
    """동일 Equipment Name 판단 범위는 반드시 현재 Conversation 내부여야 한다 —
    이전 대화에서 SPEC-051/SPEC-044가 충돌했더라도, 새 대화에서 SPEC-051만
    단독으로 나오면 Subtitle도 Hint도 나타나면 안 된다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)
    expect(agent_page.locator(".card-header", has_text=DUPLICATE_NAME)).to_have_count(2)
    assert agent_page.locator(".card-subtitle").count() == 2
    assert agent_page.locator(".card-hint").count() == 1

    agent_page.click("#newChatBtn")
    expect(agent_page.locator(".welcome-block")).to_be_visible()

    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)

    expect(agent_page.locator(".card-header", has_text=DUPLICATE_NAME)).to_have_count(1)
    assert agent_page.locator(".card-subtitle").count() == 0, "이전 대화의 중복이 새 대화에 영향을 주면 안 된다"
    assert agent_page.locator(".card-hint").count() == 0, "이전 대화의 중복이 새 대화에 영향을 주면 안 된다"


# ----- Test D: Fallback to Source Document -----


def test_fallback_to_source_document_when_all_other_fields_identical(agent_page: Page, mock_api):
    """Manufacturer/Measurement Method/Inspection Item/Width/Range/Accuracy가
    전부 같고 오직 source_document만 다르면, 최종 수단으로 "Reference: SPEC-xxx"
    형태를 사용해야 한다(요청서 4/6절)."""
    spec = make_specification(name=DUPLICATE_NAME, manufacturer="MultiInspect", model="MI-800")
    candidate_1 = make_candidate(
        status="PASS", candidate_id="cand-1", manufacturer="MultiInspect", model="MI-800",
        source_document="SPEC-044.md", measurement_method="non_contact", measurement_principle="Laser",
        defect_types=["Surface Defect"], width_mm=800.0, range_min=0.0, range_max=500.0, range_unit="um",
        accuracy_value=0.8, accuracy_unit="um",
    )
    candidate_2 = make_candidate(
        status="PASS", candidate_id="cand-2", manufacturer="MultiInspect", model="MI-800",
        source_document="SPEC-051.md", measurement_method="non_contact", measurement_principle="Laser",
        defect_types=["Surface Defect"], width_mm=800.0, range_min=0.0, range_max=500.0, range_unit="um",
        accuracy_value=0.8, accuracy_unit="um",
    )

    _mock_turn(mock_api, spec, candidate_1)
    _send(agent_page, QUESTION_1)
    _mock_turn(mock_api, spec, candidate_2)
    _send(agent_page, QUESTION_2)

    subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    assert len(subtitles) == 2
    assert any("SPEC-044" in s for s in subtitles), subtitles
    assert any("SPEC-051" in s for s in subtitles), subtitles
    # 내부 파일명 자체가 최종 수단으로만 쓰였는지 "Reference:" 접두어로 확인한다
    # (요청서 4절: 내부 파일명을 기본 UI에 직접 크게 노출하는 것은 피하되, 마지막
    # 수단으로 쓸 때는 사람이 읽을 수 있는 형태로).
    assert all(s.startswith("Reference:") for s in subtitles), subtitles


# ----- Test E: Conversation Persistence -----


def test_disambiguation_survives_reload_and_localstorage_restore(agent_page: Page, mock_api, live_server: str):
    """중복 결과를 표시한 뒤 페이지를 새로고침(localStorage 복원)해도 동일한
    Disambiguation이 유지되어야 한다."""
    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()

    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)

    before_subtitles = agent_page.locator(".card-subtitle").all_text_contents()
    before_hints = agent_page.locator(".card-hint").all_text_contents()
    assert len(before_subtitles) == 2
    assert len(before_hints) == 1

    agent_page.goto(f"{live_server}/agent")
    agent_page.wait_for_selector("#chatInput")
    expect(agent_page.locator(".card-header", has_text=DUPLICATE_NAME)).to_have_count(2, timeout=10000)

    after_subtitles = sorted(agent_page.locator(".card-subtitle").all_text_contents())
    after_hints = sorted(agent_page.locator(".card-hint").all_text_contents())
    assert after_subtitles == sorted(before_subtitles), f"새로고침 후 Disambiguation이 바뀜: {before_subtitles} -> {after_subtitles}"
    assert after_hints == sorted(before_hints), f"새로고침 후 Contextual Hint가 바뀜: {before_hints} -> {after_hints}"


# ----- Test F: Markdown (regression — 구조상 다중 후보 나열 없음) -----


def test_markdown_generation_still_works_for_a_duplicate_named_candidate(agent_page: Page, mock_api):
    """Markdown 생성은 candidate 1개 단위로 동작한다(여러 후보를 한 문서에 나열하는
    구조 자체가 없음 — build-candidate-markdown은 chosen_candidate 하나만 받는다).
    이름이 중복되는 후보라도 기존처럼 정상적으로 다운로드 버튼이 동작해야 한다
    (회귀 없음 확인)."""
    spec, candidate = _duplicate_spec_and_candidate_a()
    _mock_turn(mock_api, spec, candidate)
    _send(agent_page, QUESTION_1)

    mock_api.mock(
        "**/api/agent/build-candidate-markdown",
        {"status": "success", "file_name": "electrode_inspection_candidate_test1234.md", "download_url": "/api/download/electrode_inspection_candidate_test1234.md"},
    )
    agent_page.click(".build-markdown-btn")
    expect(agent_page.locator("a.download-btn")).to_be_visible(timeout=10000)


# ----- Test G: Accessibility -----


def test_duplicate_disambiguation_has_no_new_accessibility_violations(agent_page: Page, mock_api):
    from axe_playwright_python.sync_playwright import Axe

    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(agent_page, QUESTION_1)
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(agent_page, QUESTION_2)

    # 구분 정보/안내 문구가 화면에 숨겨진 텍스트가 아니라 실제로 읽히는 일반
    # 텍스트인지 확인 — 스크린 리더가 동일 Equipment Name 카드가 반복되어도
    # 구분 정보를 읽을 수 있어야 한다(요청서 9절).
    subtitle = agent_page.locator(".card-subtitle").first
    expect(subtitle).to_be_visible()
    assert subtitle.text_content().strip() != ""
    hint = agent_page.locator(".card-hint").first
    expect(hint).to_be_visible()
    assert hint.text_content().strip() != ""
    assert agent_page.locator(".card-hint").get_attribute("aria-hidden") is None

    axe = Axe()
    results = axe.run(agent_page)
    violations = results.response["violations"]
    serious_or_worse = [v for v in violations if v.get("impact") in ("serious", "critical")]
    assert serious_or_worse == [], (
        "중복 Equipment Name Disambiguation 렌더링 후 axe-core가 serious/critical 위반을 발견함: "
        + "; ".join(f"{v['id']}: {[n['target'] for n in v['nodes']]}" for v in serious_or_worse)
    )


# ----- Test: Mobile regression (요청서 11절) -----


def test_duplicate_disambiguation_does_not_break_mobile_layout(page: Page, live_server: str, mock_api):
    """375px 뷰포트에서 Disambiguation Label이 추가되어도 가로 스크롤/카드 폭
    Overflow가 생기지 않아야 한다(Mobile Drawer/Focus Trap 자체는 이 변경과
    무관하므로 별도 회귀 대상이 아니다 — 기존 tests/e2e/test_mobile_drawer.py가
    계속 검증한다)."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_server}/agent")
    page.wait_for_selector("#chatInput")

    spec_a, candidate_a = _duplicate_spec_and_candidate_a()
    spec_b, candidate_b = _duplicate_spec_and_candidate_b()
    _mock_turn(mock_api, spec_a, candidate_a)
    _send(page, QUESTION_1)
    _mock_turn(mock_api, spec_b, candidate_b)
    _send(page, QUESTION_2)

    expect(page.locator(".card-subtitle")).to_have_count(2)
    expect(page.locator(".card-hint")).to_have_count(1)  # Contextual Hint 문구가 더 길어 Overflow 위험이 더 큼
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= 375 + 1, f"Disambiguation Label/Hint 추가 후 가로 스크롤 발생: scrollWidth={scroll_width}"
    send_btn_box = page.locator("#sendBtn").bounding_box()
    assert send_btn_box is not None and send_btn_box["x"] + send_btn_box["width"] <= 375 + 1, "전송 버튼이 화면 밖으로 밀려남"
    hint_box = page.locator(".card-hint").bounding_box()
    assert hint_box is not None and hint_box["x"] >= 0 and hint_box["x"] + hint_box["width"] <= 375 + 1, "Contextual Hint가 카드 밖으로 넘침"
