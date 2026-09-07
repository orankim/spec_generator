"""
Phase 7/11 — 근거자료 기반 답변 및 Hallucination 방어 테스트.

요청서가 명시한 금지 항목을 하나씩 직접 검증한다:
  - SPEC에 없는 사양 생성 금지 / QUOTE에 없는 가격·옵션·비용 생성 금지
  - UNKNOWN을 사실로 바꾸지 않음 / UNKNOWN을 PASS로 처리하지 않음
  - 근거 오류(장비 A를 장비 B의 정보로 잘못 연결) 금지
  - 비교 근거 없는 가격 적정성 판단 금지
"""
from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.pipeline import analyze_named_equipment
from agent.quote_generator import QuoteNarrative, build_quote_facts_prompt, find_unrecognized_numbers
from agent.quote_parser import analyze_quotation, load_quotation, parse_quotation_markdown

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_QUOTES_DIR = _REPO_ROOT / "sample_quotes"


# ---------------------------------------------------------------------------
# 구조적 방지: LLM 출력 스키마 자체에 숫자 필드가 없다
# ---------------------------------------------------------------------------
def test_narrative_schema_has_no_numeric_fields():
    numeric_types = (float, int)
    for name, field in QuoteNarrative.model_fields.items():
        annotation_str = str(field.annotation)
        assert not any(t.__name__ in annotation_str for t in numeric_types), (
            f"QuoteNarrative.{name}이 숫자형을 담을 수 있습니다({field.annotation}) — "
            "LLM 출력 스키마에는 숫자 필드가 있으면 안 됩니다(요청서 7단계)."
        )


def test_prompt_contains_no_fabrication_instruction():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    from agent.quote_generator import _NO_FABRICATION_INSTRUCTION

    assert "만들지 마세요" in _NO_FABRICATION_INSTRUCTION
    assert "가격이 비싸다" in _NO_FABRICATION_INSTRUCTION or "적정" in _NO_FABRICATION_INSTRUCTION


def test_prompt_only_states_real_computed_values():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    prompt = build_quote_facts_prompt(analysis)
    assert f"{analysis.computed_grand_total:,.0f}" in prompt
    assert f"{analysis.computed_equipment_amount:,.0f}" in prompt


# ---------------------------------------------------------------------------
# 안전망: 서술 텍스트에 등장하는 숫자가 실제 값 밖의 것이면 검출
# ---------------------------------------------------------------------------
def test_find_unrecognized_numbers_detects_fabricated_price():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    fake_text = "이 장비의 실제 시장가는 999,999,999원으로 추정됩니다."
    suspicious = find_unrecognized_numbers(fake_text, analysis)
    assert 999_999_999 in [round(v) for v in suspicious]


def test_find_unrecognized_numbers_no_false_positive_on_real_values():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    real_text = f"최종 금액은 {analysis.computed_grand_total:,.0f}원이며, 본체 금액은 {analysis.computed_equipment_amount:,.0f}원입니다."
    assert find_unrecognized_numbers(real_text, analysis) == []


def test_find_unrecognized_numbers_ignores_small_numbers():
    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    text = "옵션은 2개이며 할부는 3회차입니다."
    assert find_unrecognized_numbers(text, analysis) == []


# ---------------------------------------------------------------------------
# QUOTE에 없는 가격/옵션/비용 생성 금지 (구조적 — 파서가 문서 밖 값을 만들지 않음)
# ---------------------------------------------------------------------------
def test_parser_never_invents_options_when_section_absent():
    text = """# Equipment Quotation

## General

- Manufacturer: NoOptionCo
- Model: NO-1

## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| NoOptionCo NO-1 (Main Unit) | 1 | 50,000,000 | 50,000,000 |

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 50,000,000 |
"""
    quotation = parse_quotation_markdown(text, "QUOTE-NOOPT.md")
    assert quotation.options == []
    assert quotation.additional_costs == []
    analysis = analyze_quotation(quotation)
    assert analysis.computed_options_amount == 0
    assert analysis.computed_additional_cost_amount == 0


# ---------------------------------------------------------------------------
# UNKNOWN을 사실로 바꾸지 않음 / UNKNOWN을 PASS로 처리하지 않음
# ---------------------------------------------------------------------------
def test_missing_vat_stays_unknown_not_assumed_zero_or_included():
    text = """# Equipment Quotation

## General

- Manufacturer: NoVatCo
- Model: NV-1

## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| NoVatCo NV-1 (Main Unit) | 1 | 10,000,000 | 10,000,000 |

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 10,000,000 |
"""
    quotation = parse_quotation_markdown(text, "QUOTE-NOVAT.md")
    analysis = analyze_quotation(quotation)
    # VAT 관련 언급이 전혀 없으면 0%로 추측하거나 "포함"으로 단정하지 않고 None(UNKNOWN)으로 남는다.
    assert quotation.totals.vat_amount is None
    assert analysis.computed_vat_amount is None
    assert analysis.computed_grand_total is None


def test_no_matching_candidate_never_reported_as_pass():
    """이미 tests/test_integration_verification.py::test_6_no_matching_equipment가
    회귀로 지키고 있는 원칙(정확도<=0.05um 충족 후보 없음)을 Phase 7 관점(UNKNOWN을
    PASS로 취급하지 않음)에서 다시 한번 명시적으로 확인한다."""
    from agent.candidate_matcher import build_candidates, select_best_candidate
    from agent.requirement_parser import parse_requirement_text
    from agent.schemas import RequirementSchema, RequirementValue
    from langchain_core.documents import Document
    from glob import glob

    requirement = RequirementSchema(
        raw_text="정확도 ±0.03um 이내로 측정할 수 있는 장비를 찾아줘.",
        accuracy=RequirementValue(value=0.03, unit="um", operator="<="),
        required_accuracy_um=0.03,
    )
    docs = []
    for path in sorted(glob(str(_REPO_ROOT / "sample_specs" / "SPEC-*.md"))):
        text = Path(path).read_text(encoding="utf-8")
        docs.append(Document(page_content=text, metadata={"filename": Path(path).name}))
    candidates = build_candidates(requirement, docs)
    chosen = select_best_candidate(candidates)
    if chosen is not None:
        assert chosen.status != "PASS", "0.03um을 충족하는 후보가 없어야 하는데 PASS로 선택되었습니다"


# ---------------------------------------------------------------------------
# 근거 오류 금지: 장비 A의 사양을 장비 B의 정보로 잘못 연결하지 않는다
# ---------------------------------------------------------------------------
def test_no_cross_contamination_between_different_equipment_quotes():
    result = analyze_named_equipment(["SPEC-001", "SPEC-011"])
    es200 = next(e for e in result["equipment"] if e["spec_id"] == "SPEC-001")
    tp200 = next(e for e in result["equipment"] if e["spec_id"] == "SPEC-011")
    assert es200["candidate"].model == "ES-200"
    assert tp200["candidate"].model == "TP-200"
    # 두 장비의 견적이 서로 다른 문서에서 왔는지(연결이 섞이지 않았는지) 확인.
    es200_quote = es200["quote_analyses"][0].quotation
    tp200_quote = tp200["quote_analyses"][0].quotation
    assert es200_quote.general.model == "ES-200"
    assert tp200_quote.general.model == "TP-200"
    assert es200_quote.source_file != tp200_quote.source_file


# ---------------------------------------------------------------------------
# Real Ollama 실제 서술 생성 — qwen2.5:3b가 실제로 숫자를 지어내지 않는지 확인
# (Ollama 없으면 자동 SKIP. 실패하면 실제 모델의 한계를 있는 그대로 보고한다 —
# 테스트를 통과시키기 위해 기준을 낮추지 않는다.)
# ---------------------------------------------------------------------------
@pytest.mark.real_rag
def test_real_llm_narrative_does_not_fabricate_numbers():
    from tests import real_rag_lib as rag

    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버에 연결할 수 없습니다: {env.error}")

    from agent.quote_generator import generate_quote_narrative

    quotation = load_quotation(str(_QUOTES_DIR / "QUOTE-001.md"))
    analysis = analyze_quotation(quotation)
    narrative = generate_quote_narrative(analysis)

    full_text = " ".join(
        [narrative.equipment_vs_options_summary or "", narrative.excluded_items_explanation or ""]
        + narrative.key_considerations
    )
    suspicious = find_unrecognized_numbers(full_text, analysis)
    assert suspicious == [], f"LLM이 견적에 없는 숫자를 만들어냈습니다: {suspicious} (생성된 텍스트: {full_text!r})"
