import os
import glob
import re
import shutil

SOURCE_DIR = "sample_specs"
BACKUP_DIR = "sample_specs_original"

def backup_specs():
    if not os.path.exists(BACKUP_DIR):
        shutil.copytree(SOURCE_DIR, BACKUP_DIR)
        print(f"Backed up {SOURCE_DIR} to {BACKUP_DIR}")
    else:
        print(f"Backup directory {BACKUP_DIR} already exists.")

def parse_original_spec(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()

    sections = {}
    current_sec = "Header"
    sections[current_sec] = []

    for line in content.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("#"):
            current_sec = line_str.lstrip("#").strip()
            sections[current_sec] = []
        else:
            sections[current_sec].append(line_str)

    kv_pairs = {}
    notes = []

    for sec_name, lines in sections.items():
        if "Note" in sec_name:
            notes.extend(lines)
            continue
        for l in lines:
            if l.startswith("-") and ":" in l:
                k, v = l[1:].split(":", 1)
                kv_pairs[k.strip()] = v.strip()
            elif l.startswith("|") and "|" in l[1:]:
                parts = [p.strip() for p in l.strip("|").split("|")]
                if len(parts) >= 2 and parts[0] not in ("Item", "---", "---:", ":---", ":---:"):
                    if not all(c in "-" for c in parts[0]):
                        kv_pairs[parts[0]] = parts[1]
            elif ":" in l and not l.startswith("|") and not l.startswith("#"):
                k, v = l.split(":", 1)
                kv_pairs[k.strip()] = v.strip()

    notes_text = "\n".join(notes).strip()
    return kv_pairs, notes_text

def canonical_defect_types(raw_str):
    if not raw_str or raw_str == "UNKNOWN":
        return "UNKNOWN"
    
    mapping = {
        "scratch": "scratch",
        "pin hole": "pinhole",
        "pinhole": "pinhole",
        "coating defect": "coating_defect",
        "coating non-uniformity": "coating_non_uniformity",
        "surface defect": "surface_defect",
        "edge defect": "edge_defect",
        "edge crack": "edge_crack",
        "edge profile": "edge_defect",
        "particle": "particle",
        "contamination": "contamination",
        "void": "void",
        "crack": "edge_crack",
        "internal defect": "surface_defect"
    }

    items = [i.strip() for i in raw_str.split(",")]
    canonical_items = []
    for item in items:
        item_lower = item.lower()
        matched = False
        for k, v in mapping.items():
            if k in item_lower:
                if v not in canonical_items:
                    canonical_items.append(v)
                matched = True
                break
        if not matched:
            clean_v = item_lower.replace(" ", "_")
            if clean_v not in canonical_items:
                canonical_items.append(clean_v)
                
    return ", ".join(canonical_items) if canonical_items else raw_str

def canonical_inspection_items(notes_text, kv_pairs):
    items = []
    text_to_search = (notes_text + " " + " ".join(kv_pairs.values())).lower()
    
    if "thickness" in text_to_search:
        items.append("thickness")
    if "3d profile" in text_to_search or "profilometry" in text_to_search or "3d inspection" in text_to_search:
        items.append("profile_3d")
    if "surface defect" in text_to_search or "surface inspection" in text_to_search:
        items.append("surface_defect")
    if "scratch" in text_to_search:
        items.append("scratch")
    if "particle" in text_to_search:
        items.append("particle")
    if "pinhole" in text_to_search or "pin hole" in text_to_search:
        items.append("pinhole")
    if "void" in text_to_search:
        items.append("void")
    if "edge defect" in text_to_search:
        items.append("edge_defect")
    if "coating defect" in text_to_search:
        items.append("coating_defect")

    res = []
    for i in items:
        if i not in res:
            res.append(i)
            
    return ", ".join(res) if res else "UNKNOWN"

def strip_units(val_str, unit_to_strip):
    if not val_str or val_str == "UNKNOWN":
        return "UNKNOWN"
    val = val_str.strip()
    if unit_to_strip and val.endswith(unit_to_strip):
        val = val[:-len(unit_to_strip)].strip()
    return val

def transform_spec(spec_filename):
    fpath = os.path.join(SOURCE_DIR, spec_filename)
    kv, notes = parse_original_spec(fpath)

    manufacturer = kv.get("Manufacturer", "UNKNOWN")
    model = kv.get("Model", "UNKNOWN")
    eq_name = f"{manufacturer} {model}".strip() if manufacturer != "UNKNOWN" and model != "UNKNOWN" else kv.get("Equipment Name", "UNKNOWN")

    eq_type = kv.get("Equipment Type", "UNKNOWN")
    meas_principle = kv.get("Measurement Principle", "UNKNOWN")
    
    inspection_mode = kv.get("Inspection Mode", "UNKNOWN")
    if inspection_mode != "UNKNOWN":
        inspection_mode = inspection_mode.lower()
        
    meas_type = kv.get("Measurement Type", "UNKNOWN")
    if meas_type != "UNKNOWN":
        meas_type = meas_type.lower()

    # Target
    target = kv.get("Target", "UNKNOWN")
    
    # Width
    raw_width = kv.get("Maximum Electrode Width", kv.get("Maximum Width", "UNKNOWN"))
    width_val = strip_units(raw_width, "mm")

    # Length
    raw_length = kv.get("Maximum Measurement Length", "UNKNOWN")
    length_val = strip_units(raw_length, "mm")

    # Ranges
    raw_z_range = kv.get("Measurement Range (Z)", kv.get("Z Measurement Range", kv.get("Vertical Measurement Range", kv.get("Vertical Range", kv.get("Thickness Range", "UNKNOWN")))))
    z_range_val = strip_units(raw_z_range, "μm")

    # Accuracy
    raw_acc = kv.get("Accuracy", kv.get("Measurement Accuracy", "UNKNOWN"))
    acc_val = strip_units(raw_acc, "μm")

    # Repeatability
    raw_rep = kv.get("Repeatability", "UNKNOWN")
    rep_val = strip_units(raw_rep, "μm")

    # Resolution Z
    raw_z_res = kv.get("Z Resolution", kv.get("Vertical Resolution", kv.get("Thickness Resolution", "UNKNOWN")))
    z_res_val = strip_units(raw_z_res, "μm")

    # Resolution X/Y
    raw_x_res = kv.get("X Resolution", "UNKNOWN")
    x_res_val = strip_units(raw_x_res, "μm")

    raw_y_res = kv.get("Y Resolution", "UNKNOWN")
    y_res_val = strip_units(raw_y_res, "μm")

    raw_xy_res = kv.get("XY Resolution", "UNKNOWN")
    if raw_xy_res != "UNKNOWN":
        xy_clean = strip_units(raw_xy_res, "μm")
        if x_res_val == "UNKNOWN":
            x_res_val = xy_clean
        if y_res_val == "UNKNOWN":
            y_res_val = xy_clean

    # FOV
    raw_fov = kv.get("Field of View", "UNKNOWN")
    fov_val = strip_units(raw_fov, "mm")

    # Speed
    raw_speed = kv.get("Measurement Speed", "UNKNOWN")
    speed_val = strip_units(raw_speed, "mm/s")

    raw_line_speed = kv.get("Line Speed", kv.get("Maximum Line Speed", "UNKNOWN"))
    line_speed_val = strip_units(raw_line_speed, "mm/s")

    # Sampling Rate
    raw_sample_rate = kv.get("Sampling Rate", kv.get("Measurement Rate", kv.get("Image Acquisition Rate", "UNKNOWN")))

    # Measurement Time / Tact Time
    raw_meas_time = kv.get("Measurement Time", "UNKNOWN")
    tact_time_val = strip_units(raw_meas_time, "s")

    # Defect Inspection
    raw_min_defect = kv.get("Minimum Detectable Defect", "UNKNOWN")
    min_defect_val = strip_units(raw_min_defect, "μm")

    raw_defect_types = kv.get("Defect Types", "UNKNOWN")
    defect_types_val = canonical_defect_types(raw_defect_types)

    defect_class = kv.get("Classification", kv.get("Defect Classification", "UNKNOWN"))

    # Optical
    light_source = kv.get("Light Source", kv.get("3D Sensor", "UNKNOWN"))
    camera = kv.get("Camera", kv.get("2D Camera", "UNKNOWN"))
    wavelength = kv.get("Wavelength", "UNKNOWN")
    spectral_range = kv.get("Spectral Range", "UNKNOWN")
    optical_method = kv.get("Measurement Method", "UNKNOWN")
    objective = kv.get("Objective", "UNKNOWN")
    laser_val = "Supported" if (light_source != "UNKNOWN" and "laser" in light_source.lower()) else "UNKNOWN"

    # System & Interfaces
    data_output = kv.get("Data Output", "UNKNOWN")
    plc_val = kv.get("PLC Interface", kv.get("PLC", "UNKNOWN"))
    mes_val = kv.get("MES Interface", kv.get("MES", "UNKNOWN"))
    ethernet_ip_val = kv.get("EtherNet/IP", "UNKNOWN")
    digital_io_val = kv.get("Digital I/O", "UNKNOWN")
    opc_ua_val = kv.get("OPC-UA", "UNKNOWN")
    ethernet_val = "Supported" if (data_output != "UNKNOWN" and "ethernet" in data_output.lower()) else "UNKNOWN"

    # Environment
    op_temp = kv.get("Operating Temperature", "UNKNOWN")
    humidity = kv.get("Humidity", "UNKNOWN")

    # Safety
    laser_class = kv.get("Laser Safety", kv.get("Laser Class", "UNKNOWN"))
    e_stop = kv.get("Emergency Stop", "UNKNOWN")
    interlock = kv.get("Interlock", "UNKNOWN")

    # Inspection Items
    insp_items = canonical_inspection_items(notes, kv)

    # Helper for detail table row
    def detail_row(item, unit, spec, source_file):
        status = "VERIFIED" if spec != "UNKNOWN" else "UNKNOWN"
        source = source_file if status == "VERIFIED" else "-"
        return f"| {item} | {unit} | {spec} | {status} | {source} |"

    doc = []
    doc.append(f"# {eq_name}\n")

    doc.append("## 1. General Specification\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append(f"| Equipment Name | {eq_name} |")
    doc.append(f"| Equipment Type | {eq_type} |")
    doc.append(f"| Manufacturer | {manufacturer} |")
    doc.append(f"| Model | {model} |")
    doc.append("| Version | UNKNOWN |")
    doc.append("| Application | UNKNOWN |")
    doc.append("| Inspection Method | UNKNOWN |")
    doc.append(f"| Measurement Principle | {meas_principle} |")
    doc.append(f"| Inline / Offline | {inspection_mode} |")
    doc.append(f"| Measurement Type | {meas_type} |\n")

    doc.append("## 2. Inspection Target\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("Material", "-", "UNKNOWN", spec_filename))
    doc.append(detail_row("Product Type", "-", "UNKNOWN", spec_filename))
    doc.append(detail_row("Electrode Type", "-", target, spec_filename))
    doc.append(detail_row("Width", "mm", width_val, spec_filename))
    doc.append(detail_row("Length", "mm", length_val, spec_filename))
    doc.append(detail_row("Thickness", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Coating Thickness", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Substrate", "-", "UNKNOWN", spec_filename))
    doc.append(detail_row("Inspection Direction", "-", "UNKNOWN", spec_filename))
    doc.append(detail_row("Target Line Speed", "mm/s", "UNKNOWN", spec_filename) + "\n")

    doc.append("## 3. Inspection Requirements\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("Inspection Items", "-", insp_items, spec_filename))
    doc.append(detail_row("Inspection Area", "-", "UNKNOWN", spec_filename))
    doc.append(detail_row("Inspection Width", "mm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Inspection Length", "mm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Sampling Interval", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Inspection Frequency", "Hz", "UNKNOWN", spec_filename))
    doc.append(detail_row("Inspection Mode", "-", inspection_mode, spec_filename) + "\n")

    doc.append("## 4. Measurement Performance\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("Measurement Range", "μm", z_range_val, spec_filename))
    doc.append(detail_row("Resolution", "μm", z_res_val, spec_filename))
    doc.append(detail_row("Accuracy", "μm", acc_val, spec_filename))
    doc.append(detail_row("Repeatability", "μm", rep_val, spec_filename))
    doc.append(detail_row("Reproducibility", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Linearity", "%", "UNKNOWN", spec_filename))
    doc.append(detail_row("Measurement Speed", "mm/s", speed_val, spec_filename))
    doc.append(detail_row("Sampling Rate", "Hz", raw_sample_rate, spec_filename) + "\n")

    doc.append("## 5. Spatial Performance\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("X Range", "mm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Y Range", "mm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Z Range", "μm", z_range_val, spec_filename))
    doc.append(detail_row("X Resolution", "μm", x_res_val, spec_filename))
    doc.append(detail_row("Y Resolution", "μm", y_res_val, spec_filename))
    doc.append(detail_row("Z Resolution", "μm", z_res_val, spec_filename))
    doc.append(detail_row("FOV", "mm", fov_val, spec_filename))
    doc.append(detail_row("Working Distance", "mm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Pixel Size", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Point Spacing", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Profile Spacing", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Spatial Sampling Interval", "μm", "UNKNOWN", spec_filename) + "\n")

    doc.append("## 6. Optical System\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append(f"| Light Source | {light_source} |")
    doc.append(f"| Wavelength | {wavelength} |")
    doc.append(f"| Spectral Range | {spectral_range} |")
    doc.append(f"| Optical Method | {optical_method} |")
    doc.append("| Interferometry | UNKNOWN |")
    doc.append("| Reflectometry | UNKNOWN |")
    doc.append("| OCT | UNKNOWN |")
    doc.append(f"| Laser | {laser_val} |")
    doc.append("| Sensor Type | UNKNOWN |")
    doc.append(f"| Camera | {camera} |")
    doc.append("| Camera Resolution | UNKNOWN |")
    doc.append("| Lens | UNKNOWN |")
    doc.append(f"| Objective | {objective} |")
    doc.append("| Optical Working Distance | UNKNOWN |\n")

    doc.append("## 7. Defect Inspection\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("Defect Detection", "-", "Supported" if raw_min_defect != "UNKNOWN" or raw_defect_types != "UNKNOWN" else "UNKNOWN", spec_filename))
    doc.append(detail_row("Minimum Defect Size", "μm", min_defect_val, spec_filename))
    doc.append(detail_row("Defect Types", "-", defect_types_val, spec_filename))
    doc.append(detail_row("Detection Resolution", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("Defect Detection Accuracy", "μm", "UNKNOWN", spec_filename))
    doc.append(detail_row("False Positive Rate", "%", "UNKNOWN", spec_filename))
    doc.append(detail_row("False Negative Rate", "%", "UNKNOWN", spec_filename))
    doc.append(detail_row("Classification", "-", defect_class, spec_filename) + "\n")

    doc.append("## 7-1. Inspection Performance\n")
    doc.append("| Item | Unit | Specification | Status | Source |")
    doc.append("|---|---|---|---|---|")
    doc.append(detail_row("Scan Speed", "mm/s", "UNKNOWN", spec_filename))
    doc.append(detail_row("Line Speed", "mm/s", line_speed_val, spec_filename))
    doc.append(detail_row("Overall Measurement Speed", "mm/s", "UNKNOWN", spec_filename))
    doc.append(detail_row("Tact Time", "s", tact_time_val, spec_filename))
    doc.append(detail_row("Inspection Width", "mm", "UNKNOWN", spec_filename) + "\n")

    doc.append("## 8. System Configuration\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append("| Automation Level | UNKNOWN |")
    doc.append("| Stage | UNKNOWN |")
    doc.append("| Motion System | UNKNOWN |")
    doc.append("| Sensor | UNKNOWN |")
    doc.append("| Controller | UNKNOWN |")
    doc.append("| PC | UNKNOWN |")
    doc.append("| Software | UNKNOWN |")
    doc.append("| Display | UNKNOWN |")
    doc.append("| Power | UNKNOWN |")
    doc.append("| Air | UNKNOWN |")
    doc.append("| Cooling | UNKNOWN |")
    doc.append("| Mechanical Configuration | UNKNOWN |")
    doc.append(f"| Data Output | {data_output} |\n")

    doc.append("## 9. Interfaces / Data\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append(f"| PLC | {plc_val} |")
    doc.append(f"| MES | {mes_val} |")
    doc.append(f"| OPC-UA | {opc_ua_val} |")
    doc.append(f"| EtherNet/IP | {ethernet_ip_val} |")
    doc.append("| PROFINET | UNKNOWN |")
    doc.append("| Modbus | UNKNOWN |")
    doc.append(f"| Ethernet | {ethernet_val} |")
    doc.append(f"| Digital I/O | {digital_io_val} |")
    doc.append("| Analog I/O | UNKNOWN |")
    doc.append("| API | UNKNOWN |")
    doc.append("| Data Format | UNKNOWN |")
    doc.append("| Data Storage | UNKNOWN |")
    doc.append("| Network | UNKNOWN |")
    doc.append("| Other Interfaces | UNKNOWN |\n")

    doc.append("## 10. Environment\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append(f"| Operating Temperature | {op_temp} |")
    doc.append("| Storage Temperature | UNKNOWN |")
    doc.append(f"| Humidity | {humidity} |")
    doc.append("| Installation Space | UNKNOWN |")
    doc.append("| Site Power Requirement | UNKNOWN |")
    doc.append("| Vibration Requirement | UNKNOWN |")
    doc.append("| Dust | UNKNOWN |")
    doc.append("| Installation Environment | UNKNOWN |")
    doc.append("| Clean Room | UNKNOWN |\n")

    doc.append("## 11. Safety\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append("| Safety Standard | UNKNOWN |")
    doc.append(f"| Laser Class | {laser_class} |")
    doc.append(f"| Interlock | {interlock} |")
    doc.append(f"| Emergency Stop | {e_stop} |")
    doc.append("| Safety Sensor | UNKNOWN |")
    doc.append("| Protective Cover | UNKNOWN |\n")

    doc.append("## 12. Sources / Notes\n")
    doc.append("| Item | Specification |")
    doc.append("|---|---|")
    doc.append(f"| Source File | {spec_filename} |")
    doc.append(f"| Notes | {notes if notes else 'UNKNOWN'} |\n")

    output_content = "\n".join(doc)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(output_content)

def main():
    backup_specs()
    spec_files = sorted([f for f in os.listdir(SOURCE_DIR) if f.startswith("SPEC-") and f.endswith(".md")])
    print(f"Migrating {len(spec_files)} spec files...")
    for fname in spec_files:
        transform_spec(fname)
    print("Migration complete!")

if __name__ == "__main__":
    main()
