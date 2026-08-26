"""
SPEC-011.md ~ SPEC-050.md(sample_specs/) 신규 테스트 장비 40개의 단일 진실 공급원
(single source of truth). 이 모듈은 pytest가 아니다 — 값 자체를 담을 뿐이며,
아래 두 곳에서 재사용된다:

1. scripts/generate_sample_specs_011_050.py — 이 데이터를 바탕으로 실제
   sample_specs/SPEC-0NN.md 파일들을 생성한다.
2. tests/test_sample_specs_ground_truth.py — 생성된 .md 파일이 이 데이터와
   정확히 일치하는지(값이 있는 필드는 값이, UNKNOWN인 필드는 그 정보 자체가
   완전히 없는지) 검증한다.

Ground Truth 값 자체는 사용자가 지정한 것을 그대로 옮긴 것이며, 이 파일이나
생성 스크립트가 임의로 값을 바꾸거나 추가해서는 안 된다. Range/Accuracy/
Resolution/Speed/Width/MinDefect가 None이면 "UNKNOWN"(해당 정보가 원문에
아예 존재하지 않음)을 의미한다.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple


class EquipmentGT(NamedTuple):
    spec_id: str  # "SPEC-011"
    model_full: str  # "ThicknessPro TP-200" (Manufacturer + Model 결합 표기)
    equipment_type: str
    mode: str  # "Inline" | "Offline"
    width_mm: Optional[float]
    speed_mm_s: Optional[float]
    range_um: Optional[Tuple[float, float]]
    accuracy_um: Optional[float]
    resolution_um: Optional[float]
    min_defect_um: Optional[float]
    principle: str
    items: Tuple[str, ...]


# Ground Truth 표(요청서 3절)를 그대로 옮긴다 — 값을 바꾸지 말 것.
GROUND_TRUTH: List[EquipmentGT] = [
    EquipmentGT("SPEC-011", "ThicknessPro TP-200", "Thickness Inspection", "Inline", 500, 300, (0, 200), 0.5, 0.1, None, "Laser", ("thickness",)),
    EquipmentGT("SPEC-012", "ThicknessPro TP-500", "Thickness Inspection", "Inline", 800, 500, (0, 500), 2.0, 0.2, None, "Laser", ("thickness",)),
    EquipmentGT("SPEC-013", "ThicknessPro TP-800", "Thickness Inspection", "Inline", 1200, 800, (0, 800), 0.8, 0.1, None, "Optical", ("thickness",)),
    EquipmentGT("SPEC-014", "PrecisionGauge PG-100", "Thickness Inspection", "Offline", 300, None, (0, 100), 0.1, 0.01, None, "Interferometry", ("thickness",)),
    EquipmentGT("SPEC-015", "PrecisionGauge PG-300", "Thickness Inspection", "Offline", 400, None, (0, 300), 0.3, 0.05, None, "Interferometry", ("thickness",)),
    EquipmentGT("SPEC-016", "PrecisionGauge PG-600", "Thickness Inspection", "Offline", 600, None, (0, 600), 0.5, 0.05, None, "OCT", ("thickness",)),
    EquipmentGT("SPEC-017", "FastThickness FT-400", "Thickness Inspection", "Inline", 600, 1200, (0, 400), 1.5, 0.2, None, "Laser", ("thickness",)),
    EquipmentGT("SPEC-018", "WideThickness WT-1000", "Thickness Inspection", "Inline", 1500, 700, (0, 300), 1.0, 0.2, None, "Optical", ("thickness",)),
    EquipmentGT("SPEC-019", "VisionInspect VI-300", "Surface Inspection", "Inline", 300, 1000, None, None, None, 10, "Machine Vision", ("scratch", "contamination")),
    EquipmentGT("SPEC-020", "VisionInspect VI-600", "Surface Inspection", "Inline", 600, 800, None, None, None, 5, "Machine Vision", ("scratch", "contamination", "particle")),
    EquipmentGT("SPEC-021", "VisionInspect VI-1000", "Surface Inspection", "Inline", 1000, 600, None, None, None, 3, "Machine Vision", ("scratch", "contamination", "particle", "pinhole")),
    EquipmentGT("SPEC-022", "MicroDefect MD-200", "Surface Inspection", "Offline", 200, None, None, None, None, 1, "High Resolution Vision", ("scratch", "crack", "pinhole")),
    EquipmentGT("SPEC-023", "MicroDefect MD-500", "Surface Inspection", "Offline", 500, None, None, None, None, 2, "Confocal Vision", ("scratch", "particle", "contamination")),
    EquipmentGT("SPEC-024", "SurfaceScan SS-800", "Surface Inspection", "Inline", 800, 1000, None, None, None, 2, "Line Scan Vision", ("surface_defect",)),
    EquipmentGT("SPEC-025", "SurfaceScan SS-1200", "Surface Inspection", "Inline", 1200, 500, None, None, None, None, "Optical Vision", ("scratch", "contamination", "coating_defect")),
    EquipmentGT("SPEC-026", "EdgeVision EV-300", "Edge Inspection", "Inline", 300, 800, None, None, None, 10, "Vision", ("edge_defect",)),
    EquipmentGT("SPEC-027", "EdgeVision EV-600", "Edge Inspection", "Inline", 600, 700, None, None, None, 5, "Vision", ("edge_defect", "edge_crack")),
    EquipmentGT("SPEC-028", "EdgeVision EV-1000", "Edge Inspection", "Inline", 1000, 500, None, None, None, 3, "High Resolution Vision", ("edge_defect", "edge_crack", "edge_chipping")),
    EquipmentGT("SPEC-029", "EdgePrecision EP-400", "Edge Inspection", "Offline", 400, None, None, None, None, 1, "Microscope Vision", ("edge_defect", "edge_crack")),
    EquipmentGT("SPEC-030", "EdgeScan Pro ES-800", "Edge Inspection", "Inline", 800, None, None, None, None, 2, "Laser + Vision", ("edge_defect", "edge_crack", "edge_profile")),
    EquipmentGT("SPEC-031", "OCTInspect OI-300", "OCT Inspection", "Inline", 300, 300, (5, 300), 1.0, 0.5, None, "OCT", ("thickness", "void")),
    EquipmentGT("SPEC-032", "OCTInspect OI-600", "OCT Inspection", "Inline", 600, 500, (5, 500), 1.0, 0.5, None, "OCT", ("thickness", "void", "coating_non_uniformity")),
    EquipmentGT("SPEC-033", "OCTInspect OI-1000", "OCT Inspection", "Inline", 1000, 400, (1, 800), 2.0, 1.0, None, "OCT", ("thickness", "void")),
    EquipmentGT("SPEC-034", "CoatingOCT CO-400", "Coating Inspection", "Offline", 400, None, (1, 400), 0.5, 0.1, None, "OCT", ("thickness", "coating_non_uniformity", "void")),
    EquipmentGT("SPEC-035", "FilmInspect FI-500", "Coating Inspection", "Inline", 500, 600, (0.1, 500), 0.8, 0.1, None, "Spectral Interferometry", ("thickness", "coating_non_uniformity")),
    EquipmentGT("SPEC-036", "VoidScan VS-800", "Void Inspection", "Inline", 800, 300, None, None, None, None, "OCT", ("void",)),
    EquipmentGT("SPEC-037", "ProfileScan PS-300", "3D Profile Inspection", "Inline", 300, 500, (0, 300), 1.0, 0.2, None, "Laser Profiling", ("profile_3d",)),
    EquipmentGT("SPEC-038", "ProfileScan PS-600", "3D Profile Inspection", "Inline", 600, 500, (0, 500), 1.0, 0.2, None, "Laser Profiling", ("profile_3d", "surface_defect")),
    EquipmentGT("SPEC-039", "ProfileScan PS-1000", "3D Profile Inspection", "Inline", 1000, 700, (0, 1000), 2.0, 0.5, None, "3D Laser", ("profile_3d",)),
    EquipmentGT("SPEC-040", "NanoProfile NP-500", "3D Profile Inspection", "Offline", 500, None, (0, 100), 0.2, 0.05, None, "Confocal", ("profile_3d", "surface_defect")),
    EquipmentGT("SPEC-041", "WideProfile WP-1200", "3D Profile Inspection", "Inline", 1200, None, (0, 500), 1.5, 0.3, None, "Laser Triangulation", ("profile_3d",)),
    EquipmentGT("SPEC-042", "MultiInspect MI-500", "Multi Inspection", "Inline", 500, 500, (0, 300), 0.8, 0.2, 5, "Multi-sensor", ("thickness", "surface_defect")),
    EquipmentGT("SPEC-043", "MultiInspect MI-600", "Multi Inspection", "Inline", 600, 500, (0, 300), 1.2, 0.2, 5, "Multi-sensor", ("thickness", "surface_defect")),
    EquipmentGT("SPEC-044", "MultiInspect MI-800", "Multi Inspection", "Inline", 800, 600, (0, 500), 0.8, 0.1, 3, "Multi-sensor", ("thickness", "surface_defect", "profile_3d")),
    EquipmentGT("SPEC-045", "MultiInspect MI-1000", "Multi Inspection", "Inline", 1000, 500, (0, 300), 0.5, 0.1, 2, "Multi-sensor", ("thickness", "surface_defect", "edge_defect")),
    EquipmentGT("SPEC-046", "TotalInspect TI-800", "Multi Inspection", "Inline", 800, 800, (0, 800), 1.0, 0.2, 2, "Multi-sensor", ("thickness", "surface_defect", "edge_defect", "profile_3d")),
    EquipmentGT("SPEC-047", "TotalInspect TI-1200", "Multi Inspection", "Inline", 1200, 600, (0, 500), None, 0.2, None, "Multi-sensor", ("thickness", "surface_defect", "void", "coating_non_uniformity")),
    EquipmentGT("SPEC-048", "BasicInspect BI-600", "Basic Inspection", "Inline", 600, None, None, None, None, None, "Optical", ("thickness",)),
    EquipmentGT("SPEC-049", "VisionFlex VF-800", "Surface Inspection", "Inline", 800, None, None, None, None, None, "Optical Vision", ("scratch", "particle")),
    EquipmentGT("SPEC-050", "HybridScan HS-1000", "Hybrid Inspection", "Inline", None, None, None, None, None, None, "Hybrid Optical", ("thickness", "void", "surface_defect")),
]

GROUND_TRUTH_BY_ID: Dict[str, EquipmentGT] = {gt.spec_id: gt for gt in GROUND_TRUTH}

# 검사 항목(item) 식별자 -> Defect Types 표/문서에 쓸 사람이 읽는 명칭(요청서 5절 매핑).
# thickness/profile_3d는 "결함 종류"가 아니라 측정 능력이므로 Defect Types에는 넣지
# 않는다(별도로 Measurement Range/Equipment Type 서술로 표현됨).
ITEM_DEFECT_LABELS: Dict[str, str] = {
    "surface_defect": "Surface Defect",
    "edge_defect": "Edge Defect",
    "edge_crack": "Edge Crack",
    "edge_chipping": "Edge Chipping",
    "edge_profile": "Edge Profile",
    "scratch": "Scratch",
    "contamination": "Contamination",
    "particle": "Particle",
    "pinhole": "Pin Hole",
    "pit": "Pit",
    "crack": "Crack",
    "void": "Void",
    "coating_non_uniformity": "Coating Non-uniformity",
    "coating_defect": "Coating Defect",
}

# thickness/profile_3d는 Defect Types 목록에 넣지 않는 항목("측정 능력"이지 "결함
# 종류"가 아님).
_NON_DEFECT_ITEMS = ("thickness", "profile_3d")


def defect_type_items(items: Tuple[str, ...]) -> Tuple[str, ...]:
    return tuple(i for i in items if i not in _NON_DEFECT_ITEMS)
