"""
전극 검사기 Agent 파이프라인 테스트.

Ollama가 실행 중인 사내 서버가 아니면 LLM 추론 자체는 검증할 수 없으므로,
`agent.ollama_client.parse_structured` / `OllamaEmbeddings.embed_*` 만 스텁으로
대체하고 나머지(파싱 결과 검증, RAG 인덱싱/검색, 병합 로직, 검증 규칙, PPTX 생성)는
실제 코드 경로를 그대로 실행해서 검증한다.

실행 방법:
    pip install pytest numpy
    pytest tests/ -v
"""
import hashlib
import shutil
import tempfile
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings

from agent import spec_retriever
from agent.pipeline import analyze_requirement, retrieve_and_generate
from agent.pptx_electrode_builder import ElectrodeSpecPPTXBuilder
from agent.requirement_validator import validate_requirement
from agent.schemas import (
    RequirementSchema,
    RequirementTarget,
    SourcedNumber,
    SpecificationSchema,
)
from agent.spec_validator import validate_specification
from build_rag_ollama import build_vector_db

TEST_DB_PATH = "./_test_chroma_db_pytest"


def _fake_vector(text: str, dim: int = 32):
    h = hashlib.sha256(text.encode("utf-8")).digest()
    arr = np.frombuffer((h * (dim // len(h) + 1))[: dim * 4], dtype=np.uint32).astype(np.float64)
    return (arr / arr.max()).tolist()


@pytest.fixture(scope="module", autouse=True)
def fake_embeddings():
    with mock.patch.object(OllamaEmbeddings, "embed_documents", lambda self, texts: [_fake_vector(t) for t in texts]), \
         mock.patch.object(OllamaEmbeddings, "embed_query", lambda self, text: _fake_vector(text)):
        yield


@pytest.fixture(scope="module", autouse=True)
def indexed_db(fake_embeddings):
    """
    sample_specs/ 안의 실제 파일 형식(.md 또는 .pptx, 또는 둘 다)에 상관없이 인덱싱한다.
    build_rag_ollama.build_vector_db()는 두 형식을 모두 스캔하므로, sample_specs가
    전부 Markdown으로 바뀌어도(레거시 index_spec_rows_from_folder는 .pptx 전용이라
    이 경우 0건을 반환한다) 테스트 DB가 비어있지 않게 만든다.
    """
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)
    build_vector_db("sample_specs", TEST_DB_PATH)
    from agent.chroma_store import SimpleChromaStore

    n = SimpleChromaStore(persist_directory=TEST_DB_PATH, embedding_function=spec_retriever.get_embeddings())._collection.count()
    assert n > 0, "sample_specs/ 인덱싱 결과가 0건이면 이후 검색 테스트가 무의미하므로 실패시킨다"
    yield
    shutil.rmtree(TEST_DB_PATH, ignore_errors=True)


# ==========================================
# RequirementValidator
# ==========================================
def test_requirement_validator_detects_missing_fields():
    req = RequirementSchema(
        target=RequirementTarget(material="전극", width_mm=500),
        inspection_items=["thickness", "surface_defect"],
        measurement_method="non_contact",
    )
    result = validate_requirement(req)
    assert result.is_valid is False
    assert "required_accuracy_um" in result.missing_fields
    assert "minimum_defect_size_um" in result.missing_fields
    assert "target.thickness_range_um" in result.missing_fields
    assert len(result.questions) >= len(result.missing_fields)


def test_requirement_validator_valid_when_complete():
    req = RequirementSchema(
        target=RequirementTarget(material="전극", width_mm=500, thickness_range_um="0~200"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    assert validate_requirement(req).is_valid is True


def test_requirement_validator_never_invents_values():
    """빈 RequirementSchema를 넣었을 때, validator가 값을 채우지 않고 그대로 null로 남기는지 확인."""
    req = RequirementSchema()
    result = validate_requirement(req)
    assert req.target.material is None
    assert req.required_accuracy_um is None
    assert result.is_valid is False


# ==========================================
# SpecificationValidator
# ==========================================
def test_spec_validator_flags_repeatability_worse_than_accuracy():
    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"
    spec.measurement_performance.accuracy_um = SourcedNumber.from_legacy(value=1.0, unit="um", source_type="document", source="a.pptx")
    spec.measurement_performance.repeatability_um = SourcedNumber.from_legacy(value=5.0, unit="um", source_type="document", source="a.pptx")

    result = validate_specification(spec)
    messages = [i.message for i in result.issues]
    assert any("반복성" in m for m in messages)


def test_spec_validator_requires_accuracy_for_thickness_requirement():
    req = RequirementSchema(inspection_items=["thickness"])
    spec = SpecificationSchema()
    spec.inspection_target.material = "전극"
    spec.inspection_items = ["thickness"]
    spec.equipment.name = "테스트 장비"

    result = validate_specification(spec, requirement=req)
    assert result.is_valid is False
    assert any(i.field == "measurement_performance.accuracy_um" for i in result.issues)


# ==========================================
# 통합: 요청서 18절의 테스트 케이스 3종
# ==========================================
def _run_case(stub_requirement: RequirementSchema, followup: dict, stub_llm_spec: SpecificationSchema, user_text: str = "(테스트용 입력)"):
    """
    followup은 실제 제품에서 "추가 질문에 대한 사용자 답변"을 흉내낸다 — 여기서
    설정하는 값(target.material/width_mm 등)은 raw_text에 근거가 없어도 정상이다
    (사용자가 팔로우업 폼에 직접 입력한 값이므로 apply_deterministic_extraction의
    "LLM 환각은 신뢰하지 않는다" 정책과 무관하게 항상 보존되어야 하는 값).
    user_text는 실제 최초 자연어 질문을 그대로 넘겨야 한다 — RequirementParser가
    이제 raw_text에 없는 값은 LLM이 뭘 채웠든 지우므로("전극"처럼 구체적이지 않은
    재질명 포함), 무의미한 placeholder 문장을 쓰면 stub_requirement가 채운 값도
    함께 지워진다.
    """
    with mock.patch("agent.ollama_client.parse_structured", return_value=stub_requirement):
        requirement, validation = analyze_requirement(user_text=user_text)

    for path, value in followup.items():
        keys = path.split(".")
        target = requirement
        for k in keys[:-1]:
            target = getattr(target, k)
        setattr(target, keys[-1], value)

    validation = validate_requirement(requirement)
    assert validation.is_valid is True, f"followup 적용 후에도 invalid: {validation.missing_fields}"

    with mock.patch("agent.ollama_client.parse_structured", return_value=stub_llm_spec):
        specification, spec_validation, retrieved_docs = retrieve_and_generate(requirement, db_path=TEST_DB_PATH)

    assert len(retrieved_docs) > 0
    from make_electrode_template import build_electrode_template

    with tempfile.TemporaryDirectory() as tmp_dir:
        template_path = str(Path(tmp_dir) / "template_electrode.pptx")
        build_electrode_template(template_path)
        builder = ElectrodeSpecPPTXBuilder(template_path=template_path)
        output_path = builder.build(specification, output_path=str(Path(tmp_dir) / "test_output.pptx"))

        from pptx import Presentation
        prs = Presentation(output_path)
        assert len(prs.slides) == 9
    return specification, spec_validation


def test_case_1_width_thickness_surface_defect_non_contact():
    text = "500mm 폭의 전극을 검사하고 두께와 표면 결함을 측정하는 비접촉 검사기가 필요하다."
    stub_req = RequirementSchema(
        target=RequirementTarget(material="전극", width_mm=500),
        inspection_items=["thickness", "surface_defect"],
        measurement_method="non_contact",
    )
    with mock.patch("agent.ollama_client.parse_structured", return_value=stub_req):
        requirement, validation = analyze_requirement(user_text=text)
    assert validation.is_valid is False  # 정확도/최소결함/두께범위 질문이 나와야 함
    # "폭 500mm"는 raw_text에 명확한 근거가 있으므로 결정론적 추출로 정상 채워진다.
    assert requirement.target.width_mm == 500.0
    # "전극"은 구체적 재질명이 아니므로(양극/음극/분리막 중 하나가 아님) 미정으로
    # 남아야 한다 — 팔로우업에서 사용자가 직접 답해야 하는 항목.
    assert requirement.target.material is None

    stub_spec = SpecificationSchema()
    stub_spec.equipment.name = "전극 두께/표면결함 비접촉 검사기"
    specification, _ = _run_case(
        stub_req,
        {
            "target.material": "전극",  # 팔로우업 질문("예: 양극, 음극, 분리막, 전극 전반")에 대한 사용자의 실제 답변
            "required_accuracy_um": 1.0,
            "minimum_defect_size_um": 10.0,
            "target.thickness_range_um": "0~200",
        },
        stub_spec,
        user_text=text,
    )
    assert specification.measurement_performance.accuracy_um.value == 1.0
    assert specification.measurement_performance.accuracy_um.status == "USER_DEFINED"


def test_case_2_thickness_range_and_accuracy():
    text = "전극 두께를 0~200um 범위에서 측정하고 1um 이하의 정확도가 필요하다."
    stub_req = RequirementSchema(
        target=RequirementTarget(material="전극", thickness_range_um="0~200"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    with mock.patch("agent.ollama_client.parse_structured", return_value=stub_req):
        _, validation = analyze_requirement(user_text=text)
    assert "target.width_mm" in validation.missing_fields
    assert "target.material" in validation.missing_fields  # "전극"은 구체적 재질명이 아니므로 팔로우업 필요

    stub_spec = SpecificationSchema()
    stub_spec.equipment.name = "전극 두께 정밀 측정기"
    specification, _ = _run_case(
        stub_req,
        {"target.width_mm": 300, "target.material": "전극"},
        stub_spec,
        user_text=text,
    )
    assert specification.measurement_performance.accuracy_um.value == 1.0


def test_case_3_3d_profile_min_defect_size():
    text = "3D 표면 형상을 측정하고 최소 10um 크기의 표면 결함을 검출할 수 있는 검사기가 필요하다."
    stub_req = RequirementSchema(
        target=RequirementTarget(material="전극", width_mm=400),
        inspection_items=["profile_3d"],
        minimum_defect_size_um=10.0,
    )
    with mock.patch("agent.ollama_client.parse_structured", return_value=stub_req):
        _, validation = analyze_requirement(user_text=text)
    # 이 문장은 재질/폭에 대한 근거가 전혀 없으므로(사용자가 명시하지 않음),
    # LLM이 뭘 채웠든 결정론적 추출이 지워야 하고 팔로우업이 필요해야 한다 —
    # "profile_3d + minimum_defect_size_um만 있으면 충족"은 material/width_mm이
    # LLM 환각으로 살아남는다는 잘못된 전제였다.
    assert "target.material" in validation.missing_fields
    assert "target.width_mm" in validation.missing_fields

    stub_spec = SpecificationSchema()
    stub_spec.equipment.name = "3D 표면 프로파일 검사기"
    specification, _ = _run_case(
        stub_req,
        {"target.material": "전극", "target.width_mm": 400},
        stub_spec,
        user_text=text,
    )
    assert specification.defect_detection.minimum_defect_size_um.value == 10.0
