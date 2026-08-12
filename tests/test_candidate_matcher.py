"""
CandidateMatcher(agent.candidate_matcher) + Hard Requirement 평가
(agent.units.evaluate_hard_requirements)에 대한 테스트.

요청서의 A~H 테스트 항목을 그대로 구현한다:
  A/B/C. 측정 범위(요구 0~200) vs 장비 범위(0~200/0~100/0~300) PASS/FAIL
  D/E.   정확도(요구 1.0) vs 장비 정확도(0.5/2.0) PASS/FAIL
  F.     실제 SPEC-001.md로 사용자가 보고한 질문에 대해 hard requirement PASS 검증
  G.     최종 생성 결과의 각 필드(equipment.name/measurement_range/accuracy)가
         실제 source.document(SPEC-001.md)로 연결되는지 검증
  H.     사용자 요구값과 장비 실제값이 API 응답에서 명확히 구분되는지 검증

LLM 판단이 전혀 개입하지 않는 부분(A~E, 후보 추출/판정)은 순수 함수 테스트로,
RAG가 필요한 부분(F~H)은 fake-embedding 패턴(다른 테스트 파일과 동일)으로 검증한다.
"""
import hashlib
import shutil
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document

from agent import spec_retriever
from agent.candidate_matcher import build_candidates, select_best_candidate
from agent.pipeline import retrieve_and_generate
from agent.schemas import RequirementRange, RequirementSchema, RequirementTarget, RequirementValue, SpecificationSchema
from agent.spec_validator import build_hard_requirement_report
from agent.units import evaluate_hard_requirements
from build_rag_ollama import build_vector_db

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_DB = "./_test_chroma_db_candidate_matcher"
_REPORTED_QUERY = "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."


def _fake_vector(text: str, dim: int = 32):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    arr = np.frombuffer((h * (dim // len(h) + 1))[: dim * 4], dtype=np.uint32).astype(np.float64)
    return (arr / arr.max()).tolist()


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with mock.patch.object(OllamaEmbeddings, "embed_documents", lambda self, texts: [_fake_vector(t) for t in texts]), \
         mock.patch.object(OllamaEmbeddings, "embed_query", lambda self, text: _fake_vector(text)):
        yield


@pytest.fixture(scope="module")
def db(fake_embeddings):
    shutil.rmtree(_TEST_DB, ignore_errors=True)
    build_vector_db("sample_specs", _TEST_DB, rebuild=True)
    yield _TEST_DB
    shutil.rmtree(_TEST_DB, ignore_errors=True)


def _mk_doc(text: str, filename: str = "DOC.md") -> Document:
    return Document(page_content=text, metadata={"filename": filename, "source": filename, "source_type": "markdown"})


# ---------------------------------------------------------------
# A/B/C. 측정 범위 PASS/FAIL — agent.units.evaluate_hard_requirements
# ---------------------------------------------------------------
def test_A_range_equal_to_required_passes():
    ok, reasons = evaluate_hard_requirements(required_range=(0.0, 200.0, "um"), candidate_range=(0.0, 200.0, "um"))
    assert ok is True
    assert reasons == []


def test_B_range_narrower_than_required_fails():
    ok, reasons = evaluate_hard_requirements(required_range=(0.0, 200.0, "um"), candidate_range=(0.0, 100.0, "um"))
    assert ok is False
    assert any("측정 범위" in r for r in reasons)


def test_C_range_wider_than_required_passes():
    ok, reasons = evaluate_hard_requirements(required_range=(0.0, 200.0, "um"), candidate_range=(0.0, 300.0, "um"))
    assert ok is True
    assert reasons == []


# ---------------------------------------------------------------
# D/E. 정확도 PASS/FAIL
# ---------------------------------------------------------------
def test_D_accuracy_better_than_required_passes():
    ok, reasons = evaluate_hard_requirements(required_accuracy=(1.0, "um", "<="), candidate_accuracy=(0.5, "um"))
    assert ok is True
    assert reasons == []


def test_E_accuracy_worse_than_required_fails():
    ok, reasons = evaluate_hard_requirements(required_accuracy=(1.0, "um", "<="), candidate_accuracy=(2.0, "um"))
    assert ok is False
    assert any("정확도" in r for r in reasons)


# ---------------------------------------------------------------
# build_candidates() 자체의 표(테이블) 추출 + PASS/FAIL 종합 판정
# ---------------------------------------------------------------
def test_build_candidates_extracts_range_and_accuracy_from_table_and_marks_pass():
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    doc = _mk_doc(
        "## General\n\n- Manufacturer: OptiScan\n- Model: ES-200\n\n"
        "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
        "| Measurement Range (Z) | 0 ~ 200 μm |\n| Accuracy | ±1.0 μm |\n",
        filename="SPEC-001.md",
    )
    candidates = build_candidates(requirement, [doc])
    assert len(candidates) == 1
    c = candidates[0]
    assert c.manufacturer == "OptiScan"
    assert c.model == "ES-200"
    assert c.hard_requirements_pass is True
    assert c.pass_count == 2
    assert c.fail_count == 0
    results = {m.item: m.result for m in c.matches}
    assert results["Measurement Range"] == "PASS"
    assert results["Accuracy"] == "PASS"


def test_build_candidates_marks_fail_for_narrower_range():
    requirement = RequirementSchema(measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"))
    doc = _mk_doc("| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 100 μm |\n", filename="SPEC-X.md")
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    assert c.hard_requirements_pass is False
    assert c.matches[0].result == "FAIL"


def test_select_best_candidate_prefers_passing_over_failing():
    requirement = RequirementSchema(measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"))
    passing = _mk_doc("| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 300 μm |\n", filename="PASS.md")
    failing = _mk_doc("| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 100 μm |\n", filename="FAIL.md")
    candidates = build_candidates(requirement, [failing, passing])
    best = select_best_candidate(candidates)
    assert best.source_document == "PASS.md"
    assert best.hard_requirements_pass is True


def test_select_best_candidate_returns_none_for_empty_list():
    assert select_best_candidate([]) is None


# ---------------------------------------------------------------
# F. 실제 SPEC-001.md로 사용자가 보고한 질문에 대해 hard requirement PASS 검증
# ---------------------------------------------------------------
def test_F_spec_001_passes_hard_requirement_for_reported_query(db):
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    candidates = build_candidates(requirement, retrieved_docs)
    spec001 = next((c for c in candidates if c.source_document == "SPEC-001.md"), None)
    assert spec001 is not None, "SPEC-001.md 후보가 만들어지지 않았습니다"
    assert spec001.hard_requirements_pass is True, [m.result for m in spec001.matches]

    best = select_best_candidate(candidates)
    assert best is not None
    assert best.source_document == "SPEC-001.md"
    assert best.hard_requirements_pass is True


# ---------------------------------------------------------------
# G. 최종 생성 결과에서 equipment.name/measurement_range/accuracy 각각이
#    source.document=SPEC-001.md로 연결되는지 검증
# ---------------------------------------------------------------
def test_G_final_specification_links_each_field_to_spec_001(db):
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    fake_llm_response = SpecificationSchema()  # LLM은 아무것도 채우지 않았다고 가정 — 후보 매칭이 전부 채워야 함

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=db)

    assert specification.equipment.name == "OptiScan ES-200"

    range_full = specification.measurement_performance.measurement_range_full
    assert range_full is not None
    assert range_full.min == 0.0
    assert range_full.max == 200.0
    assert range_full.status == "VERIFIED"
    assert range_full.source is not None
    assert range_full.source.document == "SPEC-001.md"

    equipment_accuracy = specification.measurement_performance.equipment_accuracy_um
    assert equipment_accuracy is not None
    assert equipment_accuracy.value == 1.0
    assert equipment_accuracy.status == "VERIFIED"
    assert equipment_accuracy.source.document == "SPEC-001.md"

    assert "SPEC-001.md" in specification.primary_sources

    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"


# ---------------------------------------------------------------
# H. 사용자 요구값과 장비 실제값이 API 응답 레벨에서 명확히 구분되는지 검증
# ---------------------------------------------------------------
def test_H_required_value_and_equipment_value_are_distinct_in_api_response(db):
    """
    회귀: 이전에는 measurement_performance.accuracy_um이 사용자 요구값으로 고정되어
    "정확도: 1 μm (사용자 요구사항)"만 보이고 장비의 실제 정확도와 구분되지 않았다.
    이제 requirement.accuracy(요구값)와 specification.measurement_performance.
    equipment_accuracy_um(장비 실측값)이 서로 다른 필드로 명확히 분리되어야 한다.
    """
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    fake_llm_response = SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=db)

    # 요구값(사용자 입력) — accuracy_um은 여전히 prefill로 보호되는 "요구값" 필드다.
    assert specification.measurement_performance.accuracy_um.value == 1.0
    assert specification.measurement_performance.accuracy_um.status == "USER_DEFINED"

    # 장비 실측값 — 별도 필드(equipment_accuracy_um)에 SPEC-001.md 근거로 채워진다.
    assert specification.measurement_performance.equipment_accuracy_um.value == 1.0
    assert specification.measurement_performance.equipment_accuracy_um.status == "VERIFIED"
    assert specification.measurement_performance.equipment_accuracy_um.source.document == "SPEC-001.md"

    # 두 필드는 서로 다른 필드이지 같은 필드를 재사용한 것이 아니다.
    assert specification.measurement_performance.accuracy_um is not specification.measurement_performance.equipment_accuracy_um
