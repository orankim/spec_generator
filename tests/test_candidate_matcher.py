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
from agent.schemas import (
    RequirementRange,
    RequirementSchema,
    RequirementTarget,
    RequirementValue,
    SourcedNumber,
    SpecificationSchema,
)
from agent.spec_generator import generate_specification
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
# Minimum Defect Size hard requirement — 실제 사용자 보고 버그 재현:
# "최소 검출 결함 크기"를 확인 질문으로 물어놓고도 candidate_matcher가 이를 전혀
# hard requirement로 평가하지 않아, 요구값(예: 2 μm)보다 훨씬 나쁜 실제 검출 성능
# (예: SPEC-005.md의 50 μm)을 가진 장비도 "조건을 모두 충족합니다"로 잘못 안내되었다.
# ---------------------------------------------------------------
def test_build_candidates_extracts_minimum_defect_size_from_table_row():
    requirement = RequirementSchema(minimum_defect_size=RequirementValue(value=30.0, unit="um", operator="<="))
    doc = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 30 μm |\n", filename="SPEC-001.md"
    )
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    results = {m.item: m for m in c.matches}
    assert results["Minimum Defect Size"].result == "PASS"
    assert results["Minimum Defect Size"].found_value == 30.0


def test_build_candidates_extracts_minimum_defect_size_from_bullet_list():
    """SPEC-002.md는 표가 아니라 불릿("- Minimum Detectable Defect: 5 μm")로 이 값을 적는다."""
    requirement = RequirementSchema(minimum_defect_size=RequirementValue(value=10.0, unit="um", operator="<="))
    doc = _mk_doc(
        "## Defect Inspection\n\n- Minimum Detectable Defect: 5 μm\n- Defect Types: Scratch, Pit, Particle\n",
        filename="SPEC-002.md",
    )
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    results = {m.item: m for m in c.matches}
    assert results["Minimum Defect Size"].result == "PASS"
    assert results["Minimum Defect Size"].found_value == 5.0


def test_build_candidates_marks_fail_when_defect_size_worse_than_required():
    """요구: 2μm까지 검출 가능해야 함. 장비: 50μm까지만 검출 가능(더 미세한 결함은 못 잡음) → FAIL."""
    requirement = RequirementSchema(minimum_defect_size=RequirementValue(value=2.0, unit="um", operator="<="))
    doc = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 50 μm |\n", filename="SPEC-005.md"
    )
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    results = {m.item: m for m in c.matches}
    assert results["Minimum Defect Size"].result == "FAIL"
    assert c.hard_requirements_pass is False


def test_build_candidates_defect_size_unknown_when_not_reported():
    requirement = RequirementSchema(minimum_defect_size=RequirementValue(value=2.0, unit="um", operator="<="))
    doc = _mk_doc("## Defect Inspection\n\n- Not Supported\n", filename="SPEC-003.md")
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    results = {m.item: m for m in c.matches}
    assert results["Minimum Defect Size"].result == "UNKNOWN"


def test_build_candidates_skips_defect_size_when_not_required():
    """사용자가 최소 검출 결함 크기를 요구하지 않았으면 애초에 평가 목록에 넣지 않는다(Range/Accuracy와 동일 원칙)."""
    requirement = RequirementSchema()
    doc = _mk_doc(
        "| Item | Specification |\n|---|---|\n| Minimum Detectable Defect | 50 μm |\n", filename="SPEC-005.md"
    )
    candidates = build_candidates(requirement, [doc])
    c = candidates[0]
    assert "Minimum Defect Size" not in {m.item for m in c.matches}


def test_reported_bug_spec_005_min_defect_size_2um_fails_hard_requirement(db):
    """
    Sample b (실사용자 보고): "음극 폭 300 mm의 두께와 3D 프로파일을 0~500 μm 범위에서
    ±2 μm 이하 정확도로 측정" + 최소 검출 결함 크기 2μm 요구 → 시스템이 LaserMetrix
    LP-500(SPEC-005.md, 실제 최소 검출 결함 크기 50μm)을 "Hard Requirement 조건을 모두
    충족합니다"로 안내했다. 이 테스트는 그 후보가 실제로는 Minimum Defect Size에서
    FAIL로 판정되어야 함을 검증한다.
    """
    requirement = RequirementSchema(
        target=RequirementTarget(material="음극", width_mm=300),
        inspection_items=["thickness", "profile_3d"],
        measurement_range=RequirementRange(min=0.0, max=500.0, unit="um"),
        accuracy=RequirementValue(value=2.0, unit="um", operator="<="),
        required_accuracy_um=2.0,
        minimum_defect_size=RequirementValue(value=2.0, unit="um", operator="<="),
        minimum_defect_size_um=2.0,
    )
    # fake-hash 임베딩은 의미 유사도를 반영하지 않으므로, k_per_query를 작게 두면
    # SPEC-005.md의 "Defect Inspection" chunk가 우연히 top-k 밖으로 밀려날 수 있다 —
    # corpus 전체 chunk 수(84개)보다 크게 잡아 모든 chunk가 확실히 포함되게 한다
    # (실제 서비스에서는 bge-m3 실제 임베딩을 쓰므로 k_per_query=5로도 충분하다).
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=100)
    candidates = build_candidates(requirement, retrieved_docs)
    spec005 = next((c for c in candidates if c.source_document == "SPEC-005.md"), None)
    assert spec005 is not None, "SPEC-005.md 후보가 만들어지지 않았습니다"

    defect_match = next(m for m in spec005.matches if m.item == "Minimum Defect Size")
    assert defect_match.result == "FAIL", "50um 최소 검출 결함 크기는 2um 요구조건을 충족하지 못해야 한다"
    assert spec005.hard_requirements_pass is False


def test_spec_generator_applies_equipment_minimum_defect_size_from_chosen_candidate(db):
    """generate_specification()이 선택된 후보(SPEC-005.md)의 실제 최소 검출 결함 크기를
    spec.defect_detection.equipment_minimum_defect_size_um에 VERIFIED+source로 채우고,
    build_hard_requirement_report가 이를 근거로 FAIL을 보고하는지 검증한다."""
    requirement = RequirementSchema(
        target=RequirementTarget(material="음극", width_mm=300),
        inspection_items=["thickness", "profile_3d"],
        measurement_range=RequirementRange(min=0.0, max=500.0, unit="um"),
        accuracy=RequirementValue(value=2.0, unit="um", operator="<="),
        required_accuracy_um=2.0,
        minimum_defect_size=RequirementValue(value=2.0, unit="um", operator="<="),
        minimum_defect_size_um=2.0,
    )
    fake_llm_response = SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=db, k_per_query=100)

    assert specification.equipment.name == "LaserMetrix LP-500"

    eq_defect = specification.defect_detection.equipment_minimum_defect_size_um
    assert eq_defect is not None
    assert eq_defect.value == 50.0
    assert eq_defect.status == "VERIFIED"
    assert eq_defect.source.document == "SPEC-005.md"

    # 사용자가 요구한 값(보호된 필드)은 여전히 별도로 남아 있어야 한다 — 요구값/실측값 혼동 방지.
    assert specification.defect_detection.minimum_defect_size_um.value == 2.0
    assert specification.defect_detection.minimum_defect_size_um.status == "USER_DEFINED"

    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Minimum Defect Size"].result == "FAIL"
    assert by_item["Minimum Defect Size"].specification == 50.0
    assert by_item["Minimum Defect Size"].requirement == 2.0


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


# ---------------------------------------------------------------
# Reconciliation 테스트 (요청서 Test 1~4): "Hard Requirement PASS인데 measurement_range는
# INFERRED"라는 모순이 다시 발생하지 않는지 검증한다.
#
# 실제 관찰된 버그: LLM이 measurement_performance.measurement_range(레거시 단일값
# SourcedNumber)를 채우면서 범위의 하한("0")을 VERIFIED로 주장하는 경우가 있었다.
# "0 ~ 200 μm" 원문에는 "0"이 단위와 바로 붙어 나오지 않으므로(항상 "~200 μm"로만
# 등장) _verify_sourced_numbers가 이 값을 확인하지 못해 INFERRED로 강등시켰다 — 하지만
# candidate_matcher는 같은 문서에서 범위 전체(0~200)를 올바르게 추출해 Hard
# Requirement를 PASS로 판정했으므로, 최종 결과에 "PASS인데 INFERRED"라는 모순이
# 남아 있었다.
# ---------------------------------------------------------------
def test_reconciliation_1_pass_range_reconciles_legacy_field_to_verified(db):
    """
    Test 1: 사용자 요구 0~200 μm, 문서(SPEC-001.md) 0~200 μm → PASS.
    LLM이 legacy measurement_range를 검증 불가능한 값(범위의 하한 "0")으로 잘못
    채워도, Hard Requirement가 PASS로 확정한 값으로 재조정(VERIFIED)되어야 한다.
    """
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    context_text = spec_retriever.format_context(retrieved_docs)

    fake_llm_response = SpecificationSchema()
    fake_llm_response.measurement_performance.measurement_range = SourcedNumber(
        value=0.0, unit="um", status="VERIFIED"
    )

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        spec = generate_specification(requirement, retrieved_docs, context_text, model="test-model")

    mr = spec.measurement_performance.measurement_range
    assert mr.status == "VERIFIED"
    assert mr.source is not None and mr.source.document == "SPEC-001.md"

    mrf = spec.measurement_performance.measurement_range_full
    assert mrf.status == "VERIFIED"
    assert mrf.source.document == "SPEC-001.md"

    assert "measurement_performance.measurement_range" not in spec.needs_confirmation

    hard_report = build_hard_requirement_report(spec, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Measurement Range"].result == "PASS"


def test_reconciliation_2_fail_range_does_not_force_verified():
    """
    Test 2: 사용자 요구 0~200 μm, 문서 0~100 μm → FAIL. 이 경우 measurement_range를
    VERIFIED로 확정하면 안 된다 — Hard Requirement가 충족하지 못한 값을 "요구사항을
    만족하는 확정값"처럼 보여주지 않기 위함이다. 다만 measurement_range_full(장비의
    실제 확인된 범위, PASS/FAIL 판정과는 별개의 "무엇을 찾았는가" 정보)은 여전히
    VERIFIED로 채워져야 Hard Requirement Report가 실제 근거로 FAIL 사유를 보여줄
    수 있다 — measurement_range_full까지 비워버리면 FAIL 사유 자체가 UNKNOWN이 되어
    버린다(회귀: 처음 구현에서 실제로 이 문제가 발생해 여기서 함께 검증한다).
    """
    requirement = RequirementSchema(measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"))
    narrow_doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 100 μm |\n",
        metadata={"filename": "NARROW.md", "source": "NARROW.md", "source_type": "markdown", "chunk_id": 0},
    )
    fake_llm_response = SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        spec = generate_specification(requirement, [narrow_doc], "", model="test-model")

    # 레거시 필드(needs_confirmation/validator가 검사하는 필드)는 FAIL인 값으로
    # VERIFIED가 되면 안 된다.
    assert (
        spec.measurement_performance.measurement_range is None
        or spec.measurement_performance.measurement_range.status != "VERIFIED"
    )

    # measurement_range_full은 "실제로 찾은 값"이므로 여전히 채워져야 한다(FAIL 사유의 근거).
    mrf = spec.measurement_performance.measurement_range_full
    assert mrf is not None
    assert mrf.min == 0.0 and mrf.max == 100.0
    assert mrf.source.document == "NARROW.md"

    hard_report = build_hard_requirement_report(spec, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Measurement Range"].result == "FAIL"


def test_reconciliation_3_accuracy_pass_reconciles_equipment_field_to_verified():
    """Test 3: 요구 정확도 <= 1μm, 문서 정확도 ±1.0μm → PASS → equipment_accuracy_um VERIFIED + source."""
    requirement = RequirementSchema(accuracy=RequirementValue(value=1.0, unit="um", operator="<="), required_accuracy_um=1.0)
    doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Accuracy | ±1.0 μm |\n",
        metadata={"filename": "SPEC-001.md", "source": "SPEC-001.md", "source_type": "markdown", "chunk_id": 2},
    )
    fake_llm_response = SpecificationSchema()

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        spec = generate_specification(requirement, [doc], "", model="test-model")

    eq_acc = spec.measurement_performance.equipment_accuracy_um
    assert eq_acc is not None
    assert eq_acc.value == 1.0
    assert eq_acc.status == "VERIFIED"
    assert eq_acc.source is not None
    assert eq_acc.source.document == "SPEC-001.md"


def test_reconciliation_4_full_reported_query_end_to_end(db):
    """
    Test 4: 사용자가 실제로 보고한 정확한 질문에 대해 파이프라인(retrieve_and_generate)
    최종 결과를 검증한다. LLM이 legacy measurement_range를 검증 불가능한 값(0)으로
    채우는 실제 관찰된 시나리오를 재현해, 최종 결과에서 모순이 사라졌는지 확인한다.
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
    fake_llm_response.measurement_performance.measurement_range = SourcedNumber(
        value=0.0, unit="um", status="VERIFIED"
    )

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=db)

    assert specification.equipment.name == "OptiScan ES-200"

    mr = specification.measurement_performance.measurement_range
    assert mr.value == 200.0
    assert mr.status == "VERIFIED"
    assert mr.source.document == "SPEC-001.md"

    mrf = specification.measurement_performance.measurement_range_full
    assert mrf.min == 0.0 and mrf.max == 200.0
    assert mrf.status == "VERIFIED"
    assert mrf.source.document == "SPEC-001.md"

    assert requirement.required_accuracy_um == 1.0
    eq_acc = specification.measurement_performance.equipment_accuracy_um
    assert eq_acc.value == 1.0
    assert eq_acc.status == "VERIFIED"
    assert eq_acc.source.document == "SPEC-001.md"

    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"

    assert "measurement_performance.measurement_range" not in specification.needs_confirmation
    assert "measurement_performance.equipment_accuracy_um" not in specification.needs_confirmation
    assert validation.is_valid is True
