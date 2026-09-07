"""
Phase 6 — 사양 분석 + 견적 분석 통합 테스트.

요청서 6단계가 요구하는 5가지 질문 유형(사양만/견적만/사양+견적/조건+견적/비교)이
실제로 동작하는지 확인한다. Ollama가 없는 환경에서도 대부분 검증 가능하도록
tests/regression_lib.py의 fake-embedding/empty-LLM 패턴을 그대로 재사용하고
(중복 구현 금지), 실제 LLM 품질이 필요한 부분만 real_rag 마커로 분리한다.
"""
from __future__ import annotations

import shutil
import unittest.mock as mock
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.equipment_lookup import find_specs_by_mentioned_names
from agent.pipeline import analyze_named_equipment, analyze_with_quotes
from agent.quote_intent import wants_quote_analysis
from agent.schemas import RequirementSchema, RequirementTarget, SpecificationSchema

from .regression_lib import build_fake_embedding_db, patched_embeddings

# main.py는 기동 시 load_dotenv()를 호출해 .env의 OLLAMA_MODEL(예: qwen2.5:3b)을
# 읽지만, pytest 단독 실행은 그 경로를 타지 않는다 — real_rag 테스트가 .env 없이
# 기본값(qwen2.5:14b, 이 환경에는 미설치)으로 떨어져 조용히 실패하는 것을 막는다
# (다른 real_rag 테스트 파일들과 동일한 패턴, 예: tests/test_retrieval_recall.py).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TEST_DB_PATH = "./_test_chroma_db_quote_integration"


def _patched_llm_spec_generation():
    """generate_specification()이 실제 LLM을 호출하지 않도록 빈 SpecificationSchema로
    스텁한다 — analyze_with_quotes()가 내부적으로 retrieve_and_generate()를 그대로
    쓰므로(중복 구현 금지) 이 스텁이 필요하다. candidate_matcher.build_candidates()는
    이 LLM 호출과 무관하게 retrieved_docs를 직접 재분석하므로 영향받지 않는다."""
    return mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=SpecificationSchema())


# ---------------------------------------------------------------------------
# 의도 판정 (LLM 미사용, 결정론적)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("ES-200의 사양을 알려줘.", False),
        ("ES-200의 견적을 분석해줘.", True),
        ("ES-200의 사양과 견적을 같이 분석해줘.", True),
        ("이 견적에서 추가 비용이나 제외된 항목을 찾아줘.", True),
        ("폭 800mm 이상 Inline 검사기를 찾아줘.", False),
        ("가격이 얼마인가요?", True),
    ],
)
def test_quote_intent_detection(text, expected):
    assert wants_quote_analysis(text) is expected


# ---------------------------------------------------------------------------
# 장비 이름 기반 조회 / 비교
# ---------------------------------------------------------------------------
def test_find_specs_by_single_mentioned_name():
    matches = find_specs_by_mentioned_names("ES-200의 사양을 알려줘.")
    assert any(m.spec_id == "SPEC-001" for m in matches)


def test_find_specs_by_two_mentioned_names_for_comparison():
    matches = find_specs_by_mentioned_names("ES-200과 MI-800을 비교해줘.")
    spec_ids = {m.spec_id for m in matches}
    assert "SPEC-001" in spec_ids
    assert {"SPEC-044", "SPEC-051"} & spec_ids  # 중복 이름 둘 다 안전하게 포함


# ---------------------------------------------------------------------------
# 사양만 / 견적만 / 사양+견적 — analyze_named_equipment 하나로 전부 지원
# (어떤 절을 답변에 보여줄지는 quote_intent 판정에 달려 있고, 엔진 자체는 항상
# 둘 다 계산해둔다 — Phase 7에서 "물어보지 않은 정보까지 장황하게 나열" 방지는
# 프롬프트/렌더링 레벨에서 처리, 엔진 레벨에서는 데이터가 준비돼 있어야 함)
# ---------------------------------------------------------------------------
def test_spec_only_lookup_has_no_quote_but_full_spec_fact():
    result = analyze_named_equipment(["SPEC-001"])
    entry = result["equipment"][0]
    assert entry["found"] is True
    assert entry["candidate"].manufacturer == "OptiScan"
    assert entry["candidate"].equipment_fact.width_mm == 500.0
    # QUOTE-001.md가 실제로 존재하므로 quote_analyses도 채워진다(엔진은 항상 계산).
    assert len(entry["quote_analyses"]) == 1


def test_quote_analysis_exposes_required_minimum_fields():
    """요청서 5단계: 본체 금액/옵션 금액/추가 비용/할인/VAT/최종 금액/제외 항목/
    주요 확인사항을 최소한 추출할 수 있어야 한다."""
    result = analyze_named_equipment(["SPEC-001"])
    analysis = result["equipment"][0]["quote_analyses"][0]
    assert analysis.computed_equipment_amount > 0  # 본체 금액
    assert analysis.computed_options_amount >= 0  # 옵션 금액
    assert analysis.computed_additional_cost_amount >= 0  # 추가 비용
    assert analysis.computed_discount <= 0  # 할인(0 또는 음수)
    assert analysis.computed_grand_total is not None  # 최종 금액
    assert isinstance(analysis.quotation.excluded_items, list)  # 제외 항목
    assert analysis.is_calculation_consistent  # 주요 확인사항(계산 정합성)


def test_comparison_returns_both_equipment_with_independent_quotes():
    result = analyze_named_equipment(["SPEC-001", "SPEC-051"])
    assert len(result["equipment"]) == 2
    names = {e["candidate"].model for e in result["equipment"] if e["candidate"]}
    assert names == {"ES-200", "MI-800"}


# ---------------------------------------------------------------------------
# 13. 견적 없는 장비 처리
# ---------------------------------------------------------------------------
def test_equipment_with_no_quote_returns_empty_list_not_error():
    result = analyze_named_equipment(["SPEC-NONEXISTENT-999"])
    entry = result["equipment"][0]
    assert entry["found"] is False
    assert entry["quote_analyses"] == []


# ---------------------------------------------------------------------------
# 조건 + 견적 — 요구조건 기반 후보 선정에 견적 분석이 붙는지 (fake embedding, LLM 없음)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def indexed_db():
    """DB 빌드에만 fake embedding patch를 쓰고 즉시 해제한다 — patch를 yield까지
    걸쳐 두면(module scope) 이 파일에 함께 있는 real_rag 테스트가 실제 Ollama
    대신 fake 벡터를 쓰게 되는 사고가 난다(실제로 발견/수정한 버그 — 프로덕션
    chroma_db_specs는 bge-m3 1024차원인데 fake 벡터는 16차원이라 즉시 dimension
    mismatch로 드러났다). 각 fake-DB 의존 테스트는 자기 쿼리 시점에 직접
    `with patched_embeddings():`를 다시 연다(빌드와 검색 둘 다 patch 안에서
    실행돼야 한다는 patched_embeddings() 자체의 계약과 동일)."""
    with patched_embeddings():
        build_fake_embedding_db(TEST_DB_PATH)
    yield
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)


def test_condition_plus_quote_attaches_quote_analyses_to_candidates():
    requirement = RequirementSchema(
        raw_text="폭 800 mm 이상을 Inline으로 검사하고 두께와 표면결함을 모두 검사할 수 있는 장비 중 견적을 비교해줘.",
        target=RequirementTarget(width_mm=800.0),
        inline_offline="inline",
        inspection_items=["thickness", "surface_defect"],
    )
    with patched_embeddings(), _patched_llm_spec_generation():
        result = analyze_with_quotes(requirement, db_path=TEST_DB_PATH, k_per_query=100)

    assert result["candidates"], "조건에 맞는 후보가 하나도 없습니다"
    assert result["quote_analyses"], "후보들에 견적 분석이 하나도 연결되지 않았습니다"
    # 최소 한 후보는 실제로 계산이 정합적이어야 한다(전부 오류라면 로직 문제).
    any_consistent = any(
        all(a.is_calculation_consistent for a in analyses) for analyses in result["quote_analyses"].values()
    )
    assert any_consistent


def test_quote_comparison_across_candidates_shows_different_totals():
    """장비별 견적 비교: 서로 다른 후보의 Grand Total이 실제로 비교 가능한 숫자로
    나온다(하나로 뭉개지지 않음)."""
    requirement = RequirementSchema(
        raw_text="두께 검사가 가능한 장비를 찾아줘.",
        inspection_items=["thickness"],
    )
    with patched_embeddings(), _patched_llm_spec_generation():
        result = analyze_with_quotes(requirement, db_path=TEST_DB_PATH, k_per_query=100)

    grand_totals = {
        spec_id: [a.computed_grand_total for a in analyses]
        for spec_id, analyses in result["quote_analyses"].items()
    }
    assert len(grand_totals) >= 2, "비교할 후보 견적이 2개 미만입니다"
    flattened = [v for values in grand_totals.values() for v in values if v is not None]
    assert len(set(flattened)) > 1, "모든 후보의 Grand Total이 동일합니다(비교 무의미)"


# ---------------------------------------------------------------------------
# Real Ollama 전체 경로 스모크 테스트(선택적, Ollama 없으면 자동 SKIP)
# ---------------------------------------------------------------------------
@pytest.mark.real_rag
def test_real_ollama_condition_plus_quote_end_to_end():
    from tests import real_rag_lib as rag

    env = rag.check_ollama_environment()
    if not env.server_reachable:
        pytest.skip(f"Ollama 서버에 연결할 수 없습니다: {env.error}")
    if not env.embedding_model_installed:
        pytest.skip(f"embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")

    from agent.requirement_parser import parse_requirement_text

    text = "폭 800 mm 이상을 Inline으로 검사하고 두께와 표면결함을 모두 검사할 수 있는 장비 중 견적을 비교해줘."
    assert wants_quote_analysis(text) is True
    requirement = parse_requirement_text(text)
    result = analyze_with_quotes(requirement)
    assert result["chosen_candidate"] is not None
    assert result["chosen_candidate"].status == "PASS"
    assert result["quote_analyses"]
