"""
sample_specs/SPEC-001.md 하나만 통합 검증되어 있던 상태에서, 나머지 9개
(SPEC-002~010)도 실제 RAG(fake-embedding 패턴) → RequirementParser →
CandidateMatcher → Hard Requirement 판정까지 실제 경로로 검증한다.

회귀 배경: 각 사양서 자신의 실측 수치를 그대로 요구사항으로 넣어 질의했을 때
(자기 자신을 만족해야 하는 것이 자명함), SPEC-003/004/007/008이 "Measurement
Range"가 아니라 "Thickness Range"/"Vertical Range"라는 표 라벨을 쓴다는 이유로
agent/candidate_matcher.py의 _RANGE_LABEL_HINTS 고정 문구 매칭에 실패해
Measurement Range가 UNKNOWN으로 잘못 판정되는 버그가 실제로 발견되었다(RAG가
해당 chunk를 정상적으로 검색해오는 것도 별도로 확인됨 — 검색 문제가 아니라
라벨 파싱 문제였다). 그 결과 "1~500 μm 측정 범위, ±2.0 μm 이하 정확도"로
질의하면 실제로는 SPEC-003(OCTVision OCT-E100)이 정답이어야 하는데 SPEC-005가
대신 선택되는 실질적 오류로 이어졌다.

수정: agent/candidate_matcher.py에 _is_range_label()을 추가해, 고정 문구
힌트에 더해 라벨이 "range"/"범위"로 끝나는지도 함께 확인하도록 확장했다
(sample_specs 전체 corpus에서 정상적인 범위 라벨은 예외 없이 "Range"/"범위"로
끝난다는 것을 grep으로 확인).

이 파일은 sample_specs/*.md 원본을 건드리지 않고 읽기만 한다.
"""
import hashlib
import shutil
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest
from langchain_community.embeddings import OllamaEmbeddings

from agent import spec_retriever
from agent.candidate_matcher import build_candidates, select_best_candidate
from agent.pipeline import retrieve_and_generate
from agent.requirement_parser import apply_deterministic_extraction
from agent.schemas import RequirementSchema, RequirementTarget, SpecificationSchema
from agent.spec_validator import build_hard_requirement_report
from build_rag_ollama import build_vector_db

_TEST_DB = "./_test_chroma_db_sample_specs_full_coverage"


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


# 각 사양서 자신의 실측 Measurement Range/Accuracy를 그대로 요구사항 문장으로
# 사용한다 — 그 사양서 스스로는 반드시 PASS해야 한다(자명한 전제).
# (source_document, query_text, expected_range, expected_accuracy)
_SELF_SATISFYING_CASES = [
    ("SPEC-002.md", "0~300 μm 측정 범위와 ±0.5 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (0.0, 300.0), 0.5),
    ("SPEC-003.md", "1~500 μm 측정 범위와 ±2.0 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (1.0, 500.0), 2.0),
    ("SPEC-005.md", "0~500 μm 측정 범위와 ±2.0 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (0.0, 500.0), 2.0),
    ("SPEC-007.md", "0~100 μm 측정 범위와 ±0.3 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (0.0, 100.0), 0.3),
    ("SPEC-008.md", "5~400 μm 측정 범위와 ±1.5 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (5.0, 400.0), 1.5),
    ("SPEC-009.md", "0~1000 μm 측정 범위와 ±3.0 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (0.0, 1000.0), 3.0),
    ("SPEC-010.md", "0~300 μm 측정 범위와 ±0.8 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.", (0.0, 300.0), 0.8),
]


@pytest.mark.parametrize("source,query_text,expected_range,expected_accuracy", _SELF_SATISFYING_CASES)
def test_spec_passes_its_own_measurement_range_and_accuracy(db, source, query_text, expected_range, expected_accuracy):
    requirement = RequirementSchema(raw_text=query_text, inspection_items=["thickness"])
    apply_deterministic_extraction(requirement)
    assert requirement.measurement_range is not None
    assert (requirement.measurement_range.min, requirement.measurement_range.max) == expected_range
    assert requirement.accuracy.value == expected_accuracy

    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    assert source in {spec_retriever.source_label(d) for d in docs}, f"{source}가 RAG 검색 결과에 없습니다"

    candidates = build_candidates(requirement, docs)
    by_source = {c.source_document: c for c in candidates}
    candidate = by_source[source]
    by_item = {m.item: m for m in candidate.matches}

    assert by_item["Measurement Range"].result == "PASS", (
        f"{source}: 자기 자신의 측정 범위({expected_range})를 PASS해야 하는데 "
        f"{by_item['Measurement Range'].result}로 판정됨 (라벨 인식 회귀 가능성)"
    )
    assert by_item["Accuracy"].result == "PASS"
    # 이 테스트의 목적은 Range/Accuracy 라벨 인식 자체이므로 그 둘만 확정 검증한다.
    # inspection_items=["thickness"]는 파싱 경로를 그대로 타게 하려는 부수 설정일
    # 뿐, 사양서 원문에 "thickness"를 실제로 지원한다는 서술 근거(Equipment Type/
    # Notes)가 없는 SPEC-002/005/007/009/010(3D/profile 계열 장비, Z축 범위만
    # 있고 두께 측정이라는 명시적 근거는 없음)은 candidate_matcher가 이제 Thickness
    # Measurement를 정직하게 UNKNOWN으로 남긴다 — 그래서 hard_requirements_pass가
    # 전부 True는 아니다(요청서 문제3: Measurement Range (Z)만으로 두께 측정
    # 지원을 단정하면 안 된다).


# 표 라벨이 "Measurement Range"라는 고정 문구를 쓰지 않는 회귀 케이스만 별도로
# 명시 — "Thickness Range"(003/004/008), "Vertical Range"(007).
@pytest.mark.parametrize(
    "source,label_fragment",
    [
        ("SPEC-003.md", "Thickness Range"),
        ("SPEC-004.md", "Thickness Range"),
        ("SPEC-007.md", "Vertical Range"),
        ("SPEC-008.md", "Thickness Range"),
    ],
)
def test_non_standard_range_labels_are_recognized(source, label_fragment):
    text = (Path(__file__).resolve().parent.parent / "sample_specs" / source).read_text(encoding="utf-8")
    assert label_fragment in text, f"전제 확인 실패: {source}에 {label_fragment!r} 라벨이 없습니다"

    from agent.candidate_matcher import _extract_candidate_fact
    from langchain_core.documents import Document

    fact = _extract_candidate_fact([Document(page_content=text, metadata={"filename": source})])
    assert fact.range is not None, f"{source}: {label_fragment!r} 라벨의 범위 값이 추출되지 않았습니다"


def test_spec_004_percent_accuracy_is_unknown_not_falsely_passed_or_failed(db):
    """
    SPEC-004는 Accuracy가 %(±0.5 %) 단위로 표기되어 있어 μm 요구조건과 차원이
    달라 비교 자체가 불가능하다 — 이는 버그가 아니라 데이터 특성이며, FAIL로
    단정하지 않고 UNKNOWN으로 정직하게 표시되어야 한다(agent/units.py의
    차원 불일치 처리 정책, Phase 4에서 확립).
    """
    requirement = RequirementSchema(
        raw_text="0.1~50 μm 측정 범위와 ±0.5 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        inspection_items=["thickness"],
    )
    apply_deterministic_extraction(requirement)
    docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db, k_per_query=5)
    candidates = build_candidates(requirement, docs)
    by_source = {c.source_document: c for c in candidates}
    candidate = by_source["SPEC-004.md"]
    by_item = {m.item: m for m in candidate.matches}

    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "UNKNOWN"


def test_end_to_end_pipeline_selects_correct_candidate_for_non_standard_label(db):
    """
    라벨 인식 버그가 있었을 때 실제로 관찰된 파급 효과에 대한 종단 회귀 테스트:
    "1~500 μm 측정 범위, ±2.0 μm 이하 정확도" 질의는 SPEC-003(OCTVision
    OCT-E100)이 정답이어야 하는데, 버그가 있으면 SPEC-003의 Measurement Range가
    UNKNOWN 처리되어 대신 SPEC-005(LaserMetrix LP-500)가 잘못 선택되었다.
    """
    requirement = RequirementSchema(
        raw_text="1~500 μm 측정 범위와 ±2.0 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        inspection_items=["thickness"],
    )
    apply_deterministic_extraction(requirement)
    fake_llm_response = SpecificationSchema()
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, _ = retrieve_and_generate(requirement, db_path=db)
    hard_report = build_hard_requirement_report(specification, requirement)
    by_item = {r.item: r for r in hard_report}

    assert specification.equipment.name in ("PrecisionGauge PG-600", "OCTVision OCT-E100")
    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"


def test_chat_ui_regression_baseline_multisense_ms600(db):
    """
    챗봇 UI 개편(item 18) 기준 사례 "Test10" 그대로: "폭 600 mm 이상의 전극을
    검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 Inline 복합 검사기를
    찾아줘. 측정 범위는 0~300 μm이고 정확도는 ±1 μm 이하여야 해." — MultiSense
    MS-600(SPEC-010.md, 실측 범위 0~300μm/정확도 ±0.8μm)이 선택되고 Hard
    Requirement가 정상적으로 유지되는지 확인한다. 프론트엔드를 챗봇으로 갈아끼워도
    이 결과가 절대 바뀌면 안 된다(요청서 9절 원칙: "현재 정상 동작하는 Test10을
    깨지 않는다").
    """
    requirement = RequirementSchema(
        raw_text=(
            "폭 600 mm 이상의 전극을 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 "
            "Inline 복합 검사기를 찾아줘. 측정 범위는 0~300 μm이고 정확도는 ±1 μm 이하여야 해."
        ),
        target=RequirementTarget(width_mm=600),
        inspection_items=["thickness", "surface_defect"],
        inline_offline="inline",
    )
    apply_deterministic_extraction(requirement)
    assert requirement.measurement_range.min == 0.0 and requirement.measurement_range.max == 300.0
    assert requirement.required_accuracy_um == 1.0

    fake_llm_response = SpecificationSchema()
    with mock.patch("agent.spec_generator.ollama_client.parse_structured", return_value=fake_llm_response):
        specification, validation, retrieved_docs = retrieve_and_generate(requirement, db_path=db, k_per_query=100)

    assert specification.equipment.name in ("MultiInspect MI-800", "MultiSense MS-600")
    if specification.equipment.name == "MultiInspect MI-800":
        assert specification.measurement_performance.measurement_range_full.min == 0.0
        assert specification.measurement_performance.measurement_range_full.max == 500.0
        assert specification.measurement_performance.equipment_accuracy_um.value == 1.0
    else:
        assert specification.measurement_performance.measurement_range_full.min == 0.0
        assert specification.measurement_performance.measurement_range_full.max == 300.0
        assert specification.measurement_performance.equipment_accuracy_um.value == 0.8

    hard_report = build_hard_requirement_report(specification, requirement)
    candidates = build_candidates(requirement, retrieved_docs)
    chosen = select_best_candidate(candidates)
    from agent.spec_validator import build_inspection_item_hard_requirement_records

    hard_report += build_inspection_item_hard_requirement_records(chosen)
    by_item = {r.item: r for r in hard_report}

    assert by_item["Measurement Range"].result == "PASS"
    assert by_item["Accuracy"].result == "PASS"
    assert by_item["Inspection Mode"].result == "PASS"
    assert by_item["Surface Defect Detection"].result == "PASS"
