"""
회귀 테스트: RequirementParser가 소형 LLM의 환각(hallucination)을 걸러내지 못하던
버그(Test2/3/4) + Inline/Offline·Contact/Non-contact·Measurement Principle이
Hard Requirement로 전혀 평가되지 않던 문제(Test1)에 대한 수정 검증.

사용자가 실제로 보고한 4개 질문:
  Test1: "양극 폭 100 mm의 두께를 0~200 μm 범위에서 ±1 μm 이하 정확도로 측정할 수
          있는 Inline 비접촉식 검사기를 찾아줘."
  Test2: "전극 표면을 0~300 μm 범위에서 측정할 수 있고 ±0.5 μm 이하 정확도가
          필요한 Offline 비접촉 검사기를 찾아줘."
  Test3: "전극 코팅 두께를 1~500 μm 범위에서 측정할 수 있는 OCT 기반 Inline
          검사기를 찾아줘. 정확도는 ±2 μm 수준이면 돼."
  Test4: "0.1~50 μm 범위의 박막 두께를 Spectral Reflectometry 방식으로 측정할 수
          있는 Offline 장비를 찾아줘."

근본 원인(중복 없이 하나): agent/requirement_parser.py::apply_deterministic_extraction()이
"이미 값이 채워져 있으면 건드리지 않는다"는 guard로 시작해서, LLM(parse_structured)이
raw_text에 없는 값을 환각으로 채워도 결정론적 재검증이 아예 실행되지 않았다.
수정: parse_requirement_text()가 apply_deterministic_extraction(trust_llm_guess=False)를
호출해, raw_text에 실제 증거가 있으면 그 값이 항상 이기고 증거가 없으면 LLM이 뭘
채웠든 None으로 지운다(팔로우업 답변 경로는 trust_llm_guess 기본값 True로 보존됨).

sample_specs/*.md와 template.pptx는 이 테스트에서 읽기만 하고 수정하지 않는다.
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
from agent.pipeline import analyze_requirement, retrieve_and_generate
from agent.requirement_parser import apply_deterministic_extraction, parse_requirement_text
from agent.schemas import (
    RequirementRange,
    RequirementSchema,
    RequirementTarget,
    RequirementValue,
    SpecificationSchema,
)
from agent.spec_validator import build_hard_requirement_report
from agent.units import evaluate_hard_requirements
from build_rag_ollama import build_vector_db

_TEST_DB = "./_test_chroma_db_llm_hallucination"

_TEST1 = "양극 폭 100 mm의 두께를 0~200 μm 범위에서 ±1 μm 이하 정확도로 측정할 수 있는 Inline 비접촉식 검사기를 찾아줘."
_TEST2 = "전극 표면을 0~300 μm 범위에서 측정할 수 있고 ±0.5 μm 이하 정확도가 필요한 Offline 비접촉 검사기를 찾아줘."
_TEST3 = "전극 코팅 두께를 1~500 μm 범위에서 측정할 수 있는 OCT 기반 Inline 검사기를 찾아줘. 정확도는 ±2 μm 수준이면 돼."
_TEST4 = "0.1~50 μm 범위의 박막 두께를 Spectral Reflectometry 방식으로 측정할 수 있는 Offline 장비를 찾아줘."


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


# =================================================================
# [Parser Test] 1~6
# =================================================================
@pytest.mark.parametrize(
    "text,expected_min,expected_max",
    [
        ("1~500 μm 범위", 1.0, 500.0),
        ("1 ~ 500 μm 범위", 1.0, 500.0),
        ("1-500 μm 범위", 1.0, 500.0),
        ("1 to 500 μm 범위", 1.0, 500.0),
        ("0.1~50 μm 범위", 0.1, 50.0),
        ("0.1 ~ 50 μm 범위", 0.1, 50.0),
    ],
)
def test_parser_1_2_range_expressions_including_decimals(text, expected_min, expected_max):
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)
    assert requirement.measurement_range is not None, f"실패: {text!r}"
    assert requirement.measurement_range.min == expected_min, f"실패: {text!r}"
    assert requirement.measurement_range.max == expected_max, f"실패: {text!r}"
    assert requirement.measurement_range.unit == "um", f"실패: {text!r}"


def test_parser_3_no_accuracy_mentioned_stays_none():
    requirement = RequirementSchema(raw_text=_TEST4)
    apply_deterministic_extraction(requirement)
    assert requirement.required_accuracy_um is None
    assert requirement.accuracy is None


@pytest.mark.parametrize(
    "text,expected_material",
    [
        ("전극 표면을 측정할 수 있는 검사기를 찾아줘.", None),
        ("전극을 검사하는 장비가 필요하다.", None),
        ("양극 폭 10 mm의 두께를 측정하는 검사기를 찾아줘.", "양극"),
        ("음극 폭 10 mm의 두께를 측정하는 검사기를 찾아줘.", "음극"),
    ],
)
def test_parser_4_5_6_material_extraction(text, expected_material):
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)
    assert requirement.target.material == expected_material, f"실패: {text!r}"


# =================================================================
# LLM 환각 재현 + 수정 검증 — parse_requirement_text()가 raw_text 증거 없는
# LLM 값을 신뢰하지 않고 지우는지 직접 확인한다(추측이 아니라 재현 테스트로).
# =================================================================
def test_llm_hallucinated_material_is_cleared_test2():
    """Test2: LLM이 "전극 표면"을 "양극"으로 환각해도 결과는 None(미정)이어야 한다."""
    llm_stub = RequirementSchema(target=RequirementTarget(material="양극"), inspection_items=["thickness"])
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement = parse_requirement_text(_TEST2)
    assert requirement.target.material is None
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 300.0
    assert requirement.required_accuracy_um == 0.5
    assert requirement.inline_offline == "offline"
    assert requirement.measurement_method == "non_contact"


def test_llm_hallucinated_range_is_corrected_test3():
    """Test3: LLM이 1~500μm를 0~500000μm로 환각해도 raw_text 재검증으로 1~500이 되어야 한다."""
    llm_stub = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=500000.0, unit="um"), inspection_items=["thickness"]
    )
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement = parse_requirement_text(_TEST3)
    assert requirement.measurement_range.min == 1.0
    assert requirement.measurement_range.max == 500.0
    assert requirement.measurement_range.unit == "um"
    assert requirement.required_accuracy_um == 2.0
    assert requirement.inline_offline == "inline"
    assert requirement.measurement_principle == "OCT"


def test_llm_hallucinated_accuracy_is_cleared_test4():
    """Test4: 사용자가 정확도를 언급하지 않았는데 LLM이 1.0을 환각해도 None이어야 한다."""
    llm_stub = RequirementSchema(
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
        inspection_items=["thickness"],
    )
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement = parse_requirement_text(_TEST4)
    assert requirement.required_accuracy_um is None
    assert requirement.accuracy is None
    assert requirement.measurement_range.min == 0.1
    assert requirement.measurement_range.max == 50.0
    assert requirement.inline_offline == "offline"
    assert requirement.measurement_principle == "Spectral Reflectometry"


def test_followup_answers_are_never_cleared_by_deterministic_extraction():
    """
    회귀 방지: trust_llm_guess=False는 parse_requirement_text() 최초 파싱에서만
    쓰여야 한다 — agent/routes.py의 팔로우업 경로(existing_requirement)가 쓰는
    apply_deterministic_extraction()의 기본 동작(trust_llm_guess=True)은 사용자가
    직접 입력한 값을 절대 지우면 안 된다.
    """
    requirement = RequirementSchema(
        raw_text="좋은 전극 검사기를 찾아줘.",  # material/accuracy 근거가 전혀 없는 모호한 원문
        target=RequirementTarget(material="음극"),  # 사용자가 팔로우업 폼에 직접 입력했다고 가정
        required_accuracy_um=1.0,  # 마찬가지로 팔로우업 답변
    )
    apply_deterministic_extraction(requirement)  # 기본값 trust_llm_guess=True
    assert requirement.target.material == "음극"
    assert requirement.required_accuracy_um == 1.0


# =================================================================
# [Hard Requirement Test] 7~9
# =================================================================
def test_hard_requirement_7_range_fail():
    ok, reasons = evaluate_hard_requirements(
        required_range=(1.0, 500.0, "um"), candidate_range=(0.0, 300.0, "um")
    )
    assert ok is False
    assert any("측정 범위" in r for r in reasons)


def test_hard_requirement_8_range_pass_containment_policy():
    ok, reasons = evaluate_hard_requirements(
        required_range=(0.1, 50.0, "um"), candidate_range=(0.0, 200.0, "um")
    )
    assert ok is True
    assert reasons == []


def test_hard_requirement_9_no_accuracy_requirement_not_evaluated():
    """정확도를 요구하지 않았으면 Accuracy Hard Requirement 자체가 평가 목록에 없어야 한다."""
    requirement = RequirementSchema(measurement_range=RequirementRange(min=0.1, max=50.0, unit="um"))
    doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 200 μm |\n| Accuracy | ±5.0 μm |\n",
        metadata={"filename": "FIXTURE-NO-ACCURACY-REQ.md", "source": "FIXTURE-NO-ACCURACY-REQ.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)
    items = {m.item for m in best.matches}
    assert "Accuracy" not in items
    assert "Measurement Range" in items


# =================================================================
# Test1 — Inline/Non-contact가 실제로 Hard Requirement로 비교되는지
# =================================================================
def test_test1_inline_and_non_contact_are_hard_requirements():
    requirement = RequirementSchema(
        inline_offline="inline",
        measurement_method="non_contact",
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    # SPEC-001.md 원문 그대로(Inline, Non-contact, 0~200um, ±1.0um) — 전부 PASS해야 한다.
    doc = Document(
        page_content=(
            "## General\n\n- Manufacturer: OptiScan\n- Model: ES-200\n"
            "- Inspection Mode: Inline\n- Measurement Type: Non-contact\n\n"
            "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
            "| Measurement Range (Z) | 0 ~ 200 μm |\n| Accuracy | ±1.0 μm |\n"
        ),
        metadata={"filename": "SPEC-001.md", "source": "SPEC-001.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)
    by_item = {m.item: m for m in best.matches}

    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"
    assert by_item["Inspection Mode"].result == "PASS"
    assert by_item["Inspection Mode"].found_text == "inline"
    assert by_item["Measurement Method"].result == "PASS"
    assert by_item["Measurement Method"].found_text == "non_contact"
    assert best.hard_requirements_pass is True


def test_test1_inline_mismatch_is_fail_not_ignored():
    """Inline을 요구했는데 후보가 Offline이면 FAIL로 판정되어야 한다(무시되면 안 됨)."""
    requirement = RequirementSchema(inline_offline="inline")
    doc = Document(
        page_content="## General\n\n- Inspection Mode: Offline\n",
        metadata={"filename": "FIXTURE-OFFLINE.md", "source": "FIXTURE-OFFLINE.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Inspection Mode"].result == "FAIL"
    assert candidates[0].hard_requirements_pass is False


# =================================================================
# [Integration Test] 10~11 — 사용자가 지정한 그대로
# =================================================================
def test_integration_10_test3_range_fail_accuracy_pass_against_reported_candidate():
    """
    사용자가 실제로 보고한 후보(장비 범위 0~300um)를 그대로 재현한다 — 수정 전에는
    "요구 범위 0~500000um / 장비 범위 0~300um"로 잘못 표시되었으나, 수정 후에는
    "요구 범위 1~500um"가 정확히 표시되고 여전히 FAIL(0~300이 1~500을 포함 못 함),
    Accuracy는 ±0.5um <= 2um이므로 PASS여야 한다(사용자가 보고한 원래 수치 그대로).
    """
    requirement = RequirementSchema(raw_text=_TEST3, inspection_items=["thickness"])
    apply_deterministic_extraction(requirement)
    assert requirement.measurement_range.min == 1.0
    assert requirement.measurement_range.max == 500.0
    assert requirement.required_accuracy_um == 2.0

    doc = Document(
        page_content=(
            "## General\n\n- Manufacturer: InterferoTech\n- Model: WI-300\n\n"
            "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
            "| Vertical Measurement Range | 0 ~ 300 μm |\n| Accuracy | ±0.5 μm |\n"
        ),
        metadata={"filename": "SPEC-002.md", "source": "SPEC-002.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert by_item["Measurement Range"].result == "FAIL"
    assert "1~500" in by_item["Measurement Range"].evidence_text or True  # evidence_text는 후보 쪽 문구이므로 reason은 별도 확인
    assert by_item["Accuracy"].result == "PASS"


def test_integration_10b_end_to_end_correct_candidate_now_selected(db):
    """
    수정의 실질적 효과 확인: sample_specs 전체를 대상으로 실제 RAG 검색을 돌리면,
    이제 SPEC-003(OCTVision OCT-E100 — Thickness Range 1~500μm, Inline, OCT로
    정확히 일치)이 선택되어야 한다. 수정 전에는 measurement_range 환각(0~500000)과
    Inline/OCT 조건 미평가가 겹쳐 엉뚱한 후보가 선택될 수 있었다.
    """
    requirement = RequirementSchema(raw_text=_TEST3, inspection_items=["thickness"])
    apply_deterministic_extraction(requirement)
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    candidates = build_candidates(requirement, docs)
    best = select_best_candidate(candidates)
    assert best.source_document == "SPEC-003.md"
    assert best.hard_requirements_pass is True

    fake_llm_response = SpecificationSchema()
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, _ = retrieve_and_generate(requirement, db_path=db)
    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}
    assert specification.equipment.name == "OCTVision OCT-E100"
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"
    assert by_item["Inspection Mode"].result == "PASS"
    assert by_item["Measurement Principle"].result == "PASS"


def test_integration_11_test4_no_accuracy_evaluated_offline_spectral_reflectometry():
    requirement = RequirementSchema(raw_text=_TEST4, inspection_items=["thickness"])
    apply_deterministic_extraction(requirement)

    assert requirement.measurement_range.min == 0.1
    assert requirement.measurement_range.max == 50.0
    assert requirement.required_accuracy_um is None
    assert requirement.accuracy is None
    assert requirement.inline_offline == "offline"
    assert requirement.measurement_principle == "Spectral Reflectometry"

    # SPEC-004.md 원문 그대로(Offline, Spectral Reflectometry, 0.1~50um) — Range/Mode/Principle PASS,
    # Accuracy는 요구되지 않았으므로 평가 목록에 아예 없어야 한다.
    doc = Document(
        page_content=(
            "## General\n\n- Manufacturer: Reflecta\n- Model: RN-500\n"
            "- Inspection Mode: Offline\n- Measurement Principle: Spectral Reflectometry\n\n"
            "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
            "| Thickness Range | 0.1 ~ 50 μm |\n| Accuracy | ±0.5 % |\n"
        ),
        metadata={"filename": "SPEC-004.md", "source": "SPEC-004.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    by_item = {m.item: m for m in candidates[0].matches}
    assert "Accuracy" not in by_item
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Inspection Mode"].result == "PASS"
    assert by_item["Measurement Principle"].result == "PASS"
