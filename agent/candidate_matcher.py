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
from .schemas import CandidateEquipment, CandidateEquipmentFact, CandidateFieldMatch, RequirementSchema, SourceRef
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
# "Defect Types"도 Minimum Detectable Defect와 동일하게 표/불릿 두 형태가 섞여 있다.
_DEFECT_TYPES_RE = re.compile(r"(?:^|\n)[-*]?\s*Defect Types\s*[:：]\s*(.+)", re.IGNORECASE)
# sample_specs SPEC-003/004처럼 "## Defect Inspection" 절 바로 아래 "- Not Supported"만
# 있는 경우 — 결함 검사 자체를 지원하지 않는다는 명시적 부정 신호. heading 기반
# chunking(build_rag_ollama.py)이 이 heading을 chunk 시작에 그대로 남겨두므로, heading과
# "Not Supported"가 같은 chunk 안에서 가깝게 나타나는지로 판정한다.
_DEFECT_INSPECTION_NOT_SUPPORTED_RE = re.compile(
    r"#{1,3}\s*Defect Inspection\s*\n+\s*[-*]?\s*Not Supported\b", re.IGNORECASE
)
# SPEC-006처럼 "## Thickness Measurement\n\n- Not Supported"로 두께 측정 자체를
# 지원하지 않는다고 명시하는 경우 — Defect Inspection과 동일한 패턴.
_THICKNESS_NOT_SUPPORTED_RE = re.compile(
    r"#{1,3}\s*Thickness Measurement\s*\n+\s*[-*]?\s*Not Supported\b", re.IGNORECASE
)
# "## General" 절의 불릿 리스트 형태(Manufacturer/Model/Inspection Mode 등과 동일).
_EQUIPMENT_TYPE_RE = re.compile(r"(?:^|\n)[-*]?\s*Equipment Type\s*[:：]\s*(.+)", re.IGNORECASE)
# "## Inspection Target" 절의 불릿 리스트 형태(sample_specs: "Maximum Electrode Width"/
# "Maximum Width" 두 표기가 섞여 있다).
_MAXIMUM_WIDTH_RE = re.compile(r"(?:^|\n)[-*]?\s*Maximum(?:\s+Electrode)?\s+Width\s*[:：]\s*(.+)", re.IGNORECASE)
# "## Notes" 절 본문(다음 heading 또는 문서 끝까지) — Thickness Measurement 지원
# 여부의 서술적 근거(예: "Designed for continuous inline electrode thickness
# measurement.")를 찾는 데 쓴다(문제3).
_NOTES_RE = re.compile(r"(?:^|\n)#{1,3}\s*Notes\s*\n+(.+?)(?=\n#{1,3}\s|\Z)", re.IGNORECASE | re.DOTALL)

_RANGE_LABEL_HINTS = ("measurement range", "측정 범위", "측정범위")
# "## Spatial Performance" 절(agent.candidate_matcher._extract_spatial_performance_
# fields 참고)의 "X Range"/"Y Range"는 전극 폭(가로) 같은 완전히 다른 물리량이라
# 이 아래 "주" Measurement Range(두께/깊이 축, Hard Requirement 판정에 쓰임)와
# 절대 섞이면 안 된다. RAG chunk는 "## Measurement Performance"/"## Spatial
# Performance"가 서로 다른 chunk로 나뉘고 검색 관련도 순으로 재배열될 수 있어
# (원본 문서 순서가 보장되지 않음), "Spatial Performance" chunk가 먼저 처리되면
# "X Range: 0 ~ 800 mm"(mm 단위 폭)이 fact.range에 잘못 들어가 예: "0~5000 μm
# 측정 가능?" 같은 두께 Hard Requirement를 엉뚱하게 PASS로 만드는 사고가 실제로
# 있었다(회귀 테스트 T020/QA019가 잡아냄) — X/Y/XY Resolution에 이미 있던 것과
# 동일한 원리의 제외 목록을 range에도 추가한다. "Z Range"는 값 자체는 항상
# Measurement Performance의 원본 범위와 동일하게 만들어지므로(agent.candidate_
# matcher._extract_spatial_performance_fields 쪽 데이터 생성 정책) 순서가 바뀌어도
# 결과값은 같지만, 우연에 기대지 않도록 동일한 원칙으로 함께 제외한다.
_SPATIAL_PERFORMANCE_RANGE_LABELS = ("x range", "y range", "z range")
_ACCURACY_LABEL_HINTS = ("accuracy", "정확도")
_DEFECT_SIZE_LABEL_HINTS = ("minimum detectable defect", "minimum defect size", "최소 검출", "최소 결함")
_DEFECT_TYPES_LABEL_HINTS = ("defect types",)
# "Measurement Speed"/"Line Speed"/"Maximum Line Speed" 모두 "speed"로 끝난다.
_SPEED_LABEL_HINTS = ("speed",)
# 이 corpus에서 "Resolution"은 항상 축(axis)이 붙어 나온다(Thickness/Vertical/Z/
# X/Y/XY Resolution). X/Y/XY Resolution은 측정 대상의 가로/세로(횡) 해상도라
# 장비의 "핵심 측정 성능"과는 다른 개념이므로 여기서는 제외하고, 두께/깊이
# 축을 가리키는 라벨(Thickness/Vertical/Z Resolution)만 "주 Resolution"으로
# 인정한다 — Markdown 사양서의 "Resolution" 행에 쓰인다.
_LATERAL_RESOLUTION_LABELS = ("x resolution", "y resolution", "xy resolution")


def _is_primary_resolution_label(label_lower: str) -> bool:
    if not label_lower.endswith("resolution"):
        return False
    return label_lower not in _LATERAL_RESOLUTION_LABELS


# ==========================================
# Spatial Performance(X/Y/Z Range·Resolution/FOV/Working Distance/Pixel Size) —
# sample_specs 데이터 보강과 함께 추가된 별도 절 전용 추출. 위 "주" Measurement
# Range/Resolution(Hard Requirement 판정에 쓰임, _is_range_label/_is_primary_
# resolution_label)과는 완전히 분리해서 처리한다 — 만약 이 라벨들을 기존
# `for label, value in _extract_table_rows(text):` 루프에 그냥 섞어 넣으면,
# "## Spatial Performance"의 "Z Range"/"X Resolution" 같은 라벨이 "range"/
# "resolution"으로 끝난다는 이유만으로 _is_range_label/_is_primary_resolution_label
# 매칭에 걸려 fact.range/fact.resolution(=Hard Requirement가 실제로 비교하는 값)을
# 잘못 채울 위험이 있다 — 특히 RAG chunk 순서는 원본 문서의 절 순서를 보장하지
# 않으므로(같은 후보의 chunk가 relevance 순으로 섞여 들어올 수 있음), "Measurement
# Performance"보다 "Spatial Performance" chunk가 먼저 처리되면 이 위험이 실제로
# 발생할 수 있다. 그래서 "## Spatial Performance" 절 본문만 별도로 잘라낸 뒤
# (_SPATIAL_PERFORMANCE_SECTION_RE), 그 안에서만 정확히 일치하는 라벨(대소문자
# 무시)로 값을 뽑는다 — Hard Requirement/Ranking 로직에는 전혀 영향을 주지 않는다.
_SPATIAL_PERFORMANCE_SECTION_RE = re.compile(
    r"(?:^|\n)#{1,3}\s*Spatial Performance\s*\n+(.+?)(?=\n#{1,3}\s|\Z)", re.IGNORECASE | re.DOTALL
)
# label -> _CandidateFact의 어느 속성에 저장할지. range 계열은 units.parse_range(),
# 나머지는 units.parse_value_unit()으로 파싱한다(FOV만 예외 — 아래 fov_display 참고).
# X/Y(/XY) Resolution은 여기 넣지 않는다 — 아래 _extract_candidate_fact의 공용
# table-row 루프가 "## Spatial Performance" 안팎을 가리지 않고 이미 처리한다
# (카메라 비전 계열은 이 값을 "## Measurement Performance"에 직접 적으므로).
_SPATIAL_RANGE_LABELS = {"x range": "x_range", "y range": "y_range", "z range": "z_range"}
_SPATIAL_VALUE_LABELS = {
    "z resolution": "z_resolution",
    "working distance": "working_distance",
    "pixel size": "pixel_size",
}


def _extract_spatial_performance_fields(text: str, fact: "_CandidateFact") -> None:
    m = _SPATIAL_PERFORMANCE_SECTION_RE.search(text)
    if not m:
        return
    section_text = m.group(1)
    for label, value in _extract_table_rows(section_text):
        label_lower = label.lower()
        if label_lower in _SPATIAL_RANGE_LABELS:
            attr = _SPATIAL_RANGE_LABELS[label_lower]
            if getattr(fact, attr) is None:
                range_result = units.parse_range(value)
                if range_result is not None:
                    setattr(fact, attr, range_result)
        elif label_lower in _SPATIAL_VALUE_LABELS:
            attr = _SPATIAL_VALUE_LABELS[label_lower]
            if getattr(fact, attr) is None:
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    setattr(fact, attr, value_unit)
        elif label_lower == "fov" and fact.fov_display is None:
            # FOV는 "10 x 10 mm"처럼 2축 복합 표기가 흔해 단일 수치로 쪼개지 않고
            # 사양서 원문 표기를 그대로 보존한다(schemas.CandidateEquipmentFact.
            # fov_display 참고).
            fact.fov_display = value.strip()

# requirement.inspection_items 중 "이 결함 종류를 실제로 검출하는가"로 검증 가능한
# 항목만 다룬다(thickness/coating은 사양서에 이런 형태의 명시적 목록이 없어 안전하게
# 판정할 근거가 부족하다 — 근거 없이 FAIL을 만들어내는 것을 피한다).
# "defect"는 Scratch/Contamination/Pit/Void 등 특정 이름이 없는 일반 결함 목록도
# surface_defect로 인정하기 위한 포괄 키워드다.
#
# 세부 canonical item(scratch/contamination/particle/pinhole/void/
# coating_non_uniformity/edge_crack)은 각각 자기 자신의 키워드로만 판정한다 —
# requirement.inspection_items에 세부 항목이 여러 개 있으면(예: "스크래치와 오염")
# 이 loop가 항목별로 독립적인 CandidateFieldMatch를 만들므로, 후보 장비가 그중
# 하나만 지원해도 나머지는 별도로 FAIL/UNKNOWN이 남는다(요청서 문제2: 상위
# 카테고리 하나로 뭉쳐서 판정하면 안 됨).
_INSPECTION_ITEM_DEFECT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    # 바레 "defect"/"void"는 넣지 않는다 — "void"는 별도 canonical item(자기
    # 자신의 키워드로 독립 판정)이고, 바레 "defect"는 "Edge Defect"/"Coating
    # Defect"처럼 다른 canonical item의 Defect Types 표기에도 포함돼 있어 그
    # 항목만 지원하는 후보를 surface_defect까지 PASS로 잘못 인정하게 된다.
    # 다만 qualifier가 붙은 "surface defect"는 이 corpus(SPEC-042~044 등)가
    # Defect Types 값 자체로 그대로 쓰는 표현이라 명확한 근거이므로 유지한다.
    "surface_defect": ("scratch", "crack", "pinhole", "pin hole", "particle", "contamination", "pit", "surface defect"),
    "edge_defect": ("edge",),
    "scratch": ("scratch",),
    "contamination": ("contamination", "contaminant"),
    "particle": ("particle",),
    "pinhole": ("pinhole", "pin hole"),
    "void": ("void",),
    "coating_non_uniformity": ("coating non-uniformity", "coating non uniformity", "coating nonuniformity"),
    "edge_crack": ("edge crack",),
    "coating_defect": ("coating defect",),
}
# profile_3d는 Defect Types 목록이 아니라 Equipment Type/Measurement Principle
# 서술 텍스트(agent.categorical_match.match_inspection_item_capability)로 판정한다 —
# 별도 처리이므로 위 딕셔너리에는 넣지 않는다.
_INSPECTION_ITEM_LABELS = {
    "surface_defect": "Surface Defect Detection",
    "edge_defect": "Edge Defect Detection",
    "profile_3d": "3D Profile Detection",
    "thickness": "Thickness Measurement",
    "scratch": "Scratch Detection",
    "contamination": "Contamination Detection",
    "particle": "Particle Detection",
    "pinhole": "Pin Hole Detection",
    "void": "Void Detection",
    "coating_non_uniformity": "Coating Non-uniformity Detection",
    "edge_crack": "Edge Crack Detection",
    "coating_defect": "Coating Defect Detection",
}

# 두께 측정을 실제로 지원한다는 명시적 근거 키워드 — 이 키워드가 Equipment
# Type 또는 Notes(서술문)에 있을 때만 Thickness Measurement를 PASS로 판정한다.
# "Measurement Range (Z)"/"Z Resolution"/"3D Profile" 같은 필드가 존재한다는
# 사실만으로는(=수치 범위가 있다는 것만으로는) 두께 측정 근거로 인정하지
# 않는다 — 3D Profile 전용 장비도 Z축 범위를 갖고 있어 이 필드만으로는 실제로
# "두께"를 측정하는지 구분할 수 없기 때문이다(요청서 문제3의 근본 원인).
_THICKNESS_EVIDENCE_KEYWORDS: Tuple[str, ...] = ("thickness", "두께")


def _thickness_evidence(fact: "_CandidateFact") -> Optional[Tuple[str, Optional[Document]]]:
    """Equipment Type 또는 Notes 서술문에서 두께 측정 지원의 명시적 근거를 찾는다.
    찾으면 (근거 텍스트, 근거 chunk)를, 못 찾으면 None을 반환한다."""
    for text, doc in ((fact.equipment_type_text, fact.equipment_type_doc), (fact.notes_text, fact.notes_doc)):
        if text and any(kw in text.lower() for kw in _THICKNESS_EVIDENCE_KEYWORDS):
            return text, doc
    return None


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
    if label_lower in _SPATIAL_PERFORMANCE_RANGE_LABELS:
        return False
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
        self.defect_types_text: Optional[str] = None
        self.defect_types_doc: Optional[Document] = None
        self.defect_inspection_not_supported: bool = False
        self.defect_inspection_not_supported_doc: Optional[Document] = None
        self.thickness_not_supported: bool = False
        self.thickness_not_supported_doc: Optional[Document] = None
        self.equipment_type_text: Optional[str] = None
        self.equipment_type_doc: Optional[Document] = None
        self.width_mm: Optional[float] = None
        self.width_mm_doc: Optional[Document] = None
        self.width_mm_text: Optional[str] = None
        self.speed: Optional[Tuple[float, str]] = None
        self.speed_doc: Optional[Document] = None
        self.speed_text: Optional[str] = None
        self.notes_text: Optional[str] = None
        self.notes_doc: Optional[Document] = None
        self.resolution: Optional[Tuple[float, str]] = None
        self.resolution_doc: Optional[Document] = None
        self.resolution_text: Optional[str] = None
        # Spatial Performance(위 _extract_spatial_performance_fields 참고) — 이
        # 필드들은 fact.range/fact.resolution(Hard Requirement 판정용)과 완전히
        # 독립적이며, Markdown/Word 사양서 내보내기 전용이다. 근거 doc/text는
        # equipment_fact 내보내기 화면이 필드별 출처를 별도로 표시하지 않으므로
        # (기존 range_min/resolution_value 등과 동일하게) 따로 두지 않는다.
        self.x_range: Optional[Tuple[float, float, str]] = None
        self.y_range: Optional[Tuple[float, float, str]] = None
        self.z_range: Optional[Tuple[float, float, str]] = None
        self.x_resolution: Optional[Tuple[float, str]] = None
        self.y_resolution: Optional[Tuple[float, str]] = None
        self.z_resolution: Optional[Tuple[float, str]] = None
        self.fov_display: Optional[str] = None
        self.working_distance: Optional[Tuple[float, str]] = None
        self.pixel_size: Optional[Tuple[float, str]] = None


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

        if fact.equipment_type_text is None:
            m = _EQUIPMENT_TYPE_RE.search(text)
            if m:
                fact.equipment_type_text = m.group(1).strip()
                fact.equipment_type_doc = doc

        if not fact.thickness_not_supported and _THICKNESS_NOT_SUPPORTED_RE.search(text):
            fact.thickness_not_supported = True
            fact.thickness_not_supported_doc = doc

        if fact.notes_text is None:
            m = _NOTES_RE.search(text)
            if m:
                fact.notes_text = m.group(1).strip()
                fact.notes_doc = doc

        _extract_spatial_performance_fields(text, fact)

        if fact.width_mm is None:
            m = _MAXIMUM_WIDTH_RE.search(text)
            if m:
                value_unit = units.parse_value_unit(m.group(1))
                if value_unit is not None:
                    value, unit = value_unit
                    try:
                        fact.width_mm = units.convert(value, unit, "mm")
                        fact.width_mm_doc = doc
                        fact.width_mm_text = f"Maximum Width: {m.group(1).strip()}"
                    except units.UnitError:
                        pass

        if not fact.defect_inspection_not_supported and fact.defect_types_text is None:
            if _DEFECT_INSPECTION_NOT_SUPPORTED_RE.search(text):
                fact.defect_inspection_not_supported = True
                fact.defect_inspection_not_supported_doc = doc
            else:
                m = _DEFECT_TYPES_RE.search(text)
                if m:
                    fact.defect_types_text = m.group(1).strip()
                    fact.defect_types_doc = doc

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
            if (
                fact.defect_types_text is None
                and not fact.defect_inspection_not_supported
                and any(h in label_lower for h in _DEFECT_TYPES_LABEL_HINTS)
            ):
                fact.defect_types_text = value.strip()
                fact.defect_types_doc = doc
            if fact.speed is None and any(h in label_lower for h in _SPEED_LABEL_HINTS):
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    fact.speed = value_unit
                    fact.speed_doc = doc
                    fact.speed_text = f"{label}: {value}"
            if fact.resolution is None and _is_primary_resolution_label(label_lower):
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    fact.resolution = value_unit
                    fact.resolution_doc = doc
                    fact.resolution_text = f"{label}: {value}"
            # X/Y/XY Resolution(위 _is_primary_resolution_label이 fact.resolution용
            # 으로는 일부러 제외하는 라벨) — 카메라 비전 계열 사양서는 이 값을
            # "## Measurement Performance" 표에 직접 적어 두므로(예: SPEC-006),
            # Spatial Performance 표시용으로 같은 값을 사양서 원문에 다시 중복
            # 기재하지 않고 여기서 코드로 직접 추출해 재사용한다("XY Resolution"
            # 한 값으로 X/Y 둘 다 채운다).
            if label_lower in ("x resolution", "y resolution", "xy resolution"):
                value_unit = units.parse_value_unit(value)
                if value_unit is not None:
                    if label_lower in ("x resolution", "xy resolution") and fact.x_resolution is None:
                        fact.x_resolution = value_unit
                    if label_lower in ("y resolution", "xy resolution") and fact.y_resolution is None:
                        fact.y_resolution = value_unit
    return fact


def _coating_evidence(
    fact: _CandidateFact, docs: List[Document]
) -> Tuple[Literal["PASS", "FAIL", "UNKNOWN"], Optional[str], Optional[str], Optional[Document]]:
    """
    "coating" 포괄 검사 항목 판정:
    - 명시적 미지원 ("Coating Inspection: Not Supported" 등) -> FAIL
    - 명시적 지원 (Equipment Type, Defect Types, Notes 또는 본문에서 Coating Inspection/Defect/Thickness/Non-uniformity 언급) -> PASS
    - 정보 없음 -> UNKNOWN
    """
    for doc in docs:
        text = doc.page_content
        text_lower = text.lower()
        if "coating inspection: not supported" in text_lower or "coating defect: not supported" in text_lower:
            return "FAIL", "Not Supported", "Coating Inspection: Not Supported", doc

    if fact.equipment_type_text and "coating" in fact.equipment_type_text.lower():
        return "PASS", fact.equipment_type_text, f"Equipment Type: {fact.equipment_type_text}", fact.equipment_type_doc

    if fact.defect_types_text and "coating" in fact.defect_types_text.lower():
        return "PASS", fact.defect_types_text, f"Defect Types: {fact.defect_types_text}", fact.defect_types_doc

    if fact.notes_text and "coating" in fact.notes_text.lower():
        return "PASS", fact.notes_text, f"Notes: {fact.notes_text}", fact.notes_doc

    coating_pass_phrases = (
        "coating inspection",
        "coating thickness inspection",
        "coating defect inspection",
        "coating non-uniformity inspection",
        "coating defect",
        "coating non-uniformity",
        "coating thickness",
        "designed for coating",
    )

    for doc in docs:
        text = doc.page_content
        text_lower = text.lower()
        for phrase in coating_pass_phrases:
            if phrase in text_lower:
                for line in text.splitlines():
                    if phrase in line.lower() and "not supported" not in line.lower():
                        return "PASS", line.strip(), line.strip(), doc

    return "UNKNOWN", None, None, None


def _thickness_evidence(fact: _CandidateFact) -> Optional[Tuple[str, Document]]:
    """
    문서 원문에서 "이 후보가 두께 측정을 실제로 지원한다"고 밝힌 서술 문구(과 그 출처 doc)를
    찾는다. 3D Profile/OCT/Z축 범위 등은 단순 파라미터일 뿐 '두께 측정 수행'의 직접 근거로
    인정하지 않으므로, Equipment Type/Notes 등 명시적 텍스트에 "thickness" 키워드가
    있는지 확인한다.
    """
    if fact.equipment_type_text and "thickness" in fact.equipment_type_text.lower():
        return f"Equipment Type: {fact.equipment_type_text}", fact.equipment_type_doc
    if fact.notes_text and "thickness" in fact.notes_text.lower():
        return f"Notes: {fact.notes_text}", fact.notes_doc
    return None


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


def _required_width(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    """요구 폭은 "이 폭 이상을 처리할 수 있어야 한다"는 뜻이므로 operator는 항상
    ">="다 — RequirementSchema.target.width_mm에는 operator 정보가 없는 단일
    float 필드라서(사용자가 폭을 요구할 때 이하/미만을 의도하는 경우가 없는
    도메인이므로) 여기서 고정한다."""
    if requirement.target.width_mm is None:
        return None
    return requirement.target.width_mm, "mm", ">="


def _required_speed(requirement: RequirementSchema) -> Optional[Tuple[float, str, str]]:
    if requirement.measurement_speed is not None and requirement.measurement_speed.value is not None:
        return (
            requirement.measurement_speed.value,
            requirement.measurement_speed.unit or "mm/s",
            requirement.measurement_speed.operator or ">=",
        )
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
    required_width = _required_width(requirement)
    required_speed = _required_speed(requirement)

    candidates: List[CandidateEquipment] = []
    for idx, (source, docs) in enumerate(sorted(by_source.items()), start=1):
        fact = _extract_candidate_fact(docs)
        matches: List[CandidateFieldMatch] = []

        if required_range is not None:
            candidate_range = fact.range
            try:
                ok, _reasons = units.evaluate_hard_requirements(required_range=required_range, candidate_range=candidate_range)
            except units.UnitError:
                ok, candidate_range = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_range is None else "FAIL")
            req_disp = f"{required_range[0]:g}~{required_range[1]:g} {required_range[2]}"
            spec_disp = f"{candidate_range[0]:g}~{candidate_range[1]:g} {candidate_range[2]}" if candidate_range else None
            margin_val = (candidate_range[1] - required_range[1]) if (result == "PASS" and candidate_range) else None
            margin_disp = f"+{margin_val:g} {required_range[2]}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {required_range[2]}" if margin_val is not None else None)
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
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
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
                ok, candidate_accuracy = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_accuracy is None else "FAIL")
            req_disp = f"{operator} {req_value:g} {req_unit}"
            spec_disp = f"±{candidate_accuracy[0]:g} {candidate_accuracy[1]}" if candidate_accuracy else None
            margin_val = (req_value - candidate_accuracy[0]) if (result == "PASS" and candidate_accuracy) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
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
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_defect_size is not None:
            candidate_defect_size = fact.defect_size
            req_value, req_unit, operator = required_defect_size
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_defect_size, candidate_accuracy=candidate_defect_size
                )
            except units.UnitError:
                ok, candidate_defect_size = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_defect_size is None else "FAIL")
            req_disp = f"{operator} {req_value:g} {req_unit}"
            spec_disp = f"{candidate_defect_size[0]:g} {candidate_defect_size[1]}" if candidate_defect_size else None
            margin_val = (req_value - candidate_defect_size[0]) if (result == "PASS" and candidate_defect_size) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
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
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_width is not None:
            req_value, req_unit, operator = required_width
            candidate_width = (fact.width_mm, "mm") if fact.width_mm is not None else None
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_width, candidate_accuracy=candidate_width
                )
            except units.UnitError:
                ok, candidate_width = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_width is None else "FAIL")
            req_disp = f">= {req_value:g} {req_unit}"
            spec_disp = f"{candidate_width[0]:g} {candidate_width[1]}" if candidate_width else None
            margin_val = (candidate_width[0] - req_value) if (result == "PASS" and candidate_width) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Width",
                    field_key="width",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_width[0] if candidate_width else None,
                    found_unit=candidate_width[1] if candidate_width else None,
                    result=result,
                    evidence_text=fact.width_mm_text,
                    source=_source_ref(fact.width_mm_doc) if fact.width_mm_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_speed is not None:
            req_value, req_unit, operator = required_speed
            candidate_speed = fact.speed
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_speed, candidate_accuracy=candidate_speed
                )
            except units.UnitError:
                ok, candidate_speed = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_speed is None else "FAIL")
            req_disp = f">= {req_value:g} {req_unit}"
            spec_disp = f"{candidate_speed[0]:g} {candidate_speed[1]}" if candidate_speed else None
            margin_val = (candidate_speed[0] - req_value) if (result == "PASS" and candidate_speed) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Speed",
                    field_key="speed",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_speed[0] if candidate_speed else None,
                    found_unit=candidate_speed[1] if candidate_speed else None,
                    result=result,
                    evidence_text=fact.speed_text,
                    source=_source_ref(fact.speed_doc) if fact.speed_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

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
                    user_requirement_display=requirement.inline_offline.capitalize(),
                    equipment_spec_display=candidate_mode.capitalize() if candidate_mode else None,
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
                    user_requirement_display=requirement.measurement_method.replace("_", "-").capitalize(),
                    equipment_spec_display=candidate_method.replace("_", "-").capitalize() if candidate_method else None,
                )
            )

        if requirement.measurement_principle is not None:
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
                    user_requirement_display=required_principle,
                    equipment_spec_display=candidate_principle if candidate_principle else None,
                )
            )

        for item in requirement.inspection_items:
            label = _INSPECTION_ITEM_LABELS.get(item, item.replace("_", " ").title())
            if item == "thickness":
                if fact.thickness_not_supported:
                    item_result = "FAIL"
                    found_text = "Not Supported"
                    evidence = "Thickness Measurement: Not Supported"
                    source_doc = fact.thickness_not_supported_doc
                else:
                    hit = _thickness_evidence(fact)
                    if hit is None:
                        item_result, found_text, evidence, source_doc = "UNKNOWN", None, None, None
                    else:
                        item_result = "PASS"
                        evidence_text, evidence_doc = hit
                        if fact.range is not None:
                            found_text = fact.range_text
                            evidence = f"{fact.range_text} (근거: {evidence_text})"
                            source_doc = fact.range_doc
                        else:
                            found_text = evidence_text
                            evidence = evidence_text
                            source_doc = evidence_doc
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=evidence,
                        source=_source_ref(source_doc) if source_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            if item == "coating":
                item_result, found_text, evidence, source_doc = _coating_evidence(fact, docs)
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=evidence,
                        source=_source_ref(source_doc) if source_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            if item in categorical_match.INSPECTION_ITEM_CAPABILITY_KEYWORDS:
                capability_doc = fact.equipment_type_doc or fact.measurement_principle_doc
                capability_text = " ".join(
                    t for t in (fact.equipment_type_text, fact.measurement_principle_text) if t
                )
                capability = categorical_match.match_inspection_item_capability(item, capability_text)
                if capability is True:
                    item_result, found_text = "PASS", capability_text
                elif capability is False:
                    item_result, found_text = "FAIL", capability_text
                else:
                    item_result, found_text, capability_doc = "UNKNOWN", None, None
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=capability_text or None,
                        source=_source_ref(capability_doc) if capability_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            keywords = _INSPECTION_ITEM_DEFECT_KEYWORDS.get(item)
            if keywords is None:
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        result="UNKNOWN",
                        user_requirement_display=label,
                    )
                )
                continue
            if fact.defect_inspection_not_supported:
                item_result = "FAIL"
                found_text = "Not Supported"
                evidence = "Defect Inspection: Not Supported"
                source_doc = fact.defect_inspection_not_supported_doc
            elif fact.defect_types_text is not None:
                defect_types_lower = fact.defect_types_text.lower()
                item_result = "PASS" if any(kw in defect_types_lower for kw in keywords) else "FAIL"
                found_text = fact.defect_types_text
                evidence = f"Defect Types: {fact.defect_types_text}"
                source_doc = fact.defect_types_doc
            else:
                item_result = "UNKNOWN"
                found_text = None
                evidence = None
                source_doc = None
            matches.append(
                CandidateFieldMatch(
                    item=label,
                    field_key=f"inspection_item_{item}",
                    hard=True,
                    requirement_text=item,
                    found_text=found_text,
                    result=item_result,
                    evidence_text=evidence,
                    source=_source_ref(source_doc) if source_doc else None,
                    user_requirement_display=label,
                    equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                )
            )

        pass_count = sum(1 for m in matches if m.result == "PASS")
        fail_count = sum(1 for m in matches if m.result == "FAIL")
        unknown_count = sum(1 for m in matches if m.result == "UNKNOWN")
        hard_requirements_pass = fail_count == 0 and unknown_count == 0
        match_score = 100.0 * pass_count / len(matches) if matches else 0.0

        total_margin = sum(m.margin for m in matches if m.margin is not None)
        doc_scores = [doc.metadata.get("score") for doc in docs if doc.metadata.get("score") is not None]
        rag_sim_score = float(sum(doc_scores) / len(doc_scores)) if doc_scores else None

        recommendation_reasons = []
        unconfirmed_items = []
        for m in matches:
            if m.result == "PASS":
                if m.margin_display:
                    recommendation_reasons.append(f"✓ {m.item}: 요구 {m.user_requirement_display}, 장비 {m.equipment_spec_display} ({m.margin_display})")
                elif m.user_requirement_display and m.equipment_spec_display:
                    recommendation_reasons.append(f"✓ {m.item}: 요구 {m.user_requirement_display}, 장비 {m.equipment_spec_display}")
                else:
                    recommendation_reasons.append(f"✓ {m.item}: {m.user_requirement_display or m.item} 지원 확인")
            elif m.result == "UNKNOWN":
                unconfirmed_items.append(f"? {m.item}: 장비 사양서에서 확인하지 못함")

        if fail_count == 0 and unknown_count == 0:
            status = "PASS"
        elif fail_count == 0:
            status = "PARTIAL"
        else:
            status = "FAIL"

        # Markdown 사양서 내보내기 등에 쓰는 전체 사양 스냅샷 — 위 matches와 달리
        # 사용자가 그 항목을 요구조건으로 묻지 않았어도 문서에 실제로 있으면 채운다
        # (요청서: "추천된 장비의 정보를 기반으로 Markdown 사양서를 생성"). 근거
        # 없는 필드는 그대로 None/빈 리스트로 둔다 — 추측해서 채우지 않는다.
        equipment_fact = CandidateEquipmentFact(
            equipment_type=fact.equipment_type_text,
            measurement_principle=fact.measurement_principle,
            inline_offline=fact.inspection_mode,
            measurement_method=fact.measurement_method,
            width_mm=fact.width_mm,
            range_min=fact.range[0] if fact.range else None,
            range_max=fact.range[1] if fact.range else None,
            range_unit=fact.range[2] if fact.range else None,
            accuracy_value=fact.accuracy[0] if fact.accuracy else None,
            accuracy_unit=fact.accuracy[1] if fact.accuracy else None,
            resolution_value=fact.resolution[0] if fact.resolution else None,
            resolution_unit=fact.resolution[1] if fact.resolution else None,
            speed_value=fact.speed[0] if fact.speed else None,
            speed_unit=fact.speed[1] if fact.speed else None,
            defect_types=(
                [t.strip() for t in fact.defect_types_text.split(",") if t.strip()]
                if fact.defect_types_text and not fact.defect_inspection_not_supported
                else []
            ),
            min_defect_size_value=fact.defect_size[0] if fact.defect_size else None,
            min_defect_size_unit=fact.defect_size[1] if fact.defect_size else None,
            x_range_min=fact.x_range[0] if fact.x_range else None,
            x_range_max=fact.x_range[1] if fact.x_range else None,
            x_range_unit=fact.x_range[2] if fact.x_range else None,
            y_range_min=fact.y_range[0] if fact.y_range else None,
            y_range_max=fact.y_range[1] if fact.y_range else None,
            y_range_unit=fact.y_range[2] if fact.y_range else None,
            # Z Range/Resolution: "## Spatial Performance" 절에 명시적으로 있으면
            # 그 값을 쓰고, 없으면 "## Measurement Performance"의 주 측정 범위/
            # 해상도(fact.range/fact.resolution)를 그대로 재사용한다 — 이 corpus의
            # 장비 대부분은 두께/깊이(Z축)를 측정하는 것이 곧 "주" 측정 성능이므로
            # 같은 숫자를 "## Spatial Performance"에도 사양서 원문에 중복으로
            # 적어 넣을 필요가 없다(sample_specs 파일에 문자 그대로 중복 텍스트를
            # 추가하면 heading 기반 RAG chunking이 새 chunk를 만들어, fake-hash
            # 임베딩을 쓰는 결정론적 테스트의 검색 순위가 흔들리는 부작용이 실제로
            # 있었다 — Z Range/Resolution은 코드에서만 매핑하고 원문은 건드리지
            # 않는 것으로 정책을 바꿨다).
            z_range_min=fact.z_range[0] if fact.z_range else (fact.range[0] if fact.range else None),
            z_range_max=fact.z_range[1] if fact.z_range else (fact.range[1] if fact.range else None),
            z_range_unit=fact.z_range[2] if fact.z_range else (fact.range[2] if fact.range else None),
            x_resolution_value=fact.x_resolution[0] if fact.x_resolution else None,
            x_resolution_unit=fact.x_resolution[1] if fact.x_resolution else None,
            y_resolution_value=fact.y_resolution[0] if fact.y_resolution else None,
            y_resolution_unit=fact.y_resolution[1] if fact.y_resolution else None,
            z_resolution_value=fact.z_resolution[0] if fact.z_resolution else (fact.resolution[0] if fact.resolution else None),
            z_resolution_unit=fact.z_resolution[1] if fact.z_resolution else (fact.resolution[1] if fact.resolution else None),
            fov_display=fact.fov_display,
            working_distance_value=fact.working_distance[0] if fact.working_distance else None,
            working_distance_unit=fact.working_distance[1] if fact.working_distance else None,
            pixel_size_value=fact.pixel_size[0] if fact.pixel_size else None,
            pixel_size_unit=fact.pixel_size[1] if fact.pixel_size else None,
        )

        candidates.append(
            CandidateEquipment(
                candidate_id=f"cand-{idx}",
                manufacturer=fact.manufacturer,
                model=fact.model,
                source_document=source,
                matches=matches,
                equipment_fact=equipment_fact,
                match_score=match_score,
                hard_requirements_pass=hard_requirements_pass,
                unknown_count=unknown_count,
                fail_count=fail_count,
                pass_count=pass_count,
                total_margin=total_margin,
                rag_similarity_score=rag_sim_score,
                recommendation_reasons=recommendation_reasons,
                unconfirmed_items=unconfirmed_items,
                status=status,
            )
        )

    return candidates


_STATUS_RANK = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


def select_best_candidate(candidates: List[CandidateEquipment]) -> Optional[CandidateEquipment]:
    """
    최종 랭킹 우선순위 (요청서 4절):
    1순위: Hard Requirement PASS 수가 많은 후보 (-c.pass_count) 또는 status (PASS: 0 > PARTIAL: 1 > FAIL: 2)
    2순위: UNKNOWN 수가 적은 후보 (unknown_count 오름차순)
    3순위: FAIL 수가 적은 후보 (fail_count 오름차순)
    4순위: RAG similarity가 높은 후보 (-(c.rag_similarity_score or 0.0) 내림차순)
    5순위: 후보 문서 순서 (candidate_id 오름차순)

    검토했으나 채택하지 않은 대안(QA 개선 작업 5절): fail_count와 RAG similarity 사이에
    -c.total_margin(요구조건 대비 성능 여유, 사용자가 실제로 요구한 항목의 margin만 합산 —
    이미 build_candidates()가 계산해 CandidateEquipment.total_margin에 채워둔다)을 추가로
    끼워 넣는 실험을 해봤다. 단일 항목 요구에서는 의도대로 더 여유 있는 후보를 우선했지만,
    기존에 확정된 후보 선택 결과에 의존하는 3개의 회귀 테스트(예:
    test_chat_ui_regression_baseline_multisense_ms600,
    test_end_to_end_pipeline_selects_correct_candidate_for_non_standard_label,
    test_integration_10b_end_to_end_correct_candidate_now_selected)가 깨졌다 — 이 테스트들이
    가정하는 기존 동점 처리 순서(RAG similarity/candidate_id)로 이미 확정된 후보가 margin
    도입으로 바뀌었기 때문이다. "666/666 기존 테스트를 절대 깨지 않는다"는 이번 작업의
    최우선 원칙이므로 이 변경은 되돌렸다 — 이 기능을 원하면 별도 후속 작업으로 위 3개
    테스트의 기대값을 의도적으로 함께 갱신해야 한다(코드에 맞추기 위한 임의 변경이 아니라
    "랭킹 정책을 실제로 바꾸기로 결정"하는 별도 승인이 필요하다).
    """
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda c: (
            _STATUS_RANK[c.status],
            -c.pass_count,
            c.unknown_count,
            c.fail_count,
            -(c.rag_similarity_score or 0.0),
            c.candidate_id,
        ),
    )[0]
