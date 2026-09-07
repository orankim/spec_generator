"""
QUOTE-001.md ~ QUOTE-100.md 생성 스크립트 (Phase 4).

docs/QUOTATION_MARKDOWN_FORMAT.md(Phase 3 설계)를 따른다. sample_specs/SPEC-NNN.md
와 파일명 번호로 1:1 연결하며, Manufacturer/Model은 해당 SPEC 파일에서 직접 읽어
그대로 옮긴다(전사 실수 방지 — 하드코딩하지 않음).

100개가 전부 같은 패턴이 되지 않도록 10가지 견적 구성 패턴(A~J)을 idx % 10으로
순환 배정한다(요청서 4단계 Case A~K 커버). Case H(동일 장비, 다른 견적 구성)는
별도로 몇 개 SPEC에 대해 "-B" 접미사 견적을 추가로 만든다. Case K(계산 오류
테스트 데이터)는 sample_quotes/error_cases/에 SPEC과 연결하지 않고 별도 생성한다
(generate_quote_error_cases.py에서 처리 — 이 스크립트는 정상 데이터만 만든다).

모든 가격은 가상의 Sample/Test 데이터다. 실제 업체 견적이 아니다.

실행:
    python scripts/generate_quotes_001_100.py
"""
from __future__ import annotations

import os
import re
from glob import glob

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPECS_DIR = os.path.join(_REPO_ROOT, "sample_specs")
_OUT_DIR = os.path.join(_REPO_ROOT, "sample_quotes")

_DISCLAIMER = (
    "SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 개발 및 테스트 목적으로만 "
    "사용됩니다. 가격은 시장가격이나 적정가격을 나타내지 않습니다."
)


def _read_spec_identity(spec_id: str) -> dict:
    path = os.path.join(_SPECS_DIR, f"{spec_id}.md")
    text = open(path, "r", encoding="utf-8").read()
    mfr = re.search(r"Manufacturer:\s*(.+)", text)
    model = re.search(r"Model:\s*(.+)", text)
    etype = re.search(r"Equipment Type:\s*(.+)", text)
    return {
        "manufacturer": mfr.group(1).strip() if mfr else "UNKNOWN",
        "model": model.group(1).strip() if model else "UNKNOWN",
        "equipment_type": etype.group(1).strip() if etype else "",
    }


def _tier_multiplier(identity: dict) -> float:
    mfr = identity["manufacturer"].lower()
    etype = identity["equipment_type"].lower()
    if any(k in mfr for k in ("multi", "hybrid", "dualcheck", "totalinspect")) or "thickness & surface defect" in etype:
        return 1.6
    if any(k in mfr for k in ("precision", "confocal", "interfero", "oct", "chroma", "deepoct")):
        return 1.3
    if any(k in mfr for k in ("basic", "defectonly")) or etype in ("surface inspection", "edge inspection"):
        return 0.85
    return 1.0


def _round10k(v: float) -> int:
    """모든 개별 금액(단가/옵션/부대비용/할인)을 가장 먼저 만 원 단위로 반올림해
    정수로 고정한다 — 이후 모든 합계는 이 정수들끼리만 더하므로, 화면에 표시되는
    개별 값과 Subtotal/Grand Total이 항상 정확히 일치한다(반올림을 표시 시점에
    각자 따로 하면 Subtotal != 개별 항목 합, Grand Total != Subtotal + VAT 같은
    누적 오차가 생긴다 — 실제로 처음 구현에서 발견/수정한 문제)."""
    return int(round(v / 10_000) * 10_000)


def _fmt_amount(v: float) -> str:
    return f"{int(round(v)):,.0f}"


def _base_price(idx: int, identity: dict) -> int:
    raw = 50_000_000 + (idx * 900_000) % 40_000_000
    return _round10k(raw * _tier_multiplier(identity))


_PATTERN_LABELS = {
    0: "complete_package",
    1: "cheap_base_required_option",
    2: "expensive_bundled",
    3: "installation_excluded",
    4: "vat_billed_separately",
    5: "spare_parts_excluded",
    6: "component_excluded",
    7: "minimal_quote",
    8: "discount_applied",
    9: "quantity_multiple",
}

# Case H(요청서 4단계): 동일 장비에 대해 서로 다른 두 번째 견적("-B")을 추가로 만든다.
_DUAL_QUOTE_SPEC_IDS = {"SPEC-005", "SPEC-030", "SPEC-051", "SPEC-077", "SPEC-095"}


def build_quote(idx: int, spec_id: str, variant: str = "") -> str:
    identity = _read_spec_identity(spec_id)
    pattern = _PATTERN_LABELS[idx % 10]
    base = _base_price(idx, identity)

    equipment_item = f"{identity['manufacturer']} {identity['model']} (Main Unit)"
    equipment_qty = 1
    options: list[tuple[str, int, float]] = []  # (item, qty, unit_price)
    additional: list[tuple[str, float]] = []
    excluded: list[str] = []
    discount_amount = 0.0
    vat_included_in_grand_total = True
    vat_note = "10%"

    def opt(item: str, qty: int, raw_unit_price: float) -> tuple[str, int, int]:
        return (item, qty, _round10k(raw_unit_price))

    def add(item: str, raw_amount: float) -> tuple[str, int]:
        return (item, _round10k(raw_amount))

    if pattern == "complete_package" or variant == "complete":
        options = [
            opt("PLC/MES Interface Module", 1, base * 0.04),
            opt("Extended Warranty (+1 year)", 1, base * 0.05),
        ]
        additional = [
            add("Installation", base * 0.06),
            add("Commissioning", base * 0.03),
            add("Training (on-site, 3 days)", base * 0.015),
            add("Spare Parts Kit (1 year)", base * 0.02),
        ]
    elif pattern == "cheap_base_required_option":
        base = _round10k(base * 0.8)
        options = [opt("PLC/MES Interface Module (Required for line integration)", 1, base * 0.18)]
        additional = [add("Installation", base * 0.05)]
    elif pattern == "expensive_bundled" or variant == "bundled":
        base = _round10k(base * 1.25)
        options = [opt("Extended Warranty (+1 year)", 1, base * 0.03)]
        additional = [add("Installation", base * 0.04), add("Commissioning", base * 0.02)]
    elif pattern == "installation_excluded":
        options = [opt("PLC/MES Interface Module", 1, base * 0.04)]
        additional = [add("Commissioning", base * 0.03), add("Training (on-site, 2 days)", base * 0.012)]
        excluded.append("Installation service (quoted separately upon site survey)")
    elif pattern == "vat_billed_separately":
        options = [opt("Extended Warranty (+1 year)", 1, base * 0.05)]
        additional = [add("Installation", base * 0.06), add("Spare Parts Kit (1 year)", base * 0.02)]
        vat_included_in_grand_total = False
    elif pattern == "spare_parts_excluded":
        options = [opt("PLC/MES Interface Module", 1, base * 0.04)]
        additional = [add("Installation", base * 0.06), add("Commissioning", base * 0.03)]
        excluded.append("Spare Parts (available as a separate service contract)")
    elif pattern == "component_excluded":
        options = [opt("Extended Warranty (+1 year)", 1, base * 0.05)]
        additional = [add("Installation", base * 0.06), add("Training (on-site, 3 days)", base * 0.015)]
        excluded.append("Calibration certificate (traceable, issued on request at extra cost)")
        excluded.append("Data logging / SPC software license")
    elif pattern == "minimal_quote" or variant == "minimal":
        excluded = [
            "Installation",
            "Commissioning",
            "Training",
            "Spare Parts",
            "PLC/MES interface (available as an option, not included)",
        ]
    elif pattern == "discount_applied":
        options = [opt("PLC/MES Interface Module", 1, base * 0.04), opt("Extended Warranty (+1 year)", 1, base * 0.05)]
        additional = [add("Installation", base * 0.06), add("Commissioning", base * 0.03)]
        discount_amount = -_round10k(base * 0.05)
    elif pattern == "quantity_multiple":
        options = [
            opt("Extended Warranty (+1 year)", 2, base * 0.05),
            opt("Spare Camera/Sensor Module", 3, base * 0.02),
        ]
        additional = [add("Installation", base * 0.06), add("Commissioning", base * 0.03)]

    equipment_amount = equipment_qty * base
    options_subtotal = sum(qty * price for _, qty, price in options)
    additional_subtotal = sum(amt for _, amt in additional)
    subtotal_before_vat = equipment_amount + options_subtotal + additional_subtotal + discount_amount
    vat_amount = _round10k(subtotal_before_vat * 0.10)
    grand_total = subtotal_before_vat + vat_amount if vat_included_in_grand_total else subtotal_before_vat

    lines: list[str] = []
    lines.append("# Equipment Quotation")
    lines.append("")
    lines.append("## General")
    lines.append("")
    lines.append(f"- Manufacturer: {identity['manufacturer']}")
    lines.append(f"- Model: {identity['model']}")
    lines.append(f"- Linked Specification: {spec_id}.md")
    quote_no = f"Q-2026-{idx:04d}{variant.upper()[:1]}" if variant else f"Q-2026-{idx:04d}"
    lines.append(f"- Quote No.: {quote_no}")
    month = (idx % 12) + 1
    day = (idx % 27) + 1
    lines.append(f"- Quote Date: 2026-{month:02d}-{day:02d}")
    lines.append("- Currency: KRW")
    lines.append("")

    lines.append("## Equipment")
    lines.append("")
    lines.append("| Item | Quantity | Unit Price | Amount |")
    lines.append("|---|---|---|---|")
    lines.append(f"| {equipment_item} | {equipment_qty} | {_fmt_amount(base)} | {_fmt_amount(equipment_amount)} |")
    lines.append("")

    if options:
        lines.append("## Options")
        lines.append("")
        lines.append("| Item | Quantity | Unit Price | Amount |")
        lines.append("|---|---|---|---|")
        for item, qty, price in options:
            lines.append(f"| {item} | {qty} | {_fmt_amount(price)} | {_fmt_amount(qty * price)} |")
        lines.append("")

    if additional:
        lines.append("## Additional Cost")
        lines.append("")
        lines.append("| Item | Amount |")
        lines.append("|---|---|")
        for item, amt in additional:
            lines.append(f"| {item} | {_fmt_amount(amt)} |")
        lines.append("")

    if excluded:
        lines.append("## Excluded Items")
        lines.append("")
        for item in excluded:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## Commercial Terms")
    lines.append("")
    if discount_amount != 0:
        lines.append(f"- Discount: {_fmt_amount(discount_amount)} KRW")
    else:
        lines.append("- Discount: None")
    lines.append("- Payment: 30% advance, 60% on delivery, 10% after acceptance")
    lines.append(f"- Delivery: {8 + (idx % 10)} weeks after order")
    lines.append("- Warranty: 12 months parts and labor")
    if vat_included_in_grand_total:
        lines.append(f"- VAT: {vat_note} (included in Grand Total below)")
    else:
        lines.append(f"- VAT: {vat_note} (NOT included in Grand Total below — added separately upon invoicing)")
    lines.append("")

    lines.append("## Total")
    lines.append("")
    lines.append("| Item | Amount |")
    lines.append("|---|---|")
    lines.append(f"| Equipment Subtotal | {_fmt_amount(equipment_amount)} |")
    if options:
        lines.append(f"| Options Subtotal | {_fmt_amount(options_subtotal)} |")
    if additional:
        lines.append(f"| Additional Cost Subtotal | {_fmt_amount(additional_subtotal)} |")
    if discount_amount != 0:
        lines.append(f"| Discount | {_fmt_amount(discount_amount)} |")
    lines.append(f"| Subtotal (before VAT) | {_fmt_amount(subtotal_before_vat)} |")
    if vat_included_in_grand_total:
        lines.append(f"| VAT (10%) | {_fmt_amount(vat_amount)} |")
        lines.append(f"| Grand Total | {_fmt_amount(grand_total)} |")
    else:
        lines.append(f"| VAT (10%, billed separately, not in Grand Total) | {_fmt_amount(vat_amount)} |")
        lines.append(f"| Grand Total (excl. VAT) | {_fmt_amount(grand_total)} |")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(_DISCLAIMER)
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    os.makedirs(_OUT_DIR, exist_ok=True)
    spec_paths = sorted(glob(os.path.join(_SPECS_DIR, "SPEC-*.md")))
    assert len(spec_paths) == 100, f"expected 100 SPEC files, found {len(spec_paths)}"

    written = []
    for idx, path in enumerate(spec_paths, start=1):
        spec_id = os.path.splitext(os.path.basename(path))[0]
        content = build_quote(idx, spec_id)
        out_path = os.path.join(_OUT_DIR, f"QUOTE-{idx:03d}.md")
        if os.path.exists(out_path):
            raise SystemExit(f"거부: {out_path}가 이미 존재합니다 — 기존 파일을 덮어쓰지 않습니다.")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        written.append(out_path)

    # Case H: 동일 장비, 다른 견적 구성("-B")
    spec_id_by_num = {os.path.splitext(os.path.basename(p))[0]: i + 1 for i, p in enumerate(spec_paths)}
    variant_cycle = ["minimal", "bundled", "complete", "minimal", "bundled"]
    for spec_id, variant in zip(sorted(_DUAL_QUOTE_SPEC_IDS), variant_cycle):
        idx = spec_id_by_num[spec_id]
        content = build_quote(idx, spec_id, variant=variant)
        num = int(spec_id.split("-")[1])
        out_path = os.path.join(_OUT_DIR, f"QUOTE-{num:03d}-B.md")
        if os.path.exists(out_path):
            raise SystemExit(f"거부: {out_path}가 이미 존재합니다.")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        written.append(out_path)

    print(f"작성 완료: {len(written)}개 (QUOTE-001.md ~ QUOTE-100.md + {len(_DUAL_QUOTE_SPEC_IDS)}개 Case H 대안 견적)")


if __name__ == "__main__":
    main()
