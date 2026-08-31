"""
"실제 실행 결과 검증" 요청에 대한 회귀 테스트.

다뤄지는 실제 버그 3종:
  1. raw_text에 담긴 구체적 수치("0~200 μm 측정 범위와 ±1 μm 이하 정확도")가
     material/inspection_items가 이미 있으면 검색 질의에 전혀 쓰이지 않던 문제
     (agent.spec_retriever._build_queries).
  2. k_per_query가 좁아서(3) 의미 검색 top-3 밖으로 밀려난 관련 문서(SPEC-001.md)가
     누락되던 문제 — range_boost로 구조적 비교를 보강하고 기본 k도 5로 올림.
  3. LLM이 status="VERIFIED"라고 주장해도 실제로 검색된 문서에 그 값이 있는지
     코드가 전혀 확인하지 않던 문제(agent.spec_generator._verify_sourced_numbers).

Ollama가 없는 환경이므로 임베딩만 결정론적 fake vector로 스텁한다(다른 테스트
파일과 동일한 패턴).
"""
import hashlib
import shutil
import tempfile
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document

from agent import spec_retriever
from agent.chroma_store import SimpleChromaStore
from agent.schemas import (
    RequirementSchema,
    RequirementTarget,
    SourcedNumber,
    SourceRef,
    SpecificationSchema,
)
from agent.spec_generator import (
    _fallback_equipment_identity,
    _find_matching_doc,
    _verify_sourced_numbers,
    generate_specification,
)
from agent.spec_validator import validate_specification
from build_rag_ollama import build_vector_db
from tests.scoped_spec_db import build_scoped_vector_db

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"
_TEST_DB = "./_test_chroma_db_source_verification"

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
    build_vector_db(str(_SAMPLE_SPECS_DIR), _TEST_DB, rebuild=True)
    yield _TEST_DB
    shutil.rmtree(_TEST_DB, ignore_errors=True)


# ---------------------------------------------------------------
# 1. raw_text가 항상 질의에 포함되는지
# ---------------------------------------------------------------
def test_build_queries_always_includes_raw_text_even_with_material_and_items():
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    queries = spec_retriever._build_queries(requirement)
    assert _REPORTED_QUERY in queries, "material/inspection_items가 있어도 raw_text는 항상 질의에 포함되어야 함"


# ---------------------------------------------------------------
# 2. 좁은 k(3)에서도 range_boost 덕분에 SPEC-001(0~200 μm 포함 문서)이 검색되는지
# ---------------------------------------------------------------
def test_reported_query_finds_spec_001_even_with_narrow_k(db):
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=3)
    sources = {spec_retriever.source_label(d) for d in docs}
    assert "SPEC-001.md" in sources, (
        f"range_boost가 0~200 μm 조건을 만족하는 SPEC-001.md를 찾아오지 못했습니다. 실제 결과: {sources}"
    )


def test_reported_query_pulls_identity_chunk_for_matched_source(db):
    """
    SPEC-001.md가 검색 결과에 포함되면(Measurement Performance chunk 등), 그 문서의
    식별 정보 chunk(chunk_id=0, Manufacturer/Model이 적힌 General 절)도 별도로
    함께 딸려와야 한다 — 그래야 spec_generator._fallback_equipment_identity()가
    "다른 문서"가 아니라 실제로 검증된 문서에서 장비명을 뽑을 수 있다.
    """
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="전극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=3)
    spec001_chunk_ids = {d.metadata.get("chunk_id") for d in docs if spec_retriever.source_label(d) == "SPEC-001.md"}
    assert 0 in spec001_chunk_ids, f"SPEC-001.md의 식별 정보 chunk(id=0)가 결과에 없습니다: {spec001_chunk_ids}"


def test_default_k_per_query_is_10_not_3_or_5():
    """
    k_per_query 기본값 회귀 가드. 원래 3(버그)에서 5로 올린 이력을 5→3 재발
    방지로만 지키던 테스트였으나, 실제 Ollama bge-m3 임베딩 + 실제 ChromaDB(52
    SPEC/383 chunk)로 R1~R5를 k=[3,5,10,20,30,50,100]으로 스윕한 결과 k=5에서도
    특정 질의(측정 원리/범위 조건이 전혀 없는 "두께+표면결함, 정확도 미지정"
    유형)의 정답 후보가 top-k 검색에서 누락되는 사례가 실측되어(agent/pipeline.py
    retrieve_and_generate() docstring 참고) 10으로 다시 올렸다. 3과 5 둘 다로
    되돌아가지 않는지 함께 확인한다.
    """
    import inspect

    sig = inspect.signature(spec_retriever.retrieve_for_requirement)
    assert sig.parameters["k_per_query"].default == 10

    from agent.pipeline import retrieve_and_generate

    sig2 = inspect.signature(retrieve_and_generate)
    assert sig2.parameters["k_per_query"].default == 10


# ---------------------------------------------------------------
# 3. _verify_sourced_numbers: 문서에 실제로 있는 값은 확인 + source 보강
# ---------------------------------------------------------------
def test_verify_confirms_value_actually_in_retrieved_docs_and_fills_source():
    doc = Document(
        page_content="| Accuracy | ±1.0 μm |",
        metadata={"filename": "SPEC-001.md", "chunk_id": 3, "item": "Measurement Performance"},
    )
    spec = SpecificationSchema()
    spec.measurement_performance.accuracy_um = SourcedNumber(value=1.0, unit="um", status="VERIFIED")

    _verify_sourced_numbers(spec, [doc])

    sn = spec.measurement_performance.accuracy_um
    assert sn.status == "VERIFIED"
    assert sn.source is not None
    assert sn.source.document == "SPEC-001.md"
    assert sn.source.chunk_id == 3


# ---------------------------------------------------------------
# 4. _verify_sourced_numbers: 검색 결과에 없는 값을 VERIFIED로 주장하면 INFERRED로 강등
# ---------------------------------------------------------------
def test_verify_downgrades_unconfirmable_verified_to_inferred():
    doc = Document(page_content="다른 내용이며 이 값은 어디에도 없습니다.", metadata={"filename": "other.md"})
    spec = SpecificationSchema()
    spec.measurement_performance.accuracy_um = SourcedNumber(value=1.0, unit="um", status="VERIFIED")

    _verify_sourced_numbers(spec, [doc])

    sn = spec.measurement_performance.accuracy_um
    assert sn.status == "INFERRED"
    assert sn.reasoning is not None and "INFERRED" in sn.reasoning


def test_find_matching_doc_returns_none_when_unit_missing():
    spec_no_unit = SourcedNumber(value=1.0, status="VERIFIED")
    assert _find_matching_doc(spec_no_unit, []) is None


# ---------------------------------------------------------------
# 5. equipment.name 자동 보강 (regex fallback)
# ---------------------------------------------------------------
def test_equipment_identity_fallback_extracts_manufacturer_and_model():
    doc = Document(
        page_content="## General\n\n- Manufacturer: OptiScan\n- Model: ES-200\n- Equipment Type: Electrode 3D Inspection System",
        metadata={"filename": "SPEC-001.md"},
    )
    spec = SpecificationSchema()
    assert not spec.equipment.name

    _fallback_equipment_identity(spec, [doc])

    assert spec.equipment.manufacturer == "OptiScan"
    assert spec.equipment.model == "ES-200"
    assert spec.equipment.name == "OptiScan ES-200"
    assert any("SPEC-001.md" in note for note in spec.notes)


def test_equipment_identity_fallback_noop_when_already_filled():
    doc = Document(page_content="- Manufacturer: OptiScan\n- Model: ES-200", metadata={"filename": "SPEC-001.md"})
    spec = SpecificationSchema()
    spec.equipment.name = "이미 채워진 이름"

    _fallback_equipment_identity(spec, [doc])

    assert spec.equipment.name == "이미 채워진 이름"


# ---------------------------------------------------------------
# 6. end-to-end: generate_specification()이 실제로 검증/보강 단계를 거치는지
# ---------------------------------------------------------------
def test_generate_specification_downgrades_hallucinated_verified_value(db):
    requirement = RequirementSchema(target=RequirementTarget(material="전극"), inspection_items=["thickness"])
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=3)
    context_text = spec_retriever.format_context(retrieved_docs)

    fake_llm_response = SpecificationSchema()
    fake_llm_response.measurement_performance.reproducibility_um = SourcedNumber(
        value=999.0, unit="um", status="VERIFIED"
    )  # 어떤 sample_specs에도 없는 값 -> 검증 실패해야 함

    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        spec = generate_specification(requirement, retrieved_docs, context_text, model="test-model")

    assert spec.measurement_performance.reproducibility_um.status == "INFERRED"
    assert "measurement_performance.reproducibility_um" in spec.needs_confirmation


def test_generate_specification_reproduces_reported_bug_fixed_end_to_end(tmp_path):
    """
    사용자가 실제로 보고한 시나리오 그대로 재현: "0~200 μm 측정 범위와 ±1 μm 이하
    정확도가 필요한 전극 검사기를 찾아줘." 질의에 대해, 소형 LLM이 measurement_range를
    VERIFIED로 주장하되 source는 비워서 반환한다고 가정한다(실제 보고된 증상).

    수정 전: SPEC-001.md가 검색에서 누락되고, source 없는 VERIFIED가 그대로 통과하고,
    equipment.name은 N/A로 남았다.
    수정 후: SPEC-001.md가 검색되고, VERIFIED 값의 근거가 실제로 채워지고,
    equipment.name이 그 근거 문서(SPEC-001.md, OptiScan ES-200)에서 정확히 채워진다.

    SPEC-001.md만 있는 격리된 corpus를 쓴다 — sample_specs/에 SPEC-011~050이
    추가되면서 이 조건을 SPEC-001과 동등하게 만족하는 신규 장비가 여러 개 생겼다
    (설계 의도, 요청서 11절). k_per_query=3(원래 버그의 핵심 — 좁은 top-k에서도
    range_boost로 SPEC-001이 검색되는지)과 VERIFIED source 재조정 메커니즘은
    이 격리된 corpus에서도 동일하게 검증된다 — 달라지는 것은 "corpus 전체에서
    유일하게 이겨야 한다"는, 더 이상 성립하지 않는 전제뿐이다.
    """
    db = build_scoped_vector_db(tmp_path, ["SPEC-001.md"])
    requirement = RequirementSchema(
        raw_text=_REPORTED_QUERY,
        target=RequirementTarget(material="전극", width_mm=500),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=3)
    assert "SPEC-001.md" in {spec_retriever.source_label(d) for d in retrieved_docs}

    fake_llm_response = SpecificationSchema()
    fake_llm_response.measurement_performance.measurement_range = SourcedNumber(
        value=200.0, unit="um", status="VERIFIED"
    )

    context_text = spec_retriever.format_context(retrieved_docs)
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        spec = generate_specification(requirement, retrieved_docs, context_text, model="test-model")

    mr = spec.measurement_performance.measurement_range
    assert mr.status == "VERIFIED"
    assert mr.source is not None and mr.source.document == "SPEC-001.md"
    assert spec.equipment.name == "OptiScan ES-200"


# ---------------------------------------------------------------
# 7. spec_validator: VERIFIED인데 source가 없으면 이제 error(is_valid=False)
# ---------------------------------------------------------------
def test_validator_treats_verified_without_source_as_error():
    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.measurement_performance.accuracy_um = SourcedNumber(value=1.0, unit="um", status="VERIFIED")  # source 없음

    result = validate_specification(spec)
    assert result.is_valid is False
    matching = [i for i in result.issues if i.field == "measurement_performance.accuracy_um" and "출처" in i.message]
    assert matching and matching[0].level == "error"


def test_validator_allows_verified_with_source():
    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.measurement_performance.accuracy_um = SourcedNumber(
        value=1.0, unit="um", status="VERIFIED", source=SourceRef(document="SPEC-001.md")
    )

    result = validate_specification(spec)
    assert not any(
        i.field == "measurement_performance.accuracy_um" and "출처" in i.message for i in result.issues
    )
