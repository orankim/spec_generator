import os
import glob
import re

SPEC_DIR = "sample_specs"

EXPECTED_SECTIONS = [
    "1. General Specification",
    "2. Inspection Target",
    "3. Inspection Requirements",
    "4. Measurement Performance",
    "5. Spatial Performance",
    "6. Optical System",
    "7. Defect Inspection",
    "7-1. Inspection Performance",
    "8. System Configuration",
    "9. Interfaces / Data",
    "10. Environment",
    "11. Safety",
    "12. Sources / Notes"
]

DETAIL_TABLE_SECTIONS = [
    "2. Inspection Target",
    "3. Inspection Requirements",
    "4. Measurement Performance",
    "5. Spatial Performance",
    "7. Defect Inspection",
    "7-1. Inspection Performance"
]

TWO_COL_SECTIONS = [
    "1. General Specification",
    "6. Optical System",
    "8. System Configuration",
    "9. Interfaces / Data",
    "10. Environment",
    "11. Safety",
    "12. Sources / Notes"
]

def validate_file(fpath):
    fname = os.path.basename(fpath)
    errors = []

    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = [l.strip() for l in content.splitlines()]

    # 1. H1 Equipment Name
    h1_lines = [l for l in lines if l.startswith("# ")]
    if not h1_lines:
        errors.append("Missing H1 Equipment Name heading")
    else:
        eq_name = h1_lines[0][2:].strip()
        if not eq_name or eq_name == "UNKNOWN":
            errors.append("Equipment Name is empty or UNKNOWN")

    # 2. Check 12 Sections
    h2_lines = [l[3:].strip() for l in lines if l.startswith("## ")]
    if h2_lines != EXPECTED_SECTIONS:
        errors.append(f"Section mismatch.\n  Expected: {EXPECTED_SECTIONS}\n  Found:    {h2_lines}")

    # Parse sections and tables
    current_sec = None
    sec_content = {sec: [] for sec in EXPECTED_SECTIONS}
    for l in lines:
        if l.startswith("## "):
            sec_title = l[3:].strip()
            if sec_title in EXPECTED_SECTIONS:
                current_sec = sec_title
        elif current_sec:
            sec_content[current_sec].append(l)

    # 3. Check Detail Table columns and status/source logic
    for sec in DETAIL_TABLE_SECTIONS:
        sec_lines = sec_content[sec]
        headers = []
        rows = []
        for l in sec_lines:
            if l.startswith("|") and "|" in l[1:]:
                parts = [p.strip() for p in l.strip("|").split("|")]
                if not headers and parts[0] == "Item":
                    headers = parts
                elif headers and not all(c in "-" for c in parts[0]):
                    rows.append(parts)
        
        expected_cols = ["Item", "Unit", "Specification", "Status", "Source"]
        if headers != expected_cols:
            errors.append(f"Section [{sec}] header error. Found: {headers}, Expected: {expected_cols}")

        for r in rows:
            if len(r) != 5:
                errors.append(f"Section [{sec}] row invalid length: {r}")
                continue
            item, unit, spec, status, source = r
            if spec != "UNKNOWN":
                if status != "VERIFIED":
                    errors.append(f"Section [{sec}] item [{item}] has spec '{spec}' but status is '{status}' (expected VERIFIED)")
                if source != fname:
                    errors.append(f"Section [{sec}] item [{item}] has status VERIFIED but source is '{source}' (expected {fname})")
            else:
                if status != "UNKNOWN":
                    errors.append(f"Section [{sec}] item [{item}] has spec UNKNOWN but status is '{status}' (expected UNKNOWN)")
                if source != "-":
                    errors.append(f"Section [{sec}] item [{item}] has spec UNKNOWN but source is '{source}' (expected -)")

    # 4. Check 2-Column Tables
    for sec in TWO_COL_SECTIONS:
        sec_lines = sec_content[sec]
        headers = []
        rows = []
        for l in sec_lines:
            if l.startswith("|") and "|" in l[1:]:
                parts = [p.strip() for p in l.strip("|").split("|")]
                if not headers and parts[0] == "Item":
                    headers = parts
                elif headers and not all(c in "-" for c in parts[0]):
                    rows.append(parts)
        
        expected_cols = ["Item", "Specification"]
        if headers != expected_cols:
            errors.append(f"Section [{sec}] header error. Found: {headers}, Expected: {expected_cols}")

        for r in rows:
            if len(r) != 2:
                errors.append(f"Section [{sec}] row invalid length: {r}")

    # 5. Check Source File in 12. Sources / Notes
    sec12_lines = sec_content["12. Sources / Notes"]
    source_file_found = False
    for l in sec12_lines:
        if "Source File" in l and fname in l:
            source_file_found = True
            break
    if not source_file_found:
        errors.append(f"Section 12. Sources / Notes missing Source File entry pointing to {fname}")

    return errors

def main():
    spec_files = sorted(glob.glob(os.path.join(SPEC_DIR, "SPEC-*.md")))
    print(f"Validating {len(spec_files)} SPEC files in {SPEC_DIR}...")

    total = len(spec_files)
    passed = 0
    failed = 0

    for fpath in spec_files:
        errors = validate_file(fpath)
        fname = os.path.basename(fpath)
        if not errors:
            passed += 1
        else:
            failed += 1
            print(f"❌ {fname} failed validation:")
            for err in errors:
                print(f"   - {err}")

    print(f"\nValidation Summary: {passed}/{total} PASS ({failed} FAIL)")
    if failed == 0:
        print("[PASS] ALL SPEC FILES PASSED SCHEMA VALIDATION!")
    return failed == 0

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
