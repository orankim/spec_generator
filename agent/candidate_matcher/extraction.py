"""
문서(Document) chunk에서 장비 사실(_CandidateFact)을 뽑아내는 결정론적 정규식/
파싱 계층. LLM을 전혀 쓰지 않는다 — agent/candidate_matcher/__init__.py 참고.

agent/candidate_matcher.py 하나였던 파일을 응집도 기준으로 나눈 것 중 "추출"
계층: Manufacturer/Model/Inspection Mode 같은 General 절 필드, Measurement/
Spatial Performance 표, Defect Inspection 절 등 원문 텍스트 -> _CandidateFact
변환만 담당한다. Hard Requirement 판정(hard_requirements.py)/검사 항목 판정
(inspection_items.py)/최종 랭킹(ranking.py)은 여기서 하지 않는다.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document

from .. import categorical_match, units

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
