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

def validate_ground_truth_dataset():
    spec_files = sorted(glob.glob(os.path.join(SPEC_DIR, "SPEC-*.md")))
    if len(spec_files) != 50:
        print(f"❌ Error: Expected 50 spec files, found {len(spec_files)}")
        return False

    errors = []
    eq_names = set()
    mfg_models = set()
    spec_summaries = {}

    forbidden_tokens = ["UNKNOWN", "unknown", "N/A", "TBD", "Not Specified"]

    for fpath in spec_files:
        fname = os.path.basename(fpath)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        lines = [l.strip() for l in content.splitlines()]

        # 1. Heading H1
        h1_lines = [l for l in lines if l.startswith("# ")]
        if not h1_lines:
            errors.append(f"{fname}: Missing H1 Equipment Name")
            continue
        eq_name = h1_lines[0][2:].strip()
        if eq_name in eq_names:
            errors.append(f"{fname}: Duplicate Equipment Name '{eq_name}'")
        eq_names.add(eq_name)

        # 2. Check 12 Sections
        h2_lines = [l[3:].strip() for l in lines if l.startswith("## ")]
        if h2_lines != EXPECTED_SECTIONS:
            errors.append(f"{fname}: Section headers mismatch")

        # 3. Check forbidden tokens
        for token in forbidden_tokens:
            if token in content:
                # Count occurrences
                cnt = content.count(token)
                errors.append(f"{fname}: Found forbidden token '{token}' ({cnt} occurrences)")

        # 4. Check tables & status/source
        current_sec = None
        sec_content = {sec: [] for sec in EXPECTED_SECTIONS}
        for l in lines:
            if l.startswith("## "):
                sec_title = l[3:].strip()
                if sec_title in EXPECTED_SECTIONS:
                    current_sec = sec_title
            elif current_sec:
                sec_content[current_sec].append(l)

        summary = {"fname": fname, "eq_name": eq_name}
        for sec_name, sec_lines in sec_content.items():
            for l in sec_lines:
                if l.startswith("|") and "|" in l[1:]:
                    parts = [p.strip() for p in l.strip("|").split("|")]
                    if len(parts) >= 2 and parts[0] not in ("Item", "---") and not all(c in "-" for c in parts[0]):
                        item = parts[0]
                        if len(parts) == 5: # Detail table
                            unit, spec, status, source = parts[1], parts[2], parts[3], parts[4]
                            if status != "VERIFIED":
                                errors.append(f"{fname} [{sec_name}] item '{item}': status is '{status}' (expected VERIFIED)")
                            if source != fname:
                                errors.append(f"{fname} [{sec_name}] item '{item}': source is '{source}' (expected {fname})")
                            summary[item] = spec
                        elif len(parts) == 2: # 2-col table
                            spec = parts[1]
                            summary[item] = spec
                            if item == "Manufacturer":
                                summary["mfg"] = spec
                            elif item == "Model":
                                summary["model"] = spec
                            elif item == "Measurement Principle":
                                summary["principle"] = spec
                            elif item == "Inline / Offline":
                                summary["mode"] = spec

        mfg_model = f"{summary.get('mfg')}_{summary.get('model')}"
        if mfg_model in mfg_models:
            errors.append(f"{fname}: Duplicate Manufacturer+Model '{mfg_model}'")
        mfg_models.add(mfg_model)

        spec_summaries[fname] = summary

    # 5. Check Test Eligibility (Test 1 ~ 5)
    test_1_pass = []
    test_2_pass = []
    test_3_pass = []
    test_4_pass = []
    test_5_pass = []

    for fname, s in spec_summaries.items():
        w = float(s.get("Width", "0"))
        mode = s.get("mode", "").lower()
        items = s.get("Inspection Items", "").lower()
        principle = s.get("principle", "").lower()

        raw_speed = s.get("Measurement Speed", "0").replace("mm/s", "").strip()
        speed = float(raw_speed) if raw_speed.replace(".","").isdigit() else 0.0

        raw_acc = s.get("Accuracy", "99").replace("±","").replace("%","").strip()
        acc = float(raw_acc) if raw_acc.replace(".","").isdigit() else 99.0

        raw_min_def = s.get("Minimum Defect Size", "99").strip()
        min_def = float(raw_min_def) if raw_min_def.replace(".","").isdigit() else 99.0

        # Test 1: Width >= 800, Speed >= 500, Inline, Accuracy <= 1.0, thickness
        if w >= 800 and speed >= 500 and mode == "inline" and acc <= 1.0 and "thickness" in items:
            test_1_pass.append(fname)

        # Test 2: Width >= 600, Inline, thickness, surface_defect, Accuracy <= 1.0
        if w >= 600 and mode == "inline" and "thickness" in items and "surface_defect" in items and acc <= 1.0:
            test_2_pass.append(fname)

        # Test 3: Width >= 800, Inline, Vision, scratch, contamination, Minimum Defect <= 3
        if w >= 800 and mode == "inline" and "vision" in principle and "scratch" in items and "contamination" in items and min_def <= 3:
            test_3_pass.append(fname)

        # Test 4: Width >= 1000, Speed >= 500, Inline, profile_3d
        if w >= 1000 and speed >= 500 and mode == "inline" and "profile_3d" in items:
            test_4_pass.append(fname)

        # Test 5: Width >= 600, Inline, thickness, surface_defect
        if w >= 600 and mode == "inline" and "thickness" in items and "surface_defect" in items:
            test_5_pass.append(fname)

    print("==================================================")
    print("GROUND TRUTH DATASET VALIDATION REPORT")
    print("==================================================")
    print(f"Total Spec Files Validated: {len(spec_files)}")
    print(f"Total Unique Equipment Names: {len(eq_names)}")
    print(f"Total Unique Manufacturer/Model pairs: {len(mfg_models)}")
    
    print("\n--- Test Eligibility Verification ---")
    print(f"Test 1 Eligible PASS Equipments ({len(test_1_pass)}): {test_1_pass[:3]}")
    print(f"Test 2 Eligible PASS Equipments ({len(test_2_pass)}): {test_2_pass[:3]}")
    print(f"Test 3 Eligible PASS Equipments ({len(test_3_pass)}): {test_3_pass[:3]}")
    print(f"Test 4 Eligible PASS Equipments ({len(test_4_pass)}): {test_4_pass[:3]}")
    print(f"Test 5 Eligible PASS Equipments ({len(test_5_pass)}): {test_5_pass[:3]}")

    if not test_1_pass or not test_2_pass or not test_3_pass or not test_4_pass or not test_5_pass:
        errors.append("One or more Test 1 ~ 5 cases have zero eligible PASS equipments!")

    if errors:
        print("\n❌ VALIDATION ERRORS FOUND:")
        for err in errors:
            print(f"  - {err}")
        return False
    else:
        print("\n[PASS] GROUND TRUTH DATASET PASSED ALL VALIDATION CHECKS (0 ERRORS)!")
        return True

if __name__ == "__main__":
    import sys
    success = validate_ground_truth_dataset()
    sys.exit(0 if success else 1)
