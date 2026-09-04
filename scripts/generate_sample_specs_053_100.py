"""
sample_specs/SPEC-053.md ~ SPEC-100.md(48개, SPEC 100개 확장 Phase 1)를
tests/ground_truth_data_053_100.py의 GROUND_TRUTH_053_100으로부터 생성한다.
SPEC-001.md ~ SPEC-052.md는 절대 건드리지 않는다(이 스크립트는 SPEC-053
이상 번호만 쓴다).

scripts/generate_sample_specs_011_050.py(기존 40개 생성기)와 같은 패턴을
따르되, 공통 매핑 테이블(Equipment Type -> Target 설명/Notes/Light Source)은
그 모듈에서 그대로 import해서 재사용한다(같은 개념을 다시 정의하지 않음 —
기존 파일을 수정하지 않고 읽기 전용으로만 참조).

기존 생성기에 없던 것 하나만 추가한다: EquipmentGT2.thickness_not_supported가
True면 "## Thickness Measurement\n\n- Not Supported\n" 절을 덧붙인다(SPEC-006과
동일한 패턴, agent.candidate_matcher._THICKNESS_NOT_SUPPORTED_RE가 인식) —
"Surface Defect는 지원하지만 Thickness는 명시적으로 미지원"인 후보를 만들기 위함.

재실행하면 SPEC-053~100을 Ground Truth 기준으로 다시 생성한다(idempotent).
사용법:

    python scripts/generate_sample_specs_053_100.py

생성 후에는 tests/test_sample_specs_053_100_ground_truth.py로 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.generate_sample_specs_011_050 import (  # noqa: E402
    _fmt_num,
    _light_source,
    _NOTES_BY_TYPE,
    _split_manufacturer_model,
    _TARGET_BY_TYPE,
)
from tests.ground_truth_data import ITEM_DEFECT_LABELS, defect_type_items  # noqa: E402
from tests.ground_truth_data_053_100 import GROUND_TRUTH_053_100, EquipmentGT2  # noqa: E402

_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"


def _defect_inspection_section(gt: EquipmentGT2) -> str:
    items = defect_type_items(gt.items)
    if not items:
        return "## Defect Inspection\n\n- Not Supported\n"
    labels = [ITEM_DEFECT_LABELS[i] for i in items]
    rows = [f"| Defect Types | {', '.join(labels)} |"]
    if gt.min_defect_um is not None:
        rows.insert(0, f"| Minimum Detectable Defect | {_fmt_num(gt.min_defect_um)} μm |")
    table = "| Item | Specification |\n|---|---|\n" + "\n".join(rows)
    return f"## Defect Inspection\n\n{table}\n"


def _measurement_performance_section(gt: EquipmentGT2) -> Optional[str]:
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


def render_spec_markdown(gt: EquipmentGT2) -> str:
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

    # 기존 생성기(011~050)에는 없던 부분 — "Thickness는 미지원"을 명시적으로
    # 밝히는 후보(Group G)를 만들기 위한 절. SPEC-006과 동일한 heading/문구
    # 패턴이어야 agent.candidate_matcher._THICKNESS_NOT_SUPPORTED_RE가 인식한다.
    if gt.thickness_not_supported:
        sections += ["## Thickness Measurement", "", "- Not Supported", ""]

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
    for gt in GROUND_TRUTH_053_100:
        content = render_spec_markdown(gt)
        out_path = _SAMPLE_SPECS_DIR / f"{gt.spec_id}.md"
        out_path.write_text(content, encoding="utf-8")
        written.append(out_path.name)
    print(f"{len(written)}개 파일 생성 완료: {written[0]} ~ {written[-1]}")


if __name__ == "__main__":
    main()
