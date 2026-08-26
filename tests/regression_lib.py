"""
Ground Truth 기반 자동 Regression Test 시스템의 공유 헬퍼.

tests/ground_truth/regression_cases.json에 있는 테스트 데이터(T001~T015)를
읽어서 실제 파이프라인(RAG 검색 -> Requirement Parsing -> Candidate 추출 ->
Hard Requirement 검증 -> Ranking)으로 실행하고, 실패 시 원인을 바로 알 수 있는
사람이 읽기 쉬운 리포트를 만든다. pytest 모듈이 아니라 순수 헬퍼 모듈이며,
tests/test_regression.py / tests/test_requirements.py가 이 모듈을 함께 쓴다
(테스트 데이터와 테스트 코드 분리 원칙).

Ollama가 없는 환경이므로 임베딩은 fake-hash 벡터로 스텁한다(기존 테스트
파일들과 동일 패턴, tests/test_hard_requirement_pipeline_fixes.py 등 참고).
LLM 파싱도 "빈 응답"으로 스텁해 worst-case(LLM이 아무것도 못 채운 경우)를
가정한다 — deterministic 추출 계층이 raw_text만으로 올바르게 채우는지를
가장 엄격하게 검증하기 위함이다. 실제 서비스에서는 LLM이 일부를 채워주므로
이보다 결과가 더 좋을 수는 있어도 나쁠 수는 없다.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import unittest.mock as mock
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from langchain_community.embeddings import OllamaEmbeddings

from agent import spec_retriever
from agent.candidate_matcher import CandidateEquipment, build_candidates, select_best_candidate
from agent.requirement_parser import parse_requirement_text
from agent.schemas import RequirementSchema

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth" / "regression_cases.json"


def load_regression_cases() -> List[Dict[str, Any]]:
    data = json.loads(_GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def _fake_vector(text: str, dim: int = 32) -> List[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    arr = np.frombuffer((h * (dim // len(h) + 1))[: dim * 4], dtype=np.uint32).astype(np.float64)
    return (arr / arr.max()).tolist()


@contextlib.contextmanager
def patched_embeddings():
    """OllamaEmbeddings.embed_documents/embed_query를 fake-hash 벡터로 스텁한다.
    빌드(build_fake_embedding_db)와 검색(run_case -> retrieve_for_requirement)
    양쪽 다 이 컨텍스트 안에서 실행되어야 한다 — 검색은 매번 새 OllamaEmbeddings
    인스턴스를 만들므로, 빌드 시점에만 패치하면 검색 시점에 실제 Ollama 서버로
    접속을 시도해 실패한다."""
    with mock.patch.object(OllamaEmbeddings, "embed_documents", lambda self, texts: [_fake_vector(t) for t in texts]), \
         mock.patch.object(OllamaEmbeddings, "embed_query", lambda self, text: _fake_vector(text)):
        yield


def build_fake_embedding_db(db_path: str) -> str:
    """sample_specs/ 전체(50개)로 Chroma DB를 새로 만든다. 호출 시점에 이미
    patched_embeddings() 컨텍스트 안에 있어야 한다."""
    import shutil

    from build_rag_ollama import build_vector_db

    shutil.rmtree(db_path, ignore_errors=True)
    build_vector_db(str(_REPO_ROOT / "sample_specs"), db_path, rebuild=True)
    return db_path


def parse_with_empty_llm(user_text: str) -> RequirementSchema:
    """LLM이 아무것도 채우지 못했다고 가정(worst case)하고 deterministic 추출
    계층만으로 파싱한다."""
    with mock.patch("agent.requirement_parser.ollama_client.parse_structured", return_value=RequirementSchema()):
        return parse_requirement_text(user_text)


def candidate_name(c: CandidateEquipment) -> str:
    return f"{c.manufacturer or '?'} {c.model or '?'}"


class RegressionRunResult:
    """한 케이스를 실제 파이프라인으로 돌린 결과 + 실패 원인 리포트에 필요한 정보."""

    def __init__(
        self,
        requirement: RequirementSchema,
        candidates: List[CandidateEquipment],
        chosen: Optional[CandidateEquipment],
    ) -> None:
        self.requirement = requirement
        self.candidates = candidates
        self.chosen = chosen
        self.by_name: Dict[str, CandidateEquipment] = {candidate_name(c): c for c in candidates}

    def candidate(self, name: str) -> Optional[CandidateEquipment]:
        return self.by_name.get(name)


def run_case(case: Dict[str, Any], db_path: str, k_per_query: int = 100) -> RegressionRunResult:
    requirement = parse_with_empty_llm(case["user_query"])
    retrieved_docs = spec_retriever.retrieve_for_requirement(requirement, db_path=db_path, k_per_query=k_per_query)
    candidates = build_candidates(requirement, retrieved_docs)
    chosen = select_best_candidate(candidates)
    return RegressionRunResult(requirement, candidates, chosen)


def _get_dotted(obj: Any, dotted_path: str) -> Any:
    value = obj
    for part in dotted_path.split("."):
        if value is None:
            return None
        value = getattr(value, part, None)
    return value


def check_requirement_field(requirement: RequirementSchema, field: str, expected: Any) -> Optional[str]:
    """expected_requirement의 필드 하나를 검증한다. 문제가 없으면 None, 있으면
    사람이 읽을 수 있는 불일치 설명 문자열을 반환한다."""
    if field == "inspection_items":
        actual = set(requirement.inspection_items)
        if actual != set(expected):
            return f"inspection_items 불일치: expected={sorted(expected)} actual={sorted(actual)}"
        return None
    if field == "inspection_categories":
        actual = set(requirement.inspection_categories)
        if actual != set(expected):
            return f"inspection_categories 불일치: expected={sorted(expected)} actual={sorted(actual)}"
        return None
    if field in ("measurement_range", "accuracy", "measurement_speed", "minimum_defect_size"):
        actual_obj = getattr(requirement, field)
        if expected is None:
            if actual_obj is not None:
                return f"{field}: expected=None(사용자가 요구하지 않음) actual={actual_obj!r}"
            return None
        if actual_obj is None:
            return f"{field}: expected={expected!r} actual=None"
        if field == "measurement_range":
            if actual_obj.min != expected.get("min") or actual_obj.max != expected.get("max"):
                return f"{field}: expected={expected!r} actual=(min={actual_obj.min}, max={actual_obj.max})"
            return None
        if actual_obj.value != expected.get("value") or actual_obj.operator != expected.get("operator"):
            return (
                f"{field}: expected(value={expected.get('value')}, operator={expected.get('operator')}) "
                f"actual(value={actual_obj.value}, operator={actual_obj.operator})"
            )
        return None
    # 나머지는 dotted path(예: target.width_mm)로 단순 값 비교.
    actual = _get_dotted(requirement, field)
    if actual != expected:
        return f"{field}: expected={expected!r} actual={actual!r}"
    return None


def format_case_failure(case: Dict[str, Any], result: RegressionRunResult, problems: List[str]) -> str:
    """실패 원인을 바로 알 수 있는 리포트를 만든다(요청서 5절 형식)."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"TEST: {case['test_id']} — {case['name']}")
    lines.append("=" * 70)
    lines.append("")
    lines.append("User Query:")
    lines.append(f"  {case['user_query']}")
    lines.append("")
    lines.append("Expected Requirement:")
    for field, expected in case["expected_requirement"].items():
        lines.append(f"  {field} = {expected!r}")
    lines.append("")
    lines.append("Actual Requirement:")
    req = result.requirement
    lines.append(f"  target.width_mm = {req.target.width_mm!r}")
    lines.append(f"  inline_offline = {req.inline_offline!r}")
    lines.append(f"  inspection_items = {req.inspection_items!r}")
    lines.append(f"  inspection_categories = {req.inspection_categories!r}")
    lines.append(f"  measurement_range = {req.measurement_range!r}")
    lines.append(f"  accuracy = {req.accuracy!r}")
    lines.append(f"  measurement_speed = {req.measurement_speed!r}")
    lines.append(f"  minimum_defect_size = {req.minimum_defect_size!r}")
    lines.append(f"  required_accuracy_um = {req.required_accuracy_um!r}")
    lines.append("")
    lines.append(f"Candidates found: {len(result.candidates)}")
    if result.chosen is not None:
        lines.append(
            f"Chosen: {candidate_name(result.chosen)} "
            f"(status={result.chosen.status}, pass={result.chosen.pass_count}, "
            f"unknown={result.chosen.unknown_count}, fail={result.chosen.fail_count})"
        )
        for m in result.chosen.matches:
            lines.append(f"    - {m.item:28s} {m.result:8s} {m.evidence_text or ''}")
    else:
        lines.append("Chosen: None (후보 없음)")
    lines.append("")
    lines.append("Ranked candidates (top 5):")
    ranked = sorted(
        result.candidates,
        key=lambda c: ({"PASS": 0, "PARTIAL": 1, "FAIL": 2}[c.status], -c.pass_count, c.unknown_count, c.fail_count),
    )
    for c in ranked[:5]:
        lines.append(f"  {c.status:8s} pass={c.pass_count} unknown={c.unknown_count} fail={c.fail_count}  {candidate_name(c)} ({c.source_document})")
    lines.append("")
    lines.append("FAILED:")
    for p in problems:
        lines.append(f"  - {p}")
    return "\n".join(lines)
