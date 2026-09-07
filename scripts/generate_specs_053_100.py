"""
SPEC-053.md ~ SPEC-100.md 생성 스크립트 (Phase 1).

기존 SPEC-001~052(sample_specs/*.md)와 동일한 포맷(# Equipment Specification /
## General / ## Inspection Target / ## Measurement Performance / ## Defect
Inspection / ## System / ## Environment / ## Safety / ## Notes)을 그대로 따른다.
포맷은 SPEC-001.md ~ SPEC-052.md를 직접 읽어 확인한 것이며 추측하지 않았다.

기존 52개 파일은 건드리지 않는다 — 이 스크립트는 sample_specs/SPEC-053.md부터
SPEC-100.md까지만 새로 쓴다(덮어쓰기 전 존재 여부를 확인).

실행:
    python scripts/generate_specs_053_100.py
"""
from __future__ import annotations

import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_REPO_ROOT, "sample_specs")

# 각 행: (manufacturer, model, equipment_type, principle, mode, target_width_mm,
#         range_lo, range_hi, accuracy, repeatability(or None), z_res, xy_res(or None),
#         speed, sampling_khz(or None), defect(dict or None), optical(dict),
#         plc_mes(tuple), env(tuple), safety(tuple), note)
# defect=None -> "Defect Inspection" 섹션은 "- Not Supported"로만 렌더링된다(S4/S3/S9 시나리오).
ROWS = [
    # F1 ConfocalTech — Confocal, Thickness 중심
    dict(mfr="ConfocalTech", model="CT-100", etype="Thickness Inspection", principle="Confocal",
         mode="Inline", width=500, rng=(0, 150), acc=0.3, rep=0.15, zres=0.05, speed=150,
         defect=None, optical={"Sensor": "Confocal", "Light Source": "White LED"},
         note="Designed for continuous inline electrode thickness measurement using confocal displacement sensing."),
    dict(mfr="ConfocalTech", model="CT-300", etype="Thickness Inspection", principle="Confocal",
         mode="Offline", width=400, rng=(0, 100), acc=0.1, rep=0.05, zres=0.02, speed=20,
         defect=None, optical={"Sensor": "Confocal", "Light Source": "White LED"},
         note="High-precision offline thickness gauge; low scan speed trades throughput for sub-0.1um accuracy."),
    dict(mfr="ConfocalTech", model="CT-600", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Confocal", mode="Inline", width=700, rng=(0, 200), acc=0.4, rep=0.2, zres=0.1, speed=300,
         defect={"min": 10, "types": "Scratch, Pinhole, Coating Non-uniformity", "cls": True},
         optical={"Sensor": "Confocal", "Light Source": "White LED"},
         note="Combined thickness and surface defect inspection in a single confocal head, inline."),

    # F2 ChromaScan — Chromatic Confocal
    dict(mfr="ChromaScan", model="CC-200", etype="Thickness Inspection", principle="Chromatic Confocal",
         mode="Offline", width=350, rng=(0, 80), acc=0.08, rep=0.04, zres=0.01, speed=15,
         defect=None, optical={"Sensor": "Chromatic Confocal", "Light Source": "White LED"},
         note="Ultra-high precision offline chromatic confocal gauge for thin coating/electrode thickness."),
    dict(mfr="ChromaScan", model="CC-500", etype="3D Profile Inspection", principle="Chromatic Confocal",
         mode="Inline", width=600, rng=(0, 300), acc=0.3, rep=0.15, zres=0.05, speed=250,
         defect=None, optical={"Sensor": "Chromatic Confocal", "Light Source": "White LED"},
         note="Inline 3D profile inspection of electrode surface topology."),
    dict(mfr="ChromaScan", model="CC-900", etype="Thickness Inspection", principle="Chromatic Confocal",
         mode="Offline", width=500, rng=(0, 2000), acc=6.0, rep=3.0, zres=5.0, speed=100,
         defect=None, optical={"Sensor": "Chromatic Confocal", "Light Source": "White LED"},
         note="Wide measurement range for thick coating stacks; resolution is coarser than the CC-200/CC-500 line."),

    # F3 NIRScan — OCT-NIR
    dict(mfr="NIRScan", model="NS-400", etype="Thickness Inspection", principle="OCT-NIR",
         mode="Inline", width=600, rng=(0, 400), acc=0.8, rep=0.4, zres=0.2, speed=400,
         defect=None, optical={"Light Source": "SLD (NIR)", "Wavelength": "1310 nm"},
         note="Near-infrared OCT for inline thickness measurement of multi-layer electrode coatings."),
    dict(mfr="NIRScan", model="NS-700", etype="Coating Inspection", principle="OCT-NIR",
         mode="Offline", width=450, rng=(0, 250), acc=0.5, rep=0.25, zres=0.1, speed=50,
         defect=None, optical={"Light Source": "SLD (NIR)", "Wavelength": "1310 nm"},
         note="Offline coating thickness/uniformity analysis for R&D sample verification."),
    dict(mfr="NIRScan", model="NS-1100", etype="Thickness Inspection", principle="OCT-NIR",
         mode="Inline", width=800, rng=(0, 3000), acc=3.0, rep=1.5, zres=2.0, speed=500,
         defect=None, optical={"Light Source": "SLD (NIR)", "Wavelength": "1310 nm"},
         note="Deep measurement range for thick electrode stacks; resolution/accuracy are traded off for range."),

    # F4 DeepOCT — OCT
    dict(mfr="DeepOCT", model="DO-300", etype="Thickness Inspection", principle="OCT",
         mode="Inline", width=500, rng=(0, 300), acc=0.6, rep=0.3, zres=0.1, speed=350,
         defect=None, optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="Standard inline OCT thickness inspection for battery electrode coating."),
    dict(mfr="DeepOCT", model="DO-800", etype="Thickness Inspection", principle="OCT",
         mode="Offline", width=400, rng=(0, 120), acc=0.09, rep=0.04, zres=0.01, speed=10,
         defect=None, optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="Laboratory-grade OCT thickness gauge; very low speed maximizes accuracy for calibration use."),
    dict(mfr="DeepOCT", model="DO-1000", etype="Coating Inspection", principle="OCT",
         mode="Inline", width=750, rng=(0, 500), acc=1.0, rep=0.5, zres=0.2, speed=450,
         defect=None, optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="High-throughput inline coating thickness inspection for wide electrode lines."),

    # F5 WideScan — 2D Laser, 광폭(wide width) 강조 (S1: 폭은 크지만 범위는 작음)
    dict(mfr="WideScan", model="WS-1500", etype="Surface Inspection", principle="2D Laser Triangulation",
         mode="Inline", width=1500, rng=(0, 50), acc=0.5, rep=0.3, zres=0.2, speed=600,
         defect={"min": 20, "types": "Scratch, Contamination", "cls": False},
         optical={"Sensor": "2D Laser", "Light Source": "Laser"},
         note="Very wide inspection width (1500 mm) but a narrow Z measurement range (0~50 um) — optimized for flat, wide electrode lines rather than deep-defect profiling."),
    dict(mfr="WideScan", model="WS-1800", etype="3D Profile Inspection", principle="2D Laser Triangulation",
         mode="Inline", width=1800, rng=(0, 60), acc=0.6, rep=0.3, zres=0.2, speed=800,
         defect=None, optical={"Sensor": "2D Laser", "Light Source": "Laser"},
         note="Widest profile head in the line-up (1800 mm) with high line speed for high-throughput wide coaters; Z range remains small by design."),
    dict(mfr="WideScan", model="WS-2000", etype="Thickness Inspection", principle="2D Laser Triangulation",
         mode="Inline", width=1900, rng=(0, 30), acc=0.4, rep=0.2, zres=0.1, speed=700,
         defect=None, optical={"Sensor": "2D Laser", "Light Source": "Laser"},
         note="Widest thickness-only model in the corpus (1900 mm), paired with the smallest Z range (0~30 um) — wide-but-shallow scenario."),

    # F6 RangeMax — 3D Laser Profilometry, 범위는 크지만 해상도 낮음 (S2)
    dict(mfr="RangeMax", model="RM-600", etype="3D Profile Inspection", principle="3D Laser Profilometry",
         mode="Inline", width=600, rng=(0, 1000), acc=6.0, rep=3.0, zres=5.0, speed=300,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Large Z measurement range (0~1000 um) for deep surface features, but Z resolution (5 um) is coarser than the corpus average — range/resolution trade-off."),
    dict(mfr="RangeMax", model="RM-900", etype="Thickness Inspection", principle="3D Laser Profilometry",
         mode="Offline", width=500, rng=(0, 1500), acc=9.0, rep=4.5, zres=8.0, speed=100,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Extended thickness range (0~1500 um) for thick electrode stacks; resolution (8 um) is deliberately relaxed."),
    dict(mfr="RangeMax", model="RM-1200", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="3D Laser Profilometry", mode="Inline", width=800, rng=(0, 800), acc=4.0, rep=2.0, zres=3.0, speed=400,
         defect={"min": 25, "types": "Scratch, Pinhole", "cls": True},
         optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Combined thickness and surface defect coverage with an extended Z range at moderate resolution."),

    # F7 SpeedInspect — 고속 검사, 정밀도 낮음 (S7)
    dict(mfr="SpeedInspect", model="SI-1000", etype="Surface Inspection", principle="Machine Vision",
         mode="Inline", width=900, rng=None, acc=None, rep=None, zres=None, speed=1000,
         xy_res=30, xy_acc=25, no_thickness=True,
         defect={"min": 50, "types": "Scratch, Contamination", "cls": False},
         optical={"Camera": "CMOS Line Scan", "Light Source": "LED"},
         note="Optimized for maximum line speed (1000 mm/s) on high-throughput lines; minimum detectable defect (50 um) is coarser than precision-oriented models — speed/precision trade-off."),
    dict(mfr="SpeedInspect", model="SI-1200", etype="Surface Inspection", principle="Machine Vision",
         mode="Inline", width=1000, rng=None, acc=None, rep=None, zres=None, speed=1200,
         xy_res=35, xy_acc=30, no_thickness=True,
         defect={"min": 60, "types": "Scratch, Contamination, Particle", "cls": False},
         optical={"Camera": "CMOS Line Scan", "Light Source": "LED"},
         note="Highest surface-inspection line speed in the corpus (1200 mm/s); defect classification is not supported, favoring throughput over analysis depth."),
    dict(mfr="SpeedInspect", model="SI-1500", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Multi-sensor (Laser + Vision)", mode="Inline", width=1000, rng=(0, 300), acc=5.0, rep=2.5, zres=4.0, speed=1500,
         defect={"min": 70, "types": "Scratch, Contamination", "cls": False},
         optical={"3D Sensor": "Laser", "Camera": "CMOS", "Light Source": "Laser + LED"},
         note="Fastest combined thickness/surface-defect system in the corpus (1500 mm/s); accuracy and minimum defect size are relaxed accordingly."),

    # F8 PrecisionEdge — 정밀도 높음, 속도 낮음 (S8)
    dict(mfr="PrecisionEdge", model="PE-100", etype="Thickness Inspection", principle="Interferometry",
         mode="Offline", width=300, rng=(0, 60), acc=0.08, rep=0.04, zres=0.01, speed=15,
         defect=None, optical={"Sensor": "Interferometer", "Light Source": "White Light"},
         note="Highest-precision thickness gauge in the corpus (+/-0.08 um) at a deliberately low scan speed (15 mm/s) — precision/speed trade-off."),
    dict(mfr="PrecisionEdge", model="PE-250", etype="3D Profile Inspection", principle="Interferometry",
         mode="Offline", width=350, rng=(0, 90), acc=0.08, rep=0.04, zres=0.02, speed=20,
         defect=None, optical={"Sensor": "Interferometer", "Light Source": "White Light"},
         note="Ultra-precise offline profile inspection for R&D sample analysis; low throughput by design."),
    dict(mfr="PrecisionEdge", model="PE-400", etype="Thickness Inspection", principle="White Light Interferometry",
         mode="Offline", width=300, rng=(0, 120), acc=0.1, rep=0.05, zres=0.02, speed=25,
         defect=None, optical={"Sensor": "Interferometer", "Light Source": "White Light"},
         note="White-light interferometry variant for calibration-lab use; speed remains low to preserve accuracy."),

    # F9 ThickOnly — Thickness 지원, Surface Defect 미지원 (S3/S4)
    dict(mfr="ThickOnly", model="TO-150", etype="Thickness Inspection", principle="Laser",
         mode="Inline", width=550, rng=(0, 220), acc=0.6, rep=0.3, zres=0.12, speed=320,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Inline thickness inspection only — surface defect inspection is not supported on this model."),
    dict(mfr="ThickOnly", model="TO-350", etype="Thickness Inspection", principle="Laser",
         mode="Offline", width=450, rng=(0, 150), acc=0.3, rep=0.15, zres=0.05, speed=40,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Offline thickness-only inspection; no defect detection module fitted."),
    dict(mfr="ThickOnly", model="TO-550", etype="Thickness Inspection", principle="OCT",
         mode="Inline", width=1000, rng=(0, 350), acc=0.7, rep=0.35, zres=0.15, speed=500,
         defect=None, optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="Wide-line thickness-only inspection (1000 mm); surface defect inspection is out of scope for this model."),

    # F10 DefectOnly — Surface Defect 지원, Thickness 미지원 (S5)
    dict(mfr="DefectOnly", model="DF-200", etype="Surface Inspection", principle="Machine Vision",
         mode="Inline", width=500, rng=None, acc=None, rep=None, zres=None, speed=400,
         xy_res=20, xy_acc=15, no_thickness=True,
         defect={"min": 15, "types": "Scratch, Contamination, Particle", "cls": True},
         optical={"Camera": "CMOS", "Light Source": "LED"},
         note="Surface defect inspection only — this model has no thickness measurement channel (no Z-axis sensor)."),
    dict(mfr="DefectOnly", model="DF-450", etype="Surface Inspection", principle="Line Scan Vision",
         mode="Inline", width=1600, rng=None, acc=None, rep=None, zres=None, speed=600,
         xy_res=25, xy_acc=20, no_thickness=True,
         defect={"min": 20, "types": "Scratch, Contamination", "cls": True},
         optical={"Camera": "CMOS Line Scan", "Light Source": "LED"},
         note="Wide-width (1600 mm) surface defect inspection; thickness inspection is not supported."),
    dict(mfr="DefectOnly", model="DF-700", etype="Surface Defect Inspection", principle="High Resolution Vision",
         mode="Offline", width=400, rng=None, acc=None, rep=None, zres=None, speed=50,
         xy_res=5, xy_acc=4, no_thickness=True,
         defect={"min": 2, "types": "Scratch, Pinhole, Particle, Edge Crack", "cls": True},
         optical={"Camera": "High-Res CMOS", "Light Source": "LED"},
         note="Micro-defect surface inspection (minimum detectable defect down to 2 um); no thickness measurement capability."),

    # F11 DualCheck — Thickness + Surface Defect 모두 지원 (S6)
    dict(mfr="DualCheck", model="DC-500", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="3D Laser Profilometry", mode="Inline", width=600, rng=(0, 250), acc=0.8, rep=0.4, zres=0.15, speed=350,
         defect={"min": 15, "types": "Scratch, Pinhole, Coating Defect", "cls": True},
         optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Balanced inline thickness and surface defect inspection in a single pass."),
    dict(mfr="DualCheck", model="DC-800", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Multi-sensor (Laser + Vision)", mode="Inline", width=1000, rng=(0, 300), acc=1.2, rep=0.6, zres=0.2, speed=500,
         defect={"min": 20, "types": "Scratch, Contamination, Particle", "cls": True},
         optical={"3D Sensor": "Laser", "Camera": "CMOS", "Light Source": "Laser + LED"},
         note="Wide-line (1000 mm) combined thickness/surface-defect system for high-volume production."),
    dict(mfr="DualCheck", model="DC-1100", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Confocal", mode="Offline", width=400, rng=(0, 100), acc=0.15, rep=0.08, zres=0.03, speed=30,
         defect={"min": 5, "types": "Scratch, Pinhole, Coating Non-uniformity, Edge Crack", "cls": True},
         optical={"Sensor": "Confocal", "Light Source": "White LED"},
         note="High-precision offline combined inspection for sample audits; both thickness and fine surface defects are covered."),

    # F12 EdgeGuard — Edge Inspection
    dict(mfr="EdgeGuard", model="EG-300", etype="Edge Inspection", principle="Vision",
         mode="Inline", width=500, rng=None, acc=None, rep=None, zres=None, speed=300,
         xy_res=25, xy_acc=20, no_thickness=True,
         defect={"min": 30, "types": "Edge Crack, Burr", "cls": False},
         optical={"Camera": "CMOS", "Light Source": "LED"},
         note="Standard inline electrode edge inspection for burr/crack detection."),
    dict(mfr="EdgeGuard", model="EG-600", etype="Edge Inspection", principle="Laser + Vision",
         mode="Inline", width=700, rng=None, acc=None, rep=None, zres=None, speed=900,
         xy_res=30, xy_acc=25, no_thickness=True,
         defect={"min": 40, "types": "Edge Crack, Burr", "cls": False},
         optical={"Sensor": "Laser", "Camera": "CMOS", "Light Source": "Laser + LED"},
         note="High-speed edge inspection (900 mm/s) for fast-moving coating lines."),
    dict(mfr="EdgeGuard", model="EG-900", etype="Edge Inspection", principle="High Resolution Vision",
         mode="Offline", width=350, rng=None, acc=None, rep=None, zres=None, speed=40,
         xy_res=4, xy_acc=3, no_thickness=True,
         defect={"min": 3, "types": "Edge Crack", "cls": True},
         optical={"Camera": "High-Res CMOS", "Light Source": "LED"},
         note="Micro edge-crack detection (down to 3 um) for offline quality audits."),

    # F13 VoidDetect — Void Inspection
    dict(mfr="VoidDetect", model="VD-400", etype="Void Inspection", principle="OCT",
         mode="Inline", width=600, rng=(0, 400), acc=1.0, rep=0.5, zres=0.3, speed=350,
         defect={"min": 20, "types": "Void", "cls": False},
         optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="Inline sub-surface void detection for coated electrode layers."),
    dict(mfr="VoidDetect", model="VD-700", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="OCT", mode="Offline", width=500, rng=(0, 300), acc=0.6, rep=0.3, zres=0.15, speed=45,
         defect={"min": 10, "types": "Void", "cls": True},
         optical={"Light Source": "SLD", "Wavelength": "840 nm"},
         note="Combined thickness and void inspection for offline lab-scale verification."),
    dict(mfr="VoidDetect", model="VD-1000", etype="Void Inspection", principle="OCT-NIR",
         mode="Inline", width=800, rng=(0, 500), acc=1.5, rep=0.7, zres=0.4, speed=700,
         defect={"min": 30, "types": "Void", "cls": False},
         optical={"Light Source": "SLD (NIR)", "Wavelength": "1310 nm"},
         note="High-speed inline void detection for high-throughput coating lines."),

    # F14 CoatGauge — Coating Inspection (Spectral Reflectometry)
    dict(mfr="CoatGauge", model="CG-250", etype="Coating Inspection", principle="Spectral Reflectometry",
         mode="Offline", width=350, rng=(0, 100), acc=0.2, rep=0.1, zres=0.05, speed=20,
         defect=None, optical={"Light Source": "Broadband LED", "Spectral Range": "400-1000 nm"},
         note="Offline coating thickness/uniformity gauge using spectral reflectometry, no defect module."),
    dict(mfr="CoatGauge", model="CG-500", etype="Coating Inspection", principle="Spectral Reflectometry",
         mode="Inline", width=600, rng=(0, 200), acc=0.5, rep=0.25, zres=0.1, speed=400,
         defect=None, optical={"Light Source": "Broadband LED", "Spectral Range": "400-1000 nm"},
         note="Inline coating weight/thickness monitoring for production lines."),
    dict(mfr="CoatGauge", model="CG-750", etype="Coating Inspection", principle="Chromatic Confocal",
         mode="Inline", width=650, rng=(0, 250), acc=0.4, rep=0.2, zres=0.08, speed=450,
         defect=None, optical={"Sensor": "Chromatic Confocal", "Light Source": "White LED"},
         note="Combined coating and thickness inspection using chromatic confocal sensing."),

    # F15 ProfileMax — Profile Inspection
    dict(mfr="ProfileMax", model="PM-400", etype="3D Profile Inspection", principle="Laser Triangulation",
         mode="Inline", width=500, rng=(0, 300), acc=1.0, rep=0.5, zres=0.2, speed=300,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Standard inline 3D profile inspection using laser triangulation."),
    dict(mfr="ProfileMax", model="PM-800", etype="3D Profile Inspection", principle="3D Laser",
         mode="Inline", width=1400, rng=(0, 80), acc=0.6, rep=0.3, zres=0.15, speed=550,
         defect=None, optical={"Sensor": "Laser", "Light Source": "Laser"},
         note="Wide-width profile head (1400 mm) with a comparatively small Z range — wide-but-shallow profiling."),
    dict(mfr="ProfileMax", model="PM-1300", etype="3D Profile Inspection", principle="Structured Light",
         mode="Offline", width=400, rng=(0, 200), acc=0.2, rep=0.1, zres=0.05, speed=25,
         defect=None, optical={"Sensor": "Structured Light Projector", "Light Source": "LED"},
         note="High-precision offline structured-light profilometry for R&D surface analysis."),

    # F16 HybridMulti — Multi-sensor, 광폭+고속 flagship (S6 + wide + fast)
    dict(mfr="HybridMulti", model="HM-900", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Multi-sensor (Laser + Vision)", mode="Inline", width=1600, rng=(0, 400), acc=1.2, rep=0.6, zres=0.3, speed=1000,
         defect={"min": 25, "types": "Scratch, Contamination, Particle, Coating Defect", "cls": True},
         optical={"3D Sensor": "Laser", "Camera": "CMOS Line Scan", "Light Source": "Laser + LED"},
         note="Wide-width (1600 mm), high-speed (1000 mm/s) flagship combining thickness and surface defect inspection."),
    dict(mfr="HybridMulti", model="HM-1200", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Multi-sensor (Laser + Vision)", mode="Inline", width=1000, rng=(0, 350), acc=1.1, rep=0.55, zres=0.2, speed=650,
         defect={"min": 15, "types": "Scratch, Pinhole, Particle", "cls": True},
         optical={"3D Sensor": "Laser", "Camera": "CMOS", "Light Source": "Laser + LED"},
         note="Balanced combined thickness/surface-defect system for general-purpose production lines."),
    dict(mfr="HybridMulti", model="HM-1600", etype="Electrode Thickness & Surface Defect Inspection System",
         principle="Multi-sensor (Laser + Vision)", mode="Inline", width=1850, rng=(0, 450), acc=1.5, rep=0.7, zres=0.35, speed=1100,
         defect={"min": 30, "types": "Scratch, Contamination, Coating Defect", "cls": True},
         optical={"3D Sensor": "Laser", "Camera": "CMOS Line Scan", "Light Source": "Laser + LED"},
         note="Widest combined inspection system in the corpus (1850 mm) for extra-wide electrode coating lines."),
]

assert len(ROWS) == 48, f"expected 48 rows, got {len(ROWS)}"


def _fmt_um(value: float) -> str:
    return f"{value:g}"


def render_spec(row: dict) -> str:
    lines = []
    lines.append("# Equipment Specification")
    lines.append("")
    lines.append("## General")
    lines.append("")
    lines.append(f"- Manufacturer: {row['mfr']}")
    lines.append(f"- Model: {row['model']}")
    lines.append(f"- Equipment Type: {row['etype']}")
    lines.append(f"- Measurement Principle: {row['principle']}")
    lines.append(f"- Inspection Mode: {row['mode']}")
    lines.append("- Measurement Type: Non-contact")
    lines.append("")
    lines.append("## Inspection Target")
    lines.append("")
    lines.append("- Target: Battery Electrode")
    lines.append(f"- Maximum Electrode Width: {row['width']} mm")
    lines.append("")

    if row["rng"] is not None:
        lo, hi = row["rng"]
        lines.append("## Measurement Performance")
        lines.append("")
        lines.append("| Item | Specification |")
        lines.append("|---|---|")
        lines.append(f"| Measurement Range (Z) | {lo} ~ {hi} μm |")
        lines.append(f"| Accuracy | ±{_fmt_um(row['acc'])} μm |")
        if row.get("rep") is not None:
            lines.append(f"| Repeatability | ±{_fmt_um(row['rep'])} μm |")
        lines.append(f"| Z Resolution | {_fmt_um(row['zres'])} μm |")
        lines.append(f"| Measurement Speed | {row['speed']} mm/s |")
        lines.append("")
    else:
        # Z(두께) 채널이 없는 순수 2D 비전/엣지 검사기 — SPEC-006(VisionMeasure VM-200)
        # 패턴을 그대로 따른다: X/Y Resolution + Measurement Accuracy + Line Speed만
        # 채우고, 두께 미지원은 아래 "## Thickness Measurement" 절에서 명시한다.
        lines.append("## Measurement Performance")
        lines.append("")
        lines.append("| Item | Specification |")
        lines.append("|---|---|")
        lines.append(f"| X Resolution | {_fmt_um(row['xy_res'])} μm |")
        lines.append(f"| Y Resolution | {_fmt_um(row['xy_res'])} μm |")
        lines.append(f"| Measurement Accuracy | ±{_fmt_um(row['xy_acc'])} μm |")
        lines.append(f"| Line Speed | {row['speed']} mm/s |")
        lines.append("")

    lines.append("## Defect Inspection")
    lines.append("")
    defect = row.get("defect")
    if defect is None:
        lines.append("- Not Supported")
    else:
        lines.append("| Item | Specification |")
        lines.append("|---|---|")
        lines.append(f"| Minimum Detectable Defect | {defect['min']} μm |")
        lines.append(f"| Defect Types | {defect['types']} |")
        lines.append(f"| Classification | {'Supported' if defect['cls'] else 'Not Supported'} |")
    lines.append("")

    if row.get("no_thickness"):
        lines.append("## Thickness Measurement")
        lines.append("")
        lines.append("- Not Supported")
        lines.append("")

    lines.append("## Optical System")
    lines.append("")
    for k, v in row["optical"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    lines.append("## Interface")
    lines.append("")
    lines.append("- PLC: Supported")
    lines.append("- MES: Supported")
    lines.append("")

    lines.append("## Environment")
    lines.append("")
    lines.append("- Operating Temperature: 10 ~ 40 °C")
    lines.append("- Humidity: 20 ~ 80 %RH")
    lines.append("")

    lines.append("## Safety")
    lines.append("")
    if "Laser" in row["principle"] or any("Laser" in v for v in row["optical"].values()):
        lines.append("- Laser Class: Class 2")
    lines.append("- Emergency Stop: Supported")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(row["note"])
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    start_id = 53
    written = []
    for offset, row in enumerate(ROWS):
        spec_id = start_id + offset
        assert spec_id <= 100
        filename = f"SPEC-{spec_id:03d}.md"
        path = os.path.join(_OUT_DIR, filename)
        if os.path.exists(path):
            raise SystemExit(f"거부: {filename}이 이미 존재합니다 — 기존 파일을 덮어쓰지 않습니다.")
        content = render_spec(row)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        written.append(filename)
    print(f"작성 완료: {written[0]} ~ {written[-1]} ({len(written)}개)")


if __name__ == "__main__":
    main()
