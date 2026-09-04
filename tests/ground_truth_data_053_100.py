"""
SPEC-053.md ~ SPEC-100.md(sample_specs/) 신규 확장 장비 48개의 단일 진실 공급원
(single source of truth) — SPEC 100개 확장 프로젝트 Phase 1.

tests/ground_truth_data.py(SPEC-011~050, 기존 40개)와 완전히 별개의 파일이다 —
기존 파일은 이 작업에서 절대 건드리지 않는다. 구조/검증 방식은 동일한 패턴을
그대로 따른다:

1. scripts/generate_sample_specs_053_100.py — 이 데이터를 바탕으로 실제
   sample_specs/SPEC-0NN.md(053~100) 파일들을 생성한다.
2. tests/test_sample_specs_053_100_ground_truth.py — 생성된 .md 파일이 이
   데이터와 정확히 일치하는지(값이 있는 필드는 값이, UNKNOWN인 필드는 그
   정보 자체가 완전히 없는지) 검증한다.

설계 원칙(요청서 1단계):
- 단순 복사본이 아니라 서로 다른 측정 원리(2D/3D Laser, Confocal, Chromatic
  Confocal, OCT/OCT-NIR, Interferometry, Vision 등)와 의도적으로 대비되는
  시나리오(폭은 크지만 범위는 좁음/범위는 크지만 해상도는 낮음/Inline이지만
  특정 항목 미지원/두께만 지원·표면결함만 지원·둘 다 지원/고속-저정밀·
  저속-고정밀/초광폭/초미세결함)를 포함한다.
- agent.candidate_matcher가 실제로 인식하는 필드/라벨/단위만 사용한다(신규
  inspection_items 키를 만들지 않는다 — agent/*.py를 수정하지 않으므로 기존
  키만 재사용 가능).
- 신규 Manufacturer/Model은 기존 52개(SPEC-001~052)와 절대 겹치지 않는
  가상의 이름만 쓴다(실제 업체처럼 보이지 않는 기존 정책 그대로 유지).
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple


class EquipmentGT2(NamedTuple):
    spec_id: str  # "SPEC-053"
    model_full: str  # "LaserGauge LG-300"
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
    # tests/ground_truth_data.py의 EquipmentGT에는 없는 확장 필드 — "두께 측정
    # 자체를 지원하지 않는다"는 명시적 반증(agent.candidate_matcher._THICKNESS_
    # NOT_SUPPORTED_RE, SPEC-006과 동일한 패턴)을 문서에 추가할지 여부. True면
    # thickness가 items에 없어도(UNKNOWN이 아니라) 명시적 FAIL 근거가 생긴다.
    thickness_not_supported: bool = False


# ==========================================================================
# Group A — 2D Laser Triangulation 계열 (Thickness). 폭은 크지만 측정 범위가
# 좁은 경우(A-3)/범위는 크지만 해상도가 낮은 경우(A-4)/고속-저정밀(A-5)/
# 저속(Offline)-초정밀(A-6)을 포함한다.
# ==========================================================================
_GROUP_A: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-053", "LaserGauge LG-300", "Thickness Inspection", "Inline", 300, 600, (0, 150), 1.0, 0.2, None, "2D Laser Triangulation", ("thickness",)),
    EquipmentGT2("SPEC-054", "LaserGauge LG-700", "Thickness Inspection", "Inline", 700, 900, (0, 300), 0.8, 0.15, None, "2D Laser Triangulation", ("thickness",)),
    EquipmentGT2("SPEC-055", "LaserGauge LG-1500", "Thickness Inspection", "Inline", 1500, 400, (0, 80), 0.5, 0.1, None, "2D Laser Triangulation", ("thickness",)),
    EquipmentGT2("SPEC-056", "CompactLaser CL-250", "Thickness Inspection", "Offline", 250, None, (0, 1000), 5.0, 2.0, None, "2D Laser", ("thickness",)),
    EquipmentGT2("SPEC-057", "RapidLaser RL-900", "Thickness Inspection", "Inline", 900, 2000, (0, 200), 3.0, 0.8, None, "2D Laser", ("thickness",)),
    EquipmentGT2("SPEC-058", "SlowPrecision SP-400", "Thickness Inspection", "Offline", 400, None, (0, 50), 0.05, 0.01, None, "Precision Laser", ("thickness",)),
]

# ==========================================================================
# Group B — 3D Laser Profilometry 계열 (profile_3d). A와 동일한 대비 구조를
# 3D Profile Inspection 쪽에서 반복한다.
# ==========================================================================
_GROUP_B: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-059", "ProfileLaser PL-300", "3D Profile Inspection", "Inline", 300, 550, (0, 300), 0.9, 0.2, None, "3D Laser Profilometry", ("profile_3d",)),
    EquipmentGT2("SPEC-060", "ProfileLaser PL-800", "3D Profile Inspection", "Inline", 800, 600, (0, 600), 1.5, 0.3, 5, "3D Laser Profilometry", ("profile_3d", "surface_defect")),
    EquipmentGT2("SPEC-061", "ProfileLaser PL-1600", "3D Profile Inspection", "Inline", 1600, 300, (0, 150), 0.8, 0.15, None, "3D Laser Profilometry", ("profile_3d",)),
    EquipmentGT2("SPEC-062", "WideRangeProfile WP-500", "3D Profile Inspection", "Offline", 500, None, (0, 2000), 8.0, 3.0, None, "Laser Profilometry", ("profile_3d",)),
    EquipmentGT2("SPEC-063", "FastProfile FP-1000", "3D Profile Inspection", "Inline", 1000, 1800, (0, 400), 4.0, 1.0, 8, "3D Laser", ("profile_3d", "surface_defect")),
    EquipmentGT2("SPEC-064", "MicroProfile MP-200", "3D Profile Inspection", "Offline", 200, None, (0, 30), 0.02, 0.005, None, "3D Laser Profilometry", ("profile_3d",)),
]

# ==========================================================================
# Group C — Confocal / Chromatic Confocal. 두 값 모두 agent.categorical_match.
# MEASUREMENT_PRINCIPLE_KEYWORDS에 없는 canonical 미인식 원리다(기존 corpus의
# SPEC-023 "Confocal Vision"/SPEC-040 "Confocal"과 동일하게 원문 텍스트로는
# 정상 저장되지만, Measurement Principle 요구조건 매칭에는 쓰이지 않는다 —
# Phase 1 완료 보고에 이 사실을 그대로 명시한다. agent/*.py는 수정하지 않는다).
# ==========================================================================
_GROUP_C: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-065", "ConfocalPro CP-300", "Thickness Inspection", "Offline", 300, None, (0, 200), 0.1, 0.02, None, "Confocal", ("thickness",)),
    EquipmentGT2("SPEC-066", "ChromaScan CS-400", "3D Profile Inspection", "Offline", 400, None, (0, 500), 0.3, 0.05, None, "Chromatic Confocal", ("profile_3d", "thickness")),
    EquipmentGT2("SPEC-067", "ConfocalInline CI-600", "Multi Inspection", "Inline", 600, 400, (0, 300), 0.5, 0.1, 4, "Confocal", ("thickness", "surface_defect")),
    EquipmentGT2("SPEC-068", "ChromaPrecision CX-250", "Thickness Inspection", "Offline", 250, None, (0, 100), 0.05, 0.01, None, "Chromatic Confocal", ("thickness",)),
]

# ==========================================================================
# Group D — OCT / OCT-NIR. "oct"가 포함되므로 categorical_match가 "OCT"로
# 정상 인식한다(OCT-NIR도 부분 문자열 "oct" 포함으로 매칭).
# ==========================================================================
_GROUP_D: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-069", "OCTNext ON-400", "OCT Inspection", "Inline", 400, 500, (1, 600), 1.0, 0.4, None, "OCT-NIR", ("thickness", "void")),
    EquipmentGT2("SPEC-070", "OCTNext ON-800", "OCT Inspection", "Inline", 800, 700, (1, 1000), 1.5, 0.5, None, "OCT-NIR", ("thickness", "void", "coating_non_uniformity")),
    EquipmentGT2("SPEC-071", "OCTCompact OC-300", "OCT Inspection", "Offline", 300, None, (1, 300), 0.3, 0.1, None, "OCT", ("thickness",)),
    EquipmentGT2("SPEC-072", "OCTHighSpeed OH-1200", "OCT Inspection", "Inline", 1200, 2500, (1, 500), 3.0, 1.0, None, "OCT-NIR", ("thickness", "void")),
]

# ==========================================================================
# Group E — Interferometry(White Light / Broadband). 초정밀·저속(Offline)
# 시나리오 위주.
# ==========================================================================
_GROUP_E: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-073", "InterferoPrecision IP-200", "Thickness Inspection", "Offline", 200, None, (0, 150), 0.05, 0.005, None, "White Light Interferometry", ("thickness",)),
    EquipmentGT2("SPEC-074", "InterferoPrecision IP-500", "Thickness Inspection", "Offline", 500, None, (0, 400), 0.1, 0.01, None, "White Light Interferometry", ("thickness",)),
    EquipmentGT2("SPEC-075", "BroadbandScan BS-350", "3D Profile Inspection", "Offline", 350, None, (0, 250), 0.08, 0.01, None, "Broadband Interferometry", ("profile_3d",)),
    EquipmentGT2("SPEC-076", "InterferoWide IW-900", "Thickness Inspection", "Offline", 900, None, (0, 60), 0.02, 0.005, None, "Interferometry", ("thickness",)),
]

# ==========================================================================
# Group F — Vision Inspection(표면 결함 다양화). 고속-저정밀(F-2)/저속-초미세
# (F-3)/광폭(F-4) 대비를 포함한다.
# ==========================================================================
_GROUP_F: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-077", "VisionCore VC-400", "Surface Inspection", "Inline", 400, 1500, None, None, None, 8, "2D Vision", ("scratch", "contamination")),
    EquipmentGT2("SPEC-078", "VisionCore VC-800", "Surface Inspection", "Inline", 800, 2000, None, None, None, 15, "High-Speed Vision", ("scratch", "particle", "contamination")),
    EquipmentGT2("SPEC-079", "VisionFine VF-300", "Surface Inspection", "Offline", 300, None, None, None, None, 0.5, "Micro Vision", ("scratch", "pinhole", "particle")),
    EquipmentGT2("SPEC-080", "VisionWide VW-1800", "Surface Inspection", "Inline", 1800, 1000, None, None, None, 10, "Wide-Field Vision", ("surface_defect",)),
    EquipmentGT2("SPEC-081", "VoidVision VV-500", "Surface Inspection", "Inline", 500, 800, None, None, None, 5, "Vision", ("pinhole", "void")),
    EquipmentGT2("SPEC-082", "EdgeVisionPro EVP-700", "Edge Inspection", "Inline", 700, 900, None, None, None, 6, "Vision", ("edge_defect", "edge_crack")),
]

# ==========================================================================
# Group G — Surface Defect 전용, Thickness 명시적 미지원(thickness_not_supported
# =True로 "## Thickness Measurement\n- Not Supported" 절 추가 — SPEC-006과
# 동일한 패턴). "Surface Defect는 지원하지만 Thickness는 미지원" 시나리오.
# ==========================================================================
_GROUP_G: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-083", "DefectOnly DO-400", "Surface Inspection", "Inline", 400, 1200, None, None, None, 8, "Vision", ("scratch", "contamination", "particle"), True),
    EquipmentGT2("SPEC-084", "DefectOnly DO-800", "Surface Inspection", "Inline", 800, 950, None, None, None, 5, "High Resolution Vision", ("scratch", "particle", "pinhole"), True),
    EquipmentGT2("SPEC-085", "SurfaceGuard SG-600", "Surface Inspection", "Offline", 650, None, None, None, None, 2, "Confocal Vision", ("scratch", "contamination"), True),
    EquipmentGT2("SPEC-086", "SurfaceGuard SG-1000", "Surface Inspection", "Inline", 1000, 700, None, None, None, 3, "Line Scan Vision", ("surface_defect",), True),
]

# ==========================================================================
# Group H — Thickness 전용(Defect Inspection은 items에 결함형 항목이 없어
# 자동으로 "Not Supported"). "Thickness는 지원하지만 Surface Defect는 미지원"
# 시나리오.
# ==========================================================================
_GROUP_H: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-087", "PureThickness PT-350", "Thickness Inspection", "Inline", 350, 600, (0, 250), 1.0, 0.2, None, "Laser", ("thickness",)),
    EquipmentGT2("SPEC-088", "PureThickness PT-750", "Thickness Inspection", "Inline", 750, 800, (0, 500), 0.6, 0.1, None, "Laser", ("thickness",)),
    EquipmentGT2("SPEC-089", "PureThickness PT-1200", "Thickness Inspection", "Offline", 1200, None, (0, 900), 0.3, 0.05, None, "Optical", ("thickness",)),
    EquipmentGT2("SPEC-090", "PureThickness PT-1600", "Thickness Inspection", "Inline", 1600, 1500, (0, 300), 2.0, 0.5, None, "Laser", ("thickness",)),
]

# ==========================================================================
# Group I — Thickness + Surface Defect 모두 지원(Multi Inspection). "둘 다
# 지원" 시나리오.
# ==========================================================================
_GROUP_I: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-091", "DualInspect DI-500", "Multi Inspection", "Inline", 500, 600, (0, 300), 0.8, 0.2, 5, "Multi-sensor", ("thickness", "surface_defect")),
    EquipmentGT2("SPEC-092", "DualInspect DI-900", "Multi Inspection", "Inline", 900, 700, (0, 500), 0.6, 0.15, 3, "Multi-sensor", ("thickness", "surface_defect", "edge_defect")),
    EquipmentGT2("SPEC-093", "CompleteInspect CI-1100", "Multi Inspection", "Inline", 1100, 500, (0, 600), 1.0, 0.2, 4, "Hybrid Optical", ("thickness", "surface_defect", "profile_3d")),
    EquipmentGT2("SPEC-094", "CompleteInspect CI-1500", "Multi Inspection", "Inline", 1500, 400, (0, 400), 1.2, 0.3, 6, "Multi-sensor", ("thickness", "surface_defect", "void")),
]

# ==========================================================================
# Group J — 초광폭/초고속 극단 시나리오.
# ==========================================================================
_GROUP_J: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-095", "MegaWide MW-2000", "Thickness Inspection", "Inline", 2000, 1000, (0, 500), 2.5, 0.5, None, "Laser", ("thickness",)),
    EquipmentGT2("SPEC-096", "UltraFast UF-800", "Surface Inspection", "Inline", 800, 3000, None, None, None, 20, "High-Speed Vision", ("scratch", "particle")),
    EquipmentGT2("SPEC-097", "MegaWide MW-2500", "Surface Inspection", "Inline", 2500, 1200, None, None, None, 15, "Wide-Field Vision", ("surface_defect",)),
    EquipmentGT2("SPEC-098", "UltraFast UF-1200", "Thickness Inspection", "Inline", 1200, 2800, (0, 200), 4.0, 1.0, None, "Laser", ("thickness",)),
]

# ==========================================================================
# Group K — 초미세 결함 검출 극단(Offline, 저속·초정밀).
# ==========================================================================
_GROUP_K: List[EquipmentGT2] = [
    EquipmentGT2("SPEC-099", "NanoDefect ND-150", "Surface Inspection", "Offline", 150, None, None, None, None, 0.1, "Confocal Vision", ("scratch", "particle", "pinhole")),
    EquipmentGT2("SPEC-100", "NanoDefect ND-300", "Surface Inspection", "Offline", 320, None, None, None, None, 0.05, "High Resolution Vision", ("scratch", "pinhole", "void")),
]

GROUND_TRUTH_053_100: List[EquipmentGT2] = (
    _GROUP_A + _GROUP_B + _GROUP_C + _GROUP_D + _GROUP_E + _GROUP_F
    + _GROUP_G + _GROUP_H + _GROUP_I + _GROUP_J + _GROUP_K
)

GROUND_TRUTH_053_100_BY_ID: Dict[str, EquipmentGT2] = {gt.spec_id: gt for gt in GROUND_TRUTH_053_100}

assert len(GROUND_TRUTH_053_100) == 48, f"SPEC-053~100은 정확히 48개여야 합니다(실제 {len(GROUND_TRUTH_053_100)}개)"
assert [gt.spec_id for gt in GROUND_TRUTH_053_100] == [f"SPEC-{i:03d}" for i in range(53, 101)], (
    "SPEC ID가 053~100 연속 순서가 아닙니다"
)
