"""
CandidateMatcher — RAG 검색 결과(retrieved_docs)를 문서(장비) 단위로 그룹화하고,
측정 범위/정확도/최소 검출 결함 크기 같은 hard requirement를 실제 원문에서 추출해
agent.units의 순수 비교 함수(evaluate_hard_requirements/range_covers)로 PASS/FAIL을
판정한다.

핵심 원칙: LLM은 이 판정에 전혀 관여하지 않는다. 이미 agent.spec_retriever가
retrieved_docs를 만드는 과정에서 range_boost/identity_chunk 로직으로 각 후보 문서의
관련 chunk를 모아 놓았으므로, 여기서 벡터 DB를 다시 스캔하지 않고 그 결과를 그대로
입력으로 받는다(중복 구현 방지) — 평가에 필요한 chunk가 retrieved_docs에 없으면
evaluate_hard_requirements가 UNKNOWN으로 정직하게 표시한다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document

from . import categorical_match, units
from .schemas import CandidateEquipment, CandidateFieldMatch, RequirementSchema, SourceRef
from .spec_retriever import source_label

_MANUFACTURER_RE = re.compile(r"(?:Manufacturer|제조사)\s*[:：]\s*(.+)", re.IGNORECASE)
_MODEL_RE = re.compile(r"(?:^|\n)[-*]?\s*Model\s*[:：]\s*(.+)", re.IGNORECASE)
# Inspection Mode/Measurement Type/Measurement Principle은 sample_specs에서
# markdown 표가 아니라 "## General" 절의 불릿 리스트로 쓰인다(Manufacturer/Model과
# 동일한 형태) — 그래서 _extract_table_rows가 아니라 Manufacturer/Model과 같은
# 방식(정규식 직접 매칭)으로 추출한다.
_INSPECTION_MODE_RE = re.compile(r"(?:^|\n)[-*]?\s*Inspection Mode\s*[:：]\s*(.+)", re.IGNORECASE)
_MEASUREMENT_TYPE_RE = re.compile(r"(?:^|\n)[-*]?\s*Measurement Type\s*[:：]\s*(.+)", re.IGNORECASE)
_MEASUREMENT_PRINCIPLE_RE = re.compile(r"(?:^|\n)[-*]?\s*Measurement Principle\s*[:：]\s*(.+)", re.IGNORECASE)
# "Minimum Detectable Defect"는 sample_specs에서 표(SPEC-001/005/006/007/008/009/010)와
# 불릿(SPEC-002: "- Minimum Detectable Defect: 5 μm") 두 형태가 섞여 있으므로, 표는
# 기존 라벨 힌트 매칭으로, 불릿은 Inspection Mode/Measurement Principle과 동일한 방식으로
# 별도 정규식을 둔다.
_MINIMUM_DEFECT_RE = re.compile(r"(?:^|\n)[-*]?\s*Minimum Detectable Defect\s*[:：]\s*(.+)", re.IGNORECASE)

_RANGE_LABEL_HINTS = ("measurement range", "측정 범위", "측정범위")
_ACCURACY_LABEL_HINTS = ("accuracy", "정확도")
_DEFECT_SIZE_LABEL_HINTS = ("minimum detectable defect", "minimum defect size", "최소 검출", "최소 결함")


def _is_range_label(label_lower: str) -> bool:
    """
    "Measurement Range"라는 정확한 문구가 없어도 "Thickness Range"/"Vertical Range"
    처럼 측정 범위를 가리키는 표 라벨이 실제 사양서에 흔히 쓰인다(sample_specs
    SPEC-003/004/007/008에서 실측됨) — 이런 라벨은 _RANGE_LABEL_HINTS의 고정 문구와
    매칭되지 않아 값이 문서에 명확히 있는데도 UNKNOWN으로 잘못 판정되는 버그가
    있었다. 이 corpus의 정상적인 범위 라벨은 전부 "Range"/"범위"로 끝나므로(다른
    무관한 "…Range" 표 라벨이 같은 표에 섞여 있는 사례는 없음), 고정 문구 힌트에
    더해 라벨이 "range"/"범위"로 끝나는지도 함께 확인한다.
    """
    if any(h in label_lower for h in _RANGE_LABEL_HINTS):
        return True
    return label_lower.endswith("range") or label_lower.endswith("범위")


def extract_manufacturer_model(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    문서 원문에서 "Manufacturer: X"/"Model: Y" 같은 명시적 라인을 정규식으로 뽑는다.
    LLM 없이 결정론적으로 동작하며, spec_generator._fallback_equipment_identity()와
    이 모듈의 후보 식별 양쪽에서 공유해 동일한 로직을 중복 구현하지 않는다.
    """
    manufacturer = None
    model = None
    m = _MANUFACTURER_RE.search(text)
    if m:
        manufacturer = m.group(1).strip()
    m = _MODEL_RE.search(text)
    if m:
        model = m.group(1).strip()
    return manufacturer, model


def _extract_table_rows(text: str) -> List[Tuple[str, str]]:
    """
    "| Item | Specification |" 형식의 markdown 표 행을 (label, value) 쌍으로 뽑는다.
    헤더 행("Item"/"구분")과 구분선 행("---")은 제외한다.
    """
    rows: List[Tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, value = cells
        if not label or not value:
            continue
        if label.lower() in ("item", "구분", "항목"):
            continue
        if set(value) <= {"-"}:
            continue
        rows.append((label, value))
    return rows


class _CandidateFact:
    """후보 문서 하나에서 추출한 값과, 그 값이 어느 chunk(Document)에서 나왔는지."""

    def __init__(self) -> None:
        self.manufacturer: Optional[str] = None
        self.model: Optional[str] = None
        self.range: Optional[Tuple[float, float, str]] = None
        self.range_doc: Optional[Document] = None
        self.range_text: Optional[str] = None
        self.accuracy: Optional[Tuple[float, str]] = None
        self.accuracy_doc: Optional[Document] = None
        self.accuracy_text: Optional[str] = None
        self.inspection_mode: Optional[str] = None
        self.inspection_mode_doc: Optional[Document] = None
        self.inspection_mode_text: Optional[str] = None
        self.measurement_method: Optional[str] = None
        self.measurement_method_doc: Optional[Document] = None
        self.measurement_method_text: Optional[str] = None
        self.measurement_principle: Optional[str] = None
        self.measurement_principle_doc: Optional[Document] = None
        self.measurement_principle_text: Optional[str] = None
        self.defect_size: Optional[Tuple[float, str]] = None
        self.defect_size_doc: Optional[Document] = None
        self.defect_size_text: Optional[str] = None


def _extract_candidate_fact(docs: List[Document]) -> _CandidateFact:
    fact = _CandidateFact()
    for doc in docs:
        text = doc.page_content
        if fact.manufacturer is None or fact.model is None:
            manufacturer, model = extract_manufacturer_model(text)
            fact.manufacturer = fact.manufacturer or manufacturer
            fact.model = fact.model or model

        if fact.inspection_mode is None:
            m = _INSPECTION_MODE_RE.search(text)
            if m:
                canonical = categorical_match.extract_inspection_mode(m.group(1))
                if canonical is not None:
                    fact.inspection_mode = canonical
                    fact.inspection_mode_doc = doc
                    fact.inspection_mode_text = f"Inspection Mode: {m.group(1).strip()}"

        if fact.measurement_method is None:
            m = _MEASUREMENT_TYPE_RE.search(text)
            if m:
                canonical = categorical_match.extract_measurement_method(m.group(1))
                if canonical is not None:
                    fact.measurement_method = canonical
                    fact.measurement_method_doc = doc
                    fact.measurement_method_text = f"Measurement Type: {m.group(1).strip()}"

        if fact.measurement_principle is None:
            m = _MEASUREMENT_PRINCIPLE_RE.search(text)
            if m:
                canonical = categorical_match.extract_measurement_principle(m.group(1))
                if canonical is not None:
                    fact.measurement_principle = canonical
                    fact.measurement_principle_doc = doc
                    fact.measurement_principle_text = f"Measurement Principle: {m.group(1).strip()}"

        if fact.defect_size is None:
            m = _MINIMUM_DEFECT_RE.search(text)
            if m:
                value_unit = units.parse_value_unit(m.group(1))
                if value_unit is not None:
                    fact.defect_size = value_unit
                    fact.defect_size_doc = doc
                    fact.defect_size_text = f"Minimum Detectable Defect: {m.group(1).strip()}"

        for label, value in _extract_table_rows(text):
            label_lower = label.lower()
            if fact.range is None and _is_range_label(label_lower):
                range_result = units.parse_range(value)
                if range_result is not None:
                    fact.range = range_result
                    fact.range_doc = doc
                    fact.range_text = f"{label}: {value}"
            if fact.accuracy is None and any(h in label_lower for h in _ACCURACY_LABEL_HINTS):
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    fact.accuracy = value_unit
                    fact.accuracy_doc = doc
                    fact.accuracy_text = f"{label}: {value}"
            if fact.defect_size is None and any(h in label_lower for h in _DEFECT_SIZE_LABEL_HINTS):
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    fact.defect_size = value_unit
                    fact.defect_size_doc = doc
                    fact.defect_size_text = f"{label}: {value}"
    return fact


def _source_ref(doc: Document) -> SourceRef:
    return SourceRef(
        document=source_label(doc),
        section=doc.metadata.get("item") or doc.metadata.get("category"),
        chunk_id=doc.metadata.get("chunk_id"),
        source_type=doc.metadata.get("source_type"),
    )


def _required_range(requirement: RequirementSchema) -> Optional[Tuple[float, float, str]]:
    r = requirement.measurement_range
    if r is None or r.min is None or r.max is None:
        return None
    return r.min, r.max, r.unit or "um"


def _required_accuracy(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    if requirement.accuracy is not None and requirement.accuracy.value is not None:
        return requirement.accuracy.value, requirement.accuracy.unit or "um", requirement.accuracy.operator or "<="
    if requirement.required_accuracy_um is not None:
        return requirement.required_accuracy_um, "um", "<="
    return None


def _required_defect_size(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    """사용자가 요구한 최소 검출 결함 크기 — 장비가 "이 크기 이하의 결함까지" 검출할 수
    있어야 한다는 뜻이므로 accuracy와 동일하게 operator는 항상 "<="다(작을수록 더
    미세한 결함까지 잡아낸다는 의미이므로 후보의 실측값이 요구값보다 작거나 같아야 PASS)."""
    if requirement.minimum_defect_size is not None and requirement.minimum_defect_size.value is not None:
        return (
            requirement.minimum_defect_size.value,
            requirement.minimum_defect_size.unit or "um",
            requirement.minimum_defect_size.operator or "<=",
        )
    if requirement.minimum_defect_size_um is not None:
        return requirement.minimum_defect_size_um, "um", "<="
    return None


def build_candidates(requirement: RequirementSchema, retrieved_docs: List[Document]) -> List[CandidateEquipment]:
    """
    retrieved_docs를 문서(장비) 단위로 그룹화하고, 각 후보의 측정 범위/정확도를
    hard requirement로 PASS/FAIL 판정한다 — "LLM이 PASS/FAIL을 임의로 판단해서는
    안 된다"는 원칙에 따라 agent.units.evaluate_hard_requirements를 그대로 재사용한다.
    """
    by_source: Dict[str, List[Document]] = defaultdict(list)
    for doc in retrieved_docs:
        by_source[source_label(doc)].append(doc)

    required_range = _required_range(requirement)
    required_accuracy = _required_accuracy(requirement)
    required_defect_size = _required_defect_size(requirement)

    candidates: List[CandidateEquipment] = []
    for idx, (source, docs) in enumerate(sorted(by_source.items()), start=1):
        fact = _extract_candidate_fact(docs)
        matches: List[CandidateFieldMatch] = []

        if required_range is not None:
            candidate_range = fact.range
            try:
                ok, _reasons = units.evaluate_hard_requirements(required_range=required_range, candidate_range=candidate_range)
            except units.UnitError:
                # 후보 문서의 범위 단위가 요구 범위와 차원이 달라(예: 시간 vs 길이)
                # 아예 비교할 수 없는 경우 — FAIL로 단정하지 않고 정보 없음과
                # 동일하게 UNKNOWN으로 취급한다(_range_boost_docs와 동일한 방어 패턴).
                ok, candidate_range = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_range is None else "FAIL")
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Range",
                    field_key="measurement_range",
                    hard=True,
                    requirement_value=required_range[1],
                    requirement_unit=required_range[2],
                    operator="<=",
                    found_value=candidate_range[1] if candidate_range else None,
                    found_min=candidate_range[0] if candidate_range else None,
                    found_unit=candidate_range[2] if candidate_range else None,
                    result=result,
                    evidence_text=fact.range_text,
                    source=_source_ref(fact.range_doc) if fact.range_doc else None,
                )
            )

        if required_accuracy is not None:
            candidate_accuracy = fact.accuracy
            req_value, req_unit, operator = required_accuracy
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_accuracy, candidate_accuracy=candidate_accuracy
                )
            except units.UnitError:
                # 후보 문서의 정확도 단위가 요구 조건과 차원이 달라(예: % vs um)
                # 비교 자체가 불가능한 경우 — FAIL로 단정하지 않고 UNKNOWN으로 취급한다.
                ok, candidate_accuracy = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_accuracy is None else "FAIL")
            matches.append(
                CandidateFieldMatch(
                    item="Accuracy",
                    field_key="accuracy",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_accuracy[0] if candidate_accuracy else None,
                    found_unit=candidate_accuracy[1] if candidate_accuracy else None,
                    result=result,
                    evidence_text=fact.accuracy_text,
                    source=_source_ref(fact.accuracy_doc) if fact.accuracy_doc else None,
                )
            )

        if required_defect_size is not None:
            candidate_defect_size = fact.defect_size
            req_value, req_unit, operator = required_defect_size
            try:
                # evaluate_hard_requirements의 required_accuracy/candidate_accuracy 파라미터는
                # "(value, unit, operator) vs (value, unit)를 operator 방향으로 비교"하는 범용
                # 로직이라 accuracy 전용이 아니다 — 결함 크기도 동일한 형태(값이 작을수록
                # 우수, operator="<=")이므로 그대로 재사용해 비교 로직을 중복 구현하지 않는다.
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_defect_size, candidate_accuracy=candidate_defect_size
                )
            except units.UnitError:
                ok, candidate_defect_size = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_defect_size is None else "FAIL")
            matches.append(
                CandidateFieldMatch(
                    item="Minimum Defect Size",
                    field_key="minimum_defect_size",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_defect_size[0] if candidate_defect_size else None,
                    found_unit=candidate_defect_size[1] if candidate_defect_size else None,
                    result=result,
                    evidence_text=fact.defect_size_text,
                    source=_source_ref(fact.defect_size_doc) if fact.defect_size_doc else None,
                )
            )

        # Inspection Mode(Inline/Offline)/Measurement Type(Contact/Non-contact)/
        # Measurement Principle — 숫자가 아니라 범주형 값이므로 agent.categorical_match로
        # 정규화한 문자열을 그대로(==) 비교한다. 사용자가 해당 조건을 요구하지 않았으면
        # (requirement.X is None) 애초에 평가 목록에 넣지 않는다 — Range/Accuracy와
        # 동일한 원칙("요구하지 않은 조건을 임의로 채점하지 않는다").
        if requirement.inline_offline is not None:
            candidate_mode = fact.inspection_mode
            if candidate_mode is None:
                mode_result = "UNKNOWN"
            elif candidate_mode == requirement.inline_offline:
                mode_result = "PASS"
            else:
                mode_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Inspection Mode",
                    field_key="inline_offline",
                    hard=True,
                    requirement_text=requirement.inline_offline,
                    found_text=candidate_mode,
                    result=mode_result,
                    evidence_text=fact.inspection_mode_text,
                    source=_source_ref(fact.inspection_mode_doc) if fact.inspection_mode_doc else None,
                )
            )

        if requirement.measurement_method is not None:
            candidate_method = fact.measurement_method
            if candidate_method is None:
                method_result = "UNKNOWN"
            elif candidate_method == requirement.measurement_method:
                method_result = "PASS"
            else:
                method_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Method",
                    field_key="measurement_method",
                    hard=True,
                    requirement_text=requirement.measurement_method,
                    found_text=candidate_method,
                    result=method_result,
                    evidence_text=fact.measurement_method_text,
                    source=_source_ref(fact.measurement_method_doc) if fact.measurement_method_doc else None,
                )
            )

        if requirement.measurement_principle is not None:
            # RequirementParser가 이미 canonical 라벨로 채우지만, 조건 선택 UI 등
            # 다른 경로로 자유 문자열이 들어올 수 있으므로 여기서도 한 번 더 정규화한다.
            required_principle = (
                categorical_match.extract_measurement_principle(requirement.measurement_principle)
                or requirement.measurement_principle
            )
            candidate_principle = fact.measurement_principle
            if candidate_principle is None:
                principle_result = "UNKNOWN"
            elif candidate_principle == required_principle:
                principle_result = "PASS"
            else:
                principle_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Principle",
                    field_key="measurement_principle",
                    hard=True,
                    requirement_text=required_principle,
                    found_text=candidate_principle,
                    result=principle_result,
                    evidence_text=fact.measurement_principle_text,
                    source=_source_ref(fact.measurement_principle_doc) if fact.measurement_principle_doc else None,
                )
            )

        pass_count = sum(1 for m in matches if m.result == "PASS")
        fail_count = sum(1 for m in matches if m.result == "FAIL")
        unknown_count = sum(1 for m in matches if m.result == "UNKNOWN")
        # FAIL이 없어도 UNKNOWN만 있는(=아무것도 확인되지 않은) 후보를 "충족"으로
        # 표시하면 안 된다 — 검사할 hard requirement가 아예 없는 경우(matches=[])는
        # 여전히 공허하게(vacuously) True다. 이 조건이 없으면 근거가 전혀 없는
        # 후보가 "확인됨(PASS)"으로 표시되고, 실제 FAIL 증거가 있는 후보보다
        # select_best_candidate()에서 우선 선택되는 문제가 있었다(실측됨).
        hard_requirements_pass = fail_count == 0 and unknown_count == 0
        match_score = 100.0 * pass_count / len(matches) if matches else 0.0

        candidates.append(
            CandidateEquipment(
                candidate_id=f"cand-{idx}",
                manufacturer=fact.manufacturer,
                model=fact.model,
                source_document=source,
                matches=matches,
                match_score=match_score,
                hard_requirements_pass=hard_requirements_pass,
                unknown_count=unknown_count,
                fail_count=fail_count,
                pass_count=pass_count,
            )
        )

    return candidates


def select_best_candidate(candidates: List[CandidateEquipment]) -> Optional[CandidateEquipment]:
    """
    PASS 후보(hard_requirements_pass=True)를 우선 선정하고, 그중에서도 pass_count가
    높은 후보를 고른다. PASS한 후보가 하나도 없으면(전부 FAIL/UNKNOWN) 그래도
    상대적으로 가장 나은 후보를 반환한다 — 반환된 후보가 hard_requirements_pass=False일
    수 있으므로, 호출부는 이 값을 반드시 확인하고 사용자에게 투명하게 보여줘야 한다
    (LLM이 조용히 부적합한 후보를 골라 감추는 상황을 막기 위함).
    """
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: (not c.hard_requirements_pass, -c.pass_count, c.fail_count))[0]
