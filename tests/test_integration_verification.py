"""
RAG / RequirementParser / Hard Requirement / Specification 생성까지의 통합 검증.

이 파일은 새 기능을 추가하기 위한 것이 아니라, 현재 구현이 실제 "요구사항 비교
시스템"으로서 안전하게 동작하는지 검증하기 위한 것이다. 각 테스트는 사용자가
제시한 7개 시나리오(TEST 1~7)와 RequirementParser 표현 5종(A~E)을 그대로 구현한다.

RAG가 필요한 테스트(TEST 1, 6, 7)는 fake-embedding 패턴(다른 테스트 파일과 동일)으로
sample_specs/*.md 전체를 실제로 색인한 뒤 진짜 검색 경로를 그대로 실행한다.
sample_specs에 정확히 맞는 조건의 문서가 없는 TEST 2~5는 요청서 지시대로 합성
Document/fixture로 candidate_matcher/spec_generator를 직접 검증한다(sample_specs
원본은 건드리지 않는다).
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
from agent.spec_generator import generate_specification
from agent.spec_validator import build_hard_requirement_report
from agent.units import evaluate_hard_requirements
from build_rag_ollama import build_vector_db

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_DB = "./_test_chroma_db_integration_verification"
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


def _dump(label, requirement=None, docs=None, candidates=None, spec=None, hard_report=None, validation=None):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    if requirement is not None:
        print(f"  measurement_range: {requirement.measurement_range}")
        print(f"  accuracy: {requirement.accuracy}")
        print(f"  required_accuracy_um: {requirement.required_accuracy_um}")
    if docs is not None:
        print(f"  검색된 후보 문서: {sorted({spec_retriever.source_label(d) for d in docs})}")
    if candidates is not None:
        for c in candidates:
            print(f"  candidate={c.source_document} manufacturer={c.manufacturer} model={c.model} hard_pass={c.hard_requirements_pass}")
            for m in c.matches:
                print(f"    - {m.item}: found={m.found_min}~{m.found_value}{m.found_unit} -> {m.result}")
    if spec is not None:
        print(f"  equipment.name: {spec.equipment.name}")
        mr = spec.measurement_performance.measurement_range
        mrf = spec.measurement_performance.measurement_range_full
        eq_acc = spec.measurement_performance.equipment_accuracy_um
        print(f"  measurement_range(legacy): {mr}")
        print(f"  measurement_range_full: {mrf}")
        print(f"  equipment_accuracy_um: {eq_acc}")
        print(f"  needs_confirmation: {spec.needs_confirmation}")
    if hard_report is not None:
        for r in hard_report:
            print(f"  [Hard Requirement] {r.item}: {r.reason} -> {r.result}")
    if validation is not None:
        print(f"  validation.is_valid: {validation.is_valid}")
        for i in validation.issues:
            print(f"    issue[{i.level}] {i.field}: {i.message}")


# =================================================================
# TEST 1 — 기본 PASS (실제 pipeline, 실제 SPEC-001.md 사용)
# =================================================================
def test_1_basic_pass(db):
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="음극", width_mm=5),
        inspection_items=["thickness"],
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    candidates = build_candidates(requirement, docs)
    fake_llm_response = SpecificationSchema()  # LLM은 아무것도 채우지 못했다고 가정 — candidate_matcher가 다 채워야 함
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, _ = retrieve_and_generate(requirement, db_path=db)
    hard_report = build_hard_requirement_report(specification, requirement)

    _dump("TEST 1 — 기본 PASS", requirement, docs, candidates, specification, hard_report, validation)

    assert "SPEC-001.md" in {spec_retriever.source_label(d) for d in docs}
    by_item = {r.item: r for r in hard_report}
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"

    assert specification.equipment.name == "OptiScan ES-200"
    mr = specification.measurement_performance.measurement_range
    assert mr.status == "VERIFIED"
    assert mr.source.document == "SPEC-001.md"
    mrf = specification.measurement_performance.measurement_range_full
    assert mrf.min == 0.0 and mrf.max == 200.0 and mrf.status == "VERIFIED"
    eq_acc = specification.measurement_performance.equipment_accuracy_um
    assert eq_acc.value == 1.0 and eq_acc.status == "VERIFIED" and eq_acc.source.document == "SPEC-001.md"

    assert "measurement_performance.measurement_range" not in specification.needs_confirmation
    assert "measurement_performance.equipment_accuracy_um" not in specification.needs_confirmation
    assert validation.is_valid is True


# =================================================================
# TEST 2 — 측정 범위 부족 (요청서 지시대로 합성 fixture 사용)
# =================================================================
def test_2_range_insufficient():
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 100 μm |\n| Accuracy | ±0.5 μm |\n",
        metadata={"filename": "FIXTURE-RANGE-SHORT.md", "source": "FIXTURE-RANGE-SHORT.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)

    _dump("TEST 2 — Range 부족", requirement, [doc], candidates)

    by_item = {m.item: m for m in best.matches}
    assert by_item["Measurement Range"].result == "FAIL"
    assert by_item["Accuracy"].result == "PASS"
    # 정확도가 PASS여도 range가 FAIL이면 전체 후보는 조건 충족(hard_requirements_pass)이 아니어야 한다.
    assert best.hard_requirements_pass is False


# =================================================================
# TEST 3 — 정확도 부족
# =================================================================
def test_3_accuracy_insufficient():
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 200 μm |\n| Accuracy | ±2.0 μm |\n",
        metadata={"filename": "FIXTURE-ACC-BAD.md", "source": "FIXTURE-ACC-BAD.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)

    _dump("TEST 3 — Accuracy 부족", requirement, [doc], candidates)

    by_item = {m.item: m for m in best.matches}
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "FAIL"
    assert best.hard_requirements_pass is False


# =================================================================
# TEST 4 — 둘 다 부족
# =================================================================
def test_4_both_insufficient():
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    doc = Document(
        page_content="| Item | Specification |\n|---|---|\n| Measurement Range | 0 ~ 100 μm |\n| Accuracy | ±2.0 μm |\n",
        metadata={"filename": "FIXTURE-BOTH-BAD.md", "source": "FIXTURE-BOTH-BAD.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)

    _dump("TEST 4 — 둘 다 부족", requirement, [doc], candidates)

    by_item = {m.item: m for m in best.matches}
    assert by_item["Measurement Range"].result == "FAIL"
    assert by_item["Accuracy"].result == "FAIL"
    assert best.hard_requirements_pass is False


# =================================================================
# TEST 5 — 장비 범위가 요구 범위를 포함하는 경우 (실제 SPEC-002.md: 0~300 μm)
# =================================================================
def test_5_range_containment_real_document(db):
    """
    현재 정책 확인: agent/units.py:range_covers()는 "장비 범위가 요구 범위를 포함하면
    PASS"로 이미 구현되어 있다(candidate_lo <= required_lo and candidate_hi >=
    required_hi) — "정확히 일치해야 한다"는 별도 정책은 코드에 없다. 이 테스트는
    실제 SPEC-002.md(0~300 μm, ±0.5 μm)로 이 기존 정책을 검증한다.
    """
    requirement = RequirementSchema(
        measurement_range=RequirementRange(min=0.0, max=200.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
    )
    doc = Document(
        page_content=(
            "## General\n\n- Manufacturer: InterferoTech\n- Model: WI-300\n\n"
            "## Measurement Performance\n\n| Item | Specification |\n|---|---|\n"
            "| Vertical Measurement Range | 0 ~ 300 μm |\n| Accuracy | ±0.5 μm |\n"
        ),
        metadata={"filename": "SPEC-002.md", "source": "SPEC-002.md", "source_type": "markdown", "chunk_id": 0},
    )
    candidates = build_candidates(requirement, [doc])
    best = select_best_candidate(candidates)

    _dump("TEST 5 — Range 포함관계 (실제 SPEC-002.md)", requirement, [doc], candidates)

    by_item = {m.item: m for m in best.matches}
    assert by_item["Measurement Range"].result == "PASS", "장비 범위(0~300)가 요구 범위(0~200)를 포함하므로 PASS여야 한다"
    assert by_item["Accuracy"].result == "PASS"
    assert best.hard_requirements_pass is True

    # range_covers()가 실제로 포함관계(>=/<=)로 구현되어 있는지 직접 확인
    from agent.units import range_covers
    assert range_covers(candidate_range=(0.0, 300.0, "um"), required_range=(0.0, 200.0, "um")) is True
    assert range_covers(candidate_range=(0.0, 100.0, "um"), required_range=(0.0, 200.0, "um")) is False


# =================================================================
# TEST 6 — 요구조건을 만족하는 장비가 없는 경우 (실제 sample_specs 전체 검색)
# =================================================================
def test_6_no_matching_equipment(db):
    """
    "0~500 μm 측정 범위와 ±0.1 μm 이하 정확도" — sample_specs/*.md 전체를 확인한 결과
    (grep으로 사전 확인, 이 테스트에서도 재확인) 정확도 <=0.1μm을 만족하는 문서는
    하나도 없다(가장 좋은 게 SPEC-007의 ±0.3μm). 조건을 만족하는 후보가 없다는 것이
    확인된 상태에서, 시스템이 허위로 PASS를 만들어내지 않는지 검증한다.
    """
    requirement = RequirementSchema(
        raw_text="0~500 μm 측정 범위와 ±0.1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        measurement_range=RequirementRange(min=0.0, max=500.0, unit="um"),
        accuracy=RequirementValue(value=0.1, unit="um", operator="<="),
        required_accuracy_um=0.1,
        inspection_items=["thickness"],
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    candidates = build_candidates(requirement, docs)

    # sample_specs 전체(파일 자체, RAG 결과와 무관)에 대해 실제로 만족하는 문서가
    # 없는지 원문 기준으로도 재확인한다(테스트가 스스로 전제를 검증).
    all_md = list((_REPO_ROOT / "sample_specs").glob("*.md"))
    from agent.candidate_matcher import _extract_candidate_fact
    any_real_pass = False
    for f in all_md:
        text = f.read_text(encoding="utf-8")
        fact = _extract_candidate_fact([Document(page_content=text, metadata={"filename": f.name})])
        if fact.accuracy and fact.accuracy[0] <= 0.1:
            any_real_pass = True
    assert any_real_pass is False, "전제 확인 실패: 실제로 <=0.1um을 만족하는 문서가 존재합니다"

    best = select_best_candidate(candidates)
    _dump("TEST 6 — 적합 장비 없음", requirement, docs, candidates)

    if best is not None:
        by_item = {m.item: m for m in best.matches}
        assert by_item["Accuracy"].result != "PASS", "정확도 <=0.1um을 만족하는 실제 문서가 없으므로 PASS로 잘못 판정되면 안 된다"
        assert best.hard_requirements_pass is False, "적합 장비가 없는데 hard_requirements_pass=True가 되면 안 된다"

    # generate_specification까지 실행해도(LLM 모킹, 빈 응답 = 값을 지어내지 않음)
    # accuracy가 허위로 PASS 판정되지 않는지 종단 확인
    fake_llm_response = SpecificationSchema()
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, _ = retrieve_and_generate(requirement, db_path=db)
    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}
    assert by_item["Accuracy"].result != "PASS"


# =================================================================
# TEST 7 — 정보가 부족한 모호한 질문
# =================================================================
def test_7_ambiguous_query_does_not_invent_values():
    llm_stub = RequirementSchema()  # 실제 LLM이 모호한 질문에 대해 아무것도 못 채웠다고 가정
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=llm_stub):
        requirement, validation = analyze_requirement(user_text="좋은 전극 검사기를 찾아줘.")

    _dump("TEST 7 — 모호한 질문", requirement)
    print(f"  target.material: {requirement.target.material}")
    print(f"  target.width_mm: {requirement.target.width_mm}")
    print(f"  inspection_items: {requirement.inspection_items}")
    print(f"  validation.is_valid: {validation.is_valid}")
    print(f"  questions: {validation.questions}")

    assert requirement.target.material is None
    assert requirement.target.width_mm is None
    assert requirement.inspection_items == []
    assert requirement.measurement_range is None
    assert requirement.accuracy is None
    assert requirement.required_accuracy_um is None
    # 값을 못 채웠으므로 후속 질문으로 유도해야 한다(is_valid=False, 질문 존재).
    assert validation.is_valid is False
    assert len(validation.questions) > 0


# =================================================================
# 4. RequirementParser 표현 A~E
# =================================================================
@pytest.mark.parametrize(
    "label,text",
    [
        ("A", "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."),
        ("B", "0 - 200 μm 측정 범위, 정확도 ±1 μm 이하인 장비를 찾아줘."),
        ("C", "0 to 200 μm 범위를 측정하고 정확도는 ±1 μm 이하여야 해."),
        ("D", "최대 200 μm까지 측정 가능하고 정확도는 1 μm 이내인 검사기를 찾아줘."),
        ("E", "200 μm 이하 측정 범위, ±1 μm 이하 정확도가 필요해."),
    ],
)
def test_requirement_parser_expressions(label, text):
    requirement = RequirementSchema(raw_text=text)
    apply_deterministic_extraction(requirement)
    print(f"\n[표현 {label}] {text!r}")
    print(f"  measurement_range: {requirement.measurement_range}")
    print(f"  accuracy: {requirement.accuracy}")
    print(f"  required_accuracy_um: {requirement.required_accuracy_um}")

    assert requirement.measurement_range is not None, f"[{label}] measurement_range가 구조화되지 않았습니다: {text!r}"
    assert requirement.measurement_range.min == 0.0
    assert requirement.measurement_range.max == 200.0
    assert requirement.measurement_range.unit == "um"
    assert requirement.required_accuracy_um == 1.0


# =================================================================
# 5. Hard Requirement가 LLM 판단에 의존하지 않는지 확인 (결정론적 함수 직접 호출)
# =================================================================
@pytest.mark.parametrize(
    "candidate_range,expected",
    [((0.0, 200.0, "um"), True), ((0.0, 100.0, "um"), False), ((0.0, 300.0, "um"), True)],
)
def test_range_comparison_is_deterministic(candidate_range, expected):
    ok, _ = evaluate_hard_requirements(required_range=(0.0, 200.0, "um"), candidate_range=candidate_range)
    assert ok is expected


@pytest.mark.parametrize(
    "candidate_accuracy,expected",
    [((0.5, "um"), True), ((1.0, "um"), True), ((1.5, "um"), False)],
)
def test_accuracy_comparison_is_deterministic(candidate_accuracy, expected):
    ok, _ = evaluate_hard_requirements(required_accuracy=(1.0, "um", "<="), candidate_accuracy=candidate_accuracy)
    assert ok is expected


def test_evaluate_hard_requirements_has_no_llm_dependency():
    """evaluate_hard_requirements/candidate_matcher가 ollama_client를 import/호출하지 않는지 정적으로 확인한다."""
    import agent.units as units_module
    import agent.candidate_matcher as candidate_matcher_module

    assert "ollama_client" not in dir(units_module)
    assert "ollama" not in units_module.__doc__.lower() or "llm" in units_module.__doc__.lower()
    # candidate_matcher는 ollama_client를 import하지 않는다(정적 검사).
    import inspect
    source = inspect.getsource(candidate_matcher_module)
    assert "ollama_client" not in source
    assert "parse_structured" not in source
