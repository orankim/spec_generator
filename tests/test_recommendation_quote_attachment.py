"""
견적 통합 개선 — 추천 장비 결과에 QUOTE 데이터가 연결되는 방식 자체를 검증한다.

agent/routes.py::generate_spec_api가 이제 quote_intent(견적 키워드) 유무와
무관하게 매번 agent.pipeline.attach_quote_analyses(candidates)를 호출한다
(이전에는 wants_quote_analysis(raw_text)가 True일 때만 호출했다 — 그래서
"장비 찾아줘"처럼 견적 키워드가 없는 일반 질문에서는 실제로 연결된 QUOTE가
있어도 화면에 전혀 나타나지 않는 버그가 있었다).

이 파일은 그 연결 함수 자체를 Ollama/RAG 없이 순수하게 검증한다:
  1. 실제로 연결된 QUOTE가 있으면 채워진다.
  2. 연결된 QUOTE가 없는 후보는 가격을 지어내지 않고 결과에서 빠진다.
  3. 서로 다른 후보(SPEC 문서)의 견적이 절대 섞이지 않는다(장비 A -> 장비 B
     견적 금지, 요청서 10/13단계).
"""
from __future__ import annotations

from agent.pipeline import attach_quote_analyses
from agent.schemas import CandidateEquipment


def _candidate(spec_id: str, candidate_id: str) -> CandidateEquipment:
    return CandidateEquipment(candidate_id=candidate_id, source_document=f"{spec_id}.md", status="PASS")


def test_candidate_with_linked_quote_gets_quote_analyses():
    candidates = [_candidate("SPEC-001", "c1")]
    result = attach_quote_analyses(candidates)
    assert "SPEC-001.md" in result
    assert result["SPEC-001.md"][0].computed_grand_total is not None


def test_candidate_without_linked_quote_is_absent_no_price_fabricated():
    """SPEC-999는 sample_specs/sample_quotes 어디에도 존재하지 않는 가짜 번호다 —
    연결된 QUOTE 파일이 없으므로 결과 dict에 키 자체가 없어야 한다(빈 리스트로
    채우지도, 가격을 추측해서 채우지도 않는다)."""
    candidates = [_candidate("SPEC-999", "c1")]
    result = attach_quote_analyses(candidates)
    assert "SPEC-999.md" not in result


def test_mixed_candidates_only_the_ones_with_real_quotes_appear():
    candidates = [_candidate("SPEC-001", "c1"), _candidate("SPEC-999", "c2"), _candidate("SPEC-011", "c3")]
    result = attach_quote_analyses(candidates)
    assert set(result.keys()) == {"SPEC-001.md", "SPEC-011.md"}


def test_no_cross_contamination_across_different_recommended_candidates():
    """장비 A(SPEC-001, ES-200)의 견적 자리에 장비 B(SPEC-011, TP-200)의 견적이
    들어가는 일이 없어야 한다 — 그리고 그 반대도 마찬가지다."""
    candidates = [_candidate("SPEC-001", "c1"), _candidate("SPEC-011", "c2")]
    result = attach_quote_analyses(candidates)

    spec001_quote = result["SPEC-001.md"][0].quotation
    spec011_quote = result["SPEC-011.md"][0].quotation

    assert spec001_quote.source_file.startswith("QUOTE-001")
    assert spec011_quote.source_file.startswith("QUOTE-011")
    assert spec001_quote.general.model == "ES-200"
    assert spec011_quote.general.model == "TP-200"
    assert spec001_quote.source_file != spec011_quote.source_file


def test_empty_candidate_list_returns_empty_dict_without_error():
    assert attach_quote_analyses([]) == {}
