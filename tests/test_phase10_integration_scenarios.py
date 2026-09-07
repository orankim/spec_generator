"""
Phase 10 — 통합 테스트: 요청서가 명시한 5가지 질문 시나리오를 그대로 재현한다.

Test 1: 사양 분석만 (기존 정상 동작 회귀 확인)
Test 2: 사양 + 견적
Test 3: 조건 필터링 후 "견적이 가장 낮은 장비"
Test 4: 두 장비의 사양 + 견적 비교
Test 5: 이 견적의 추가 비용/제외 항목 확인
"""
from __future__ import annotations

import shutil
import unittest.mock as mock
from pathlib import Path

import pytest

from agent.pipeline import analyze_named_equipment, analyze_with_quotes
from agent.quote_intent import wants_quote_analysis
from agent.quote_parser import find_cheapest, load_quotation, analyze_quotation
from agent.schemas import RequirementSchema, RequirementTarget, SpecificationSchema

from .regression_lib import build_fake_embedding_db, patched_embeddings

_REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_PATH = "./_test_chroma_db_phase10_scenarios"


def _no_llm():
    return mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=SpecificationSchema())


@pytest.fixture(scope="module", autouse=True)
def indexed_db():
    with patched_embeddings():
        build_fake_embedding_db(TEST_DB_PATH)
    yield
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 1 — "폭 800 mm 이상을 Inline으로 검사하고 두께를 측정할 수 있는 장비를
# 찾아줘." -> 기존 사양 분석 정상
# ---------------------------------------------------------------------------
def test_1_spec_only_query_finds_candidates_without_quote_section():
    text = "폭 800 mm 이상을 Inline으로 검사하고 두께를 측정할 수 있는 장비를 찾아줘."
    assert wants_quote_analysis(text) is False

    requirement = RequirementSchema(
        raw_text=text, target=RequirementTarget(width_mm=800.0), inline_offline="inline", inspection_items=["thickness"]
    )
    with patched_embeddings(), _no_llm():
        result = analyze_with_quotes(requirement, db_path=TEST_DB_PATH, k_per_query=100)

    assert result["candidates"], "폭 800mm 이상 Inline 두께 검사기 후보가 없습니다"
    assert result["chosen_candidate"] is not None
    assert result["chosen_candidate"].status == "PASS"


# ---------------------------------------------------------------------------
# Test 2 — 위 질문 + "견적도 알려줘." -> 사양 + 견적
# ---------------------------------------------------------------------------
def test_2_spec_plus_quote_query_attaches_quotes():
    text = "폭 800 mm 이상을 Inline으로 검사하고 두께를 측정할 수 있는 장비를 찾아줘. 견적도 알려줘."
    assert wants_quote_analysis(text) is True

    requirement = RequirementSchema(
        raw_text=text, target=RequirementTarget(width_mm=800.0), inline_offline="inline", inspection_items=["thickness"]
    )
    with patched_embeddings(), _no_llm():
        result = analyze_with_quotes(requirement, db_path=TEST_DB_PATH, k_per_query=100)

    assert result["chosen_candidate"] is not None
    chosen_doc = result["chosen_candidate"].source_document
    assert chosen_doc in result["quote_analyses"], "추천 장비에 견적이 연결되지 않았습니다"
    chosen_analysis = result["quote_analyses"][chosen_doc][0]
    assert chosen_analysis.computed_grand_total is not None


# ---------------------------------------------------------------------------
# Test 3 — "두께와 표면 결함을 모두 검사할 수 있는 장비 중 견적이 가장 낮은
# 장비를 찾아줘." -> 조건 필터링 + 견적 비교(최솟값)
# ---------------------------------------------------------------------------
def test_3_condition_filter_then_cheapest_quote():
    text = "두께와 표면 결함을 모두 검사할 수 있는 장비 중 견적이 가장 낮은 장비를 찾아줘."
    assert wants_quote_analysis(text) is True

    requirement = RequirementSchema(raw_text=text, inspection_items=["thickness", "surface_defect"])
    with patched_embeddings(), _no_llm():
        result = analyze_with_quotes(requirement, db_path=TEST_DB_PATH, k_per_query=100)

    assert result["quote_analyses"], "두께+표면결함 조건을 만족하는 후보의 견적이 하나도 없습니다"
    cheapest = find_cheapest(result["quote_analyses"])
    assert cheapest is not None
    cheapest_spec_id, cheapest_analysis = cheapest
    # 실제로 최솟값인지 직접 재검증(find_cheapest를 신뢰하지 않고 다시 계산).
    all_totals = [
        a.computed_grand_total
        for analyses in result["quote_analyses"].values()
        for a in analyses
        if a.computed_grand_total is not None
    ]
    assert cheapest_analysis.computed_grand_total == min(all_totals)


# ---------------------------------------------------------------------------
# Test 4 — "두 장비의 사양과 견적을 비교해줘." -> SPEC + QUOTE 비교
# ---------------------------------------------------------------------------
def test_4_compare_two_named_equipment_spec_and_quote():
    result = analyze_named_equipment(["SPEC-001", "SPEC-011"])
    assert len(result["equipment"]) == 2
    for entry in result["equipment"]:
        assert entry["found"] is True
        assert entry["candidate"].equipment_fact is not None  # 사양
        assert len(entry["quote_analyses"]) >= 1  # 견적
    models = {e["candidate"].model for e in result["equipment"]}
    assert models == {"ES-200", "TP-200"}
    totals = [e["quote_analyses"][0].computed_grand_total for e in result["equipment"]]
    assert totals[0] != totals[1], "두 장비의 견적 최종 금액이 서로 달라야 비교가 의미 있습니다"


# ---------------------------------------------------------------------------
# Test 5 — "이 견적에서 추가 비용이나 제외된 항목이 있는지 확인해줘." -> QUOTE 분석
# ---------------------------------------------------------------------------
def test_5_check_additional_cost_and_excluded_items_in_a_quote():
    text = "이 견적에서 추가 비용이나 제외된 항목이 있는지 확인해줘."
    assert wants_quote_analysis(text) is True

    # "이 견적"은 대화 맥락(직전에 보여준 장비)을 가리킨다 — 대화 상태 관리는 UI
    # 레벨(Phase 9) 관심사이므로, 여기서는 엔진이 실제로 그 정보를 추출할 수
    # 있는지만 확인한다: installation_excluded 패턴(Phase 4)의 QUOTE-003.md를 예로 쓴다.
    quotation = load_quotation(str(_REPO_ROOT / "sample_quotes" / "QUOTE-003.md"))
    analysis = analyze_quotation(quotation)

    assert quotation.excluded_items, "이 케이스는 제외 항목이 있어야 하는 sample 패턴입니다"
    assert any("Installation" in item for item in quotation.excluded_items)
    assert analysis.computed_additional_cost_amount >= 0
