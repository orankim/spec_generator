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
from collections import defaultdict
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


class AmbiguousCandidateNameError(ValueError):
    """
    동일한 Equipment Name(Manufacturer + Model)을 가진 후보가 corpus에 둘 이상
    있을 때 발생한다. sample_specs/SPEC-044.md와 SPEC-051.md가 우연히 둘 다
    "MultiInspect MI-800"을 쓰는 사례가 실제로 발견되었다(Flaky Test 조사 중
    발견) — 예전에는 by_name 딕셔너리가 이름으로 뒤에 나온 후보로 조용히
    overwrite해서 어느 문서를 검증하는지 알 수 없었다. 이제는 이름이 중복될 때
    spec_id(예: "SPEC-051.md")를 함께 넘겨 어느 후보를 가리키는지 명시하지
    않으면 이 예외를 던져 문제를 조용히 감추지 않는다.
    """


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
        # 이름 하나에 후보가 여러 개일 수 있으므로(중복 장비명) list로 보관한다
        # — 뒤에 나온 후보가 앞의 후보를 조용히 덮어쓰지 않게 한다. 순서는
        # candidates(= build_candidates가 만든, source 파일명 기준 결정론적
        # 순서)를 그대로 따른다.
        self.by_name: Dict[str, List[CandidateEquipment]] = defaultdict(list)
        for c in candidates:
            self.by_name[candidate_name(c)].append(c)

    def candidates_by_name(self, name: str) -> List[CandidateEquipment]:
        return list(self.by_name.get(name, []))

    def candidate(self, name: str, spec_id: Optional[str] = None) -> Optional[CandidateEquipment]:
        """
        이름으로 후보를 찾는다. 동일 이름의 후보가 둘 이상이면 spec_id(예:
        "SPEC-051.md")로 어느 것을 가리키는지 명시해야 한다 — 명시하지 않으면
        AmbiguousCandidateNameError를 던진다(예전처럼 마지막 후보로 조용히
        결정하지 않는다).
        """
        matches = self.by_name.get(name, [])
        if spec_id is not None:
            for c in matches:
                if c.source_document == spec_id:
                    return c
            return None
        if len(matches) > 1:
            raise AmbiguousCandidateNameError(
                f"'{name}'이라는 이름의 후보가 {len(matches)}개 있습니다 "
                f"({', '.join(c.source_document for c in matches)}). "
                "regression_cases.json의 candidate_spec_ids로 어느 SPEC 문서를 "
                "가리키는지 명시하세요."
            )
        return matches[0] if matches else None


def run_case(case: Dict[str, Any], db_path: str, k_per_query: int = 1000) -> RegressionRunResult:
    """
    k_per_query 기본값 1000(이전 100) — 이 회귀 테스트는 실제 Recall(k=15,
    agent/spec_retriever.py 프로덕션 기본값)을 검증하는 것이 아니라, corpus
    전체에서 후보를 빠짐없이 찾았다는 가정 하에 Hard Requirement 판정/랭킹
    로직만 독립적으로 검증하는 것이 목적이다. 100은 corpus가 52개 문서
    (383 chunk)였을 때는 "사실상 전체"였지만, SPEC-100개 확장(100개 문서,
    736 chunk) 이후에는 fake-hash 임베딩(patched_embeddings) 특유의 의미
    없는 유사도 순위 때문에 일부 정답 문서가 top-100 밖으로 밀려날 수 있다
    (실측: T022 "PrecisionGauge PG-100"). corpus 규모가 커져도 이 테스트의
    원래 취지(=검색 범위를 랭킹 로직 검증의 변수로 만들지 않는다)를 유지하려면
    k도 그만큼 올려야 한다 — 실제 Recall 재검증(Phase 2)과는 별개다.
    """
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
