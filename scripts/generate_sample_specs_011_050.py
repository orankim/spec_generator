"""
sample_specs/SPEC-011.md ~ SPEC-050.md(40개)를 tests/ground_truth_data.py의
GROUND_TRUTH로부터 생성한다. SPEC-001.md ~ SPEC-010.md는 절대 건드리지 않는다
(이 스크립트는 SPEC-011 이상 번호만 쓴다).

재실행하면 SPEC-011~050을 GROUND_TRUTH 기준으로 다시 생성한다(idempotent) —
Ground Truth 자체를 바꿀 때 문서를 다시 만들어야 하면 이 스크립트를 다시 돌리면
된다. 사용법:

    python scripts/generate_sample_specs_011_050.py

생성 후에는 tests/test_sample_specs_ground_truth.py로 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from tests.ground_truth_data import GROUND_TRUTH, ITEM_DEFECT_LABELS, EquipmentGT, defect_type_items  # noqa: E402

_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"


def _split_manufacturer_model(model_full: str) -> Tuple[str, str]:
    """"ThicknessPro TP-200" -> ("ThicknessPro", "TP-200"). 마지막 토큰(하이픈+숫자를
    포함하는 모델 코드)을 Model로, 나머지를 Manufacturer로 본다."""
    parts = model_full.split(" ")
    return " ".join(parts[:-1]), parts[-1]


def _fmt_num(value: float) -> str:
    """정수면 소수점 없이, 아니면 그대로("0.1", "0.01" 등 유지)."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


_TARGET_BY_TYPE = {
    "Thickness Inspection": "Battery Electrode",
    "Surface Inspection": "Battery Electrode Surface",
    "Edge Inspection": "Battery Electrode Edge",
    "OCT Inspection": "Battery Electrode Coating / Internal Structure",
    "Coating Inspection": "Battery Electrode Coating",
    "Void Inspection": "Battery Electrode Internal Structure",
    "3D Profile Inspection": "Battery Electrode Surface Profile",
    "Multi Inspection": "Battery Electrode",
    "Basic Inspection": "Battery Electrode",
    "Hybrid Inspection": "Battery Electrode",
}

_LIGHT_SOURCE_BY_PRINCIPLE_KEYWORD = (
    ("laser", "Laser"),
    ("oct", "Near Infrared"),
    ("interferometry", "Broadband Light"),
    ("confocal", "White LED"),
    ("vision", "LED"),
    ("multi-sensor", "LED"),
    ("hybrid", "LED"),
)


def _light_source(principle: str) -> str:
    p = principle.lower()
    for keyword, source in _LIGHT_SOURCE_BY_PRINCIPLE_KEYWORD:
        if keyword in p:
            return source
    return "LED"


_NOTES_BY_TYPE = {
    "Thickness Inspection": {
        "Inline": "Designed for continuous inline electrode thickness measurement.",
        "Offline": "Optimized for offline high-precision electrode thickness measurement.",
    },
    "Surface Inspection": {
        "Inline": "Designed for high-speed inline surface defect detection on battery electrodes.",
        "Offline": "Optimized for offline high-resolution surface defect analysis.",
    },
    "Edge Inspection": {
        "Inline": "Specialized system for inline battery electrode edge defect inspection.",
        "Offline": "Optimized for offline high-resolution electrode edge inspection.",
    },
    "OCT Inspection": {
        "Inline": "Combines OCT-based thickness and internal structure inspection for inline use.",
        "Offline": "Optical coherence tomography system for offline thickness and structure analysis.",
    },
    "Coating Inspection": {
        "Inline": "Optimized for inline coating thickness and coating uniformity inspection.",
        "Offline": "Designed for offline coating thickness and uniformity characterization.",
    },
    "Void Inspection": {
        "Inline": "Dedicated inline system for internal void detection via OCT.",
        "Offline": "Dedicated offline system for internal void detection via OCT.",
    },
    "3D Profile Inspection": {
        "Inline": "Performs continuous inline three-dimensional surface profiling of battery electrodes.",
        "Offline": "High-resolution offline three-dimensional surface profiling system.",
    },
    "Multi Inspection": {
        "Inline": "Combines multiple sensing modalities for comprehensive inline electrode inspection.",
        "Offline": "Combines multiple sensing modalities for comprehensive offline electrode inspection.",
    },
    "Basic Inspection": {
        "Inline": "Entry-level inline thickness inspection system.",
        "Offline": "Entry-level offline thickness inspection system.",
    },
    "Hybrid Inspection": {
        "Inline": "Hybrid optical inspection platform covering multiple electrode quality attributes.",
        "Offline": "Hybrid optical inspection platform for offline multi-attribute electrode analysis.",
    },
}


def _defect_inspection_section(gt: EquipmentGT) -> str:
    items = defect_type_items(gt.items)
    if not items:
        return "## Defect Inspection\n\n- Not Supported\n"
    labels = [ITEM_DEFECT_LABELS[i] for i in items]
    rows = [f"| Defect Types | {', '.join(labels)} |"]
    if gt.min_defect_um is not None:
        rows.insert(0, f"| Minimum Detectable Defect | {_fmt_num(gt.min_defect_um)} μm |")
    table = "| Item | Specification |\n|---|---|\n" + "\n".join(rows)
    return f"## Defect Inspection\n\n{table}\n"


def _measurement_performance_section(gt: EquipmentGT) -> Optional[str]:
    rows = []
    if gt.range_um is not None:
        lo, hi = gt.range_um
        rows.append(f"| Measurement Range (Z) | {_fmt_num(lo)} ~ {_fmt_num(hi)} μm |")
    if gt.accuracy_um is not None:
        rows.append(f"| Accuracy | ±{_fmt_num(gt.accuracy_um)} μm |")
    if gt.resolution_um is not None:
        rows.append(f"| Z Resolution | {_fmt_num(gt.resolution_um)} μm |")
    if gt.speed_mm_s is not None:
        rows.append(f"| Measurement Speed | {_fmt_num(gt.speed_mm_s)} mm/s |")
    if not rows:
        return None
    table = "| Item | Specification |\n|---|---|\n" + "\n".join(rows)
    return f"## Measurement Performance\n\n{table}\n"


def render_spec_markdown(gt: EquipmentGT) -> str:
    manufacturer, model = _split_manufacturer_model(gt.model_full)
    target_desc = _TARGET_BY_TYPE.get(gt.equipment_type, "Battery Electrode")
    light_source = _light_source(gt.principle)
    notes = _NOTES_BY_TYPE.get(gt.equipment_type, {}).get(gt.mode, "Designed for battery electrode inspection.")

    sections = ["# Equipment Specification", ""]

    sections += [
        "## General",
        "",
        f"- Manufacturer: {manufacturer}",
        f"- Model: {model}",
        f"- Equipment Type: {gt.equipment_type}",
        f"- Measurement Principle: {gt.principle}",
        f"- Inspection Mode: {gt.mode}",
        "- Measurement Type: Non-contact",
        "",
    ]

    target_lines = ["## Inspection Target", "", f"- Target: {target_desc}"]
    if gt.width_mm is not None:
        target_lines.append(f"- Maximum Electrode Width: {_fmt_num(gt.width_mm)} mm")
    sections += target_lines + [""]

    mp_section = _measurement_performance_section(gt)
    if mp_section is not None:
        sections += [mp_section]

    sections += [_defect_inspection_section(gt)]

    sections += [
        "## System",
        "",
        "- Camera: CMOS",
        f"- Light Source: {light_source}",
        "- Data Output: Ethernet",
        "- PLC Interface: Supported",
        "- MES Interface: Supported",
        "",
    ]

    if gt.mode == "Inline":
        temp, humidity = "5 ~ 40 °C", "20 ~ 85 %RH"
    else:
        temp, humidity = "18 ~ 28 °C", "30 ~ 70 %RH"
    sections += [
        "## Environment",
        "",
        f"- Operating Temperature: {temp}",
        f"- Humidity: {humidity}",
        "",
    ]

    if "laser" in gt.principle.lower():
        sections += [
            "## Safety",
            "",
            "- Laser Safety: Class 2",
            "- Emergency Stop: Supported",
            "",
        ]

    sections += ["## Notes", "", notes, ""]

    return "\n".join(sections)


def main() -> None:
    _SAMPLE_SPECS_DIR.mkdir(exist_ok=True)
    written = []
    for gt in GROUND_TRUTH:
        content = render_spec_markdown(gt)
        out_path = _SAMPLE_SPECS_DIR / f"{gt.spec_id}.md"
        out_path.write_text(content, encoding="utf-8")
        written.append(out_path.name)
    print(f"{len(written)}개 파일 생성 완료: {written[0]} ~ {written[-1]}")


if __name__ == "__main__":
    main()
