"""
검사 항목(inspection_items) PASS/FAIL/UNKNOWN 판정에 쓰는 키워드 테이블과
thickness/coating 전용 판정 함수 — agent/candidate_matcher/__init__.py 참고.

thickness/coating은 "Defect Types" 같은 단순 목록 매칭이 아니라 Equipment Type/
Notes 서술문에서 명시적 근거 문구를 찾아야 하므로(3D Profile/OCT 파라미터가
있다는 사실만으로는 "두께를 측정한다"는 근거가 되지 않는다 — 원본 파일의
_thickness_evidence 문제3 주석 참고) 별도 함수로 분리되어 있다. 나머지 canonical
item(scratch/contamination/particle/...)은 core.py의 build_candidates()가
_INSPECTION_ITEM_DEFECT_KEYWORDS를 직접 찾아 판정한다(여기서는 데이터만 제공).
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Tuple

from langchain_core.documents import Document

from .extraction import _CandidateFact

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
