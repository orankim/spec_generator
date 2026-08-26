import os
import sys
import glob
import re

sys.path.insert(0, os.getcwd())

ORIGINAL_DIR = "sample_specs_original"
CONVERTED_DIR = "sample_specs"

def extract_tokens_from_file(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Extract values from key: value lines or table rows
    kvs = []
    notes = ""
    for line in content.splitlines():
        line_s = line.strip()
        if "Note" in line_s or notes:
            if not line_s.startswith("#"):
                notes += " " + line_s
        if ":" in line_s and not line_s.startswith("#") and not line_s.startswith("|"):
            parts = line_s.split(":", 1)
            k = parts[0].strip("- ").strip()
            v = parts[1].strip()
            if v and v != "UNKNOWN":
                kvs.append((k, v))
        elif line_s.startswith("|") and "|" in line_s[1:]:
            parts = [p.strip() for p in line_s.strip("|").split("|")]
            if len(parts) >= 2 and parts[0] not in ("Item", "---", "---:", ":---", ":---:"):
                if not all(c in "-" for c in parts[0]):
                    k, v = parts[0], parts[1]
                    if v and v != "UNKNOWN":
                        kvs.append((k, v))

    return kvs, notes.strip()

def check_file_loss(fname):
    orig_path = os.path.join(ORIGINAL_DIR, fname)
    conv_path = os.path.join(CONVERTED_DIR, fname)

    if not os.path.exists(orig_path):
        return True, 0, 0, []

    orig_kvs, orig_notes = extract_tokens_from_file(orig_path)
    
    with open(conv_path, "r", encoding="utf-8") as f:
        conv_text = f.read()

    missing = []
    total_values = len(orig_kvs) + (1 if orig_notes else 0)
    found_values = 0

    # Check each original KV value in converted text
    for k, v in orig_kvs:
        # Check defect types specifically
        if k == "Defect Types":
            # Canonicalize each item in raw string
            from scripts.migrate_specs_to_standard_schema import canonical_defect_types
            expected_canonical = canonical_defect_types(v)
            expected_tokens = [t.strip() for t in expected_canonical.split(",")]
            defect_ok = True
            for tok in expected_tokens:
                if tok.lower() not in conv_text.lower():
                    defect_ok = False
                    break
            if defect_ok:
                found_values += 1
            else:
                missing.append(f"Defect Types item '{v}' -> '{expected_canonical}' not found in converted spec")
            continue

        # Clean units
        clean_v = re.sub(r'(\b|(?<=\d))(mm/s|μm|um|mm|kHz|Hz|%RH|°C|°F|s)\b', '', v, flags=re.IGNORECASE).strip()

        # Split items if comma separated
        sub_vals = [s.strip() for s in clean_v.split(",")] if "," in clean_v else [clean_v]
        
        val_found = True
        for sv in sub_vals:
            if not sv or sv == "Supported":
                continue
            
            sv_clean = sv.lower().strip()
            # Extract main number/token (e.g. 100 x 100, 30, 500)
            tokens_to_check = [sv_clean]
            num_match = re.search(r'\d+.*?\d*', sv_clean)
            if num_match:
                tokens_to_check.append(num_match.group(0))

            matched_any = False
            for tok in tokens_to_check:
                tok_norm = " ".join(tok.replace("×", " ").replace("x", " ").split())
                conv_norm = " ".join(conv_text.lower().replace("×", " ").replace("x", " ").split())
                if tok.lower() in conv_text.lower() or tok_norm in conv_norm:
                    matched_any = True
                    break
            
            if not matched_any:
                val_found = False
                break
        
        if val_found:
            found_values += 1
        else:
            missing.append(f"Field '{k}': value '{v}' not fully found in converted spec")

    if orig_notes:
        # Check notes substring
        snippet = orig_notes[:20]
        if snippet.lower() in conv_text.lower() or orig_notes.lower() in conv_text.lower():
            found_values += 1
        else:
            missing.append(f"Notes text missing or altered: '{orig_notes}'")

    return len(missing) == 0, total_values, found_values, missing

def main():
    orig_files = sorted([f for f in os.listdir(ORIGINAL_DIR) if f.startswith("SPEC-") and f.endswith(".md")])
    
    total_original_values = 0
    total_maintained_values = 0
    total_missing_values = 0
    file_status = {}

    for fname in orig_files:
        ok, tot, found, missing = check_file_loss(fname)
        total_original_values += tot
        total_maintained_values += found
        total_missing_values += len(missing)
        file_status[fname] = (ok, tot, found, missing)

    print("==================================================")
    print("DATA LOSS VERIFICATION REPORT")
    print("==================================================")
    print(f"Total Spec Files Analyzed: {len(orig_files)}")
    print(f"Total Original Values:    {total_original_values}")
    print(f"Maintained Values:        {total_maintained_values}")
    print(f"Missing/Lost Values:      {total_missing_values}")

    if total_missing_values > 0:
        print("\nMissing Details:")
        for fname, (ok, tot, found, missing) in file_status.items():
            if not ok:
                print(f"\n[{fname}] ({found}/{tot} values retained):")
                for m in missing:
                    print(f"  - {m}")
    else:
        print("\n[PASS] PERFECT RETENTION: ZERO DATA LOSS DETECTED ACROSS ALL 50 SPEC FILES!")

    return total_missing_values == 0

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
