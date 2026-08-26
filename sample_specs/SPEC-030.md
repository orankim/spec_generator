# EdgeScan Pro ES-800

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | EdgeScan Pro ES-800 |
| Equipment Type | Edge Inspection |
| Manufacturer | EdgeScan Pro |
| Model | ES-800 |
| Version | v1.0 |
| Application | Lithium-ion Battery Electrode Production Line |
| Inspection Method | Non-contact Optical Inspection |
| Measurement Principle | Laser + Vision |
| Inline / Offline | inline |
| Measurement Type | non-contact |

## 2. Inspection Target

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Material | - | Lithium-ion Battery Electrode Roll | VERIFIED | SPEC-030.md |
| Product Type | - | Cathode / Anode Coated Sheet | VERIFIED | SPEC-030.md |
| Electrode Type | - | Battery Electrode Edge | VERIFIED | SPEC-030.md |
| Width | mm | 800 | VERIFIED | SPEC-030.md |
| Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-030.md |
| Thickness | μm | 50 ~ 300 | VERIFIED | SPEC-030.md |
| Coating Thickness | μm | 20 ~ 150 | VERIFIED | SPEC-030.md |
| Substrate | - | Copper Foil (10 μm) / Aluminum Foil (15 μm) | VERIFIED | SPEC-030.md |
| Inspection Direction | - | Top & Bottom Dual Side | VERIFIED | SPEC-030.md |
| Target Line Speed | mm/s | 600 | VERIFIED | SPEC-030.md |

## 3. Inspection Requirements

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Inspection Items | - | edge_defect, edge_crack | VERIFIED | SPEC-030.md |
| Inspection Area | - | Full Electrode Width & Length | VERIFIED | SPEC-030.md |
| Inspection Width | mm | 800 | VERIFIED | SPEC-030.md |
| Inspection Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-030.md |
| Sampling Interval | μm | 20 | VERIFIED | SPEC-030.md |
| Inspection Frequency | Hz | 1000 | VERIFIED | SPEC-030.md |
| Inspection Mode | - | inline | VERIFIED | SPEC-030.md |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | μm | 0 ~ 500 | VERIFIED | SPEC-030.md |
| Resolution | μm | 0.2 | VERIFIED | SPEC-030.md |
| Accuracy | μm | ±1.0 | VERIFIED | SPEC-030.md |
| Repeatability | μm | ±0.5 | VERIFIED | SPEC-030.md |
| Reproducibility | μm | ±0.8 | VERIFIED | SPEC-030.md |
| Linearity | % | ±0.1 | VERIFIED | SPEC-030.md |
| Measurement Speed | mm/s | 600 | VERIFIED | SPEC-030.md |
| Sampling Rate | Hz | 5 kHz | VERIFIED | SPEC-030.md |

## 5. Spatial Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| X Range | mm | 800 | VERIFIED | SPEC-030.md |
| Y Range | mm | Continuous | VERIFIED | SPEC-030.md |
| Z Range | μm | 0 ~ 500 | VERIFIED | SPEC-030.md |
| X Resolution | μm | 20 | VERIFIED | SPEC-030.md |
| Y Resolution | μm | 20 | VERIFIED | SPEC-030.md |
| Z Resolution | μm | 0.2 | VERIFIED | SPEC-030.md |
| FOV | mm | 800 mm | VERIFIED | SPEC-030.md |
| Working Distance | mm | 100 | VERIFIED | SPEC-030.md |
| Pixel Size | μm | 5.0 | VERIFIED | SPEC-030.md |
| Point Spacing | μm | 20 | VERIFIED | SPEC-030.md |
| Profile Spacing | μm | 50 | VERIFIED | SPEC-030.md |
| Spatial Sampling Interval | μm | 20 | VERIFIED | SPEC-030.md |

## 6. Optical System

| Item | Specification |
|---|---|
| Light Source | Laser |
| Wavelength | 405 nm |
| Spectral Range | 400 ~ 700 nm |
| Optical Method | Laser Line Triangulation |
| Interferometry | Not Applicable |
| Reflectometry | Not Applicable |
| OCT | Not Applicable |
| Laser | Supported |
| Sensor Type | Laser Profile Sensor |
| Camera | CMOS |
| Camera Resolution | 4096 × 3072 |
| Lens | Telecentric Lens Assembly |
| Objective | 10X Telecentric Lens |
| Optical Working Distance | 100 mm |

## 7. Defect Inspection

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Defect Detection | - | Supported | VERIFIED | SPEC-030.md |
| Minimum Defect Size | μm | 2 | VERIFIED | SPEC-030.md |
| Defect Types | - | edge_defect, edge_crack | VERIFIED | SPEC-030.md |
| Detection Resolution | μm | 0.2 | VERIFIED | SPEC-030.md |
| Defect Detection Accuracy | % | 99.5 | VERIFIED | SPEC-030.md |
| False Positive Rate | % | 0.1 | VERIFIED | SPEC-030.md |
| False Negative Rate | % | 0.01 | VERIFIED | SPEC-030.md |
| Classification | - | Supported | VERIFIED | SPEC-030.md |

## 7-1. Inspection Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Scan Speed | mm/s | 600 | VERIFIED | SPEC-030.md |
| Line Speed | mm/s | 600 | VERIFIED | SPEC-030.md |
| Overall Measurement Speed | mm/s | 600 | VERIFIED | SPEC-030.md |
| Tact Time | s | 1.7 | VERIFIED | SPEC-030.md |
| Inspection Width | mm | 800 | VERIFIED | SPEC-030.md |

## 8. System Configuration

| Item | Specification |
|---|---|
| Automation Level | Fully Automated Inline System |
| Stage | Precision Motorized Stage Assembly |
| Motion System | High Precision Linear Servo Motor |
| Sensor | Multi-head Sensor Package |
| Controller | Real-Time Embedded Controller |
| PC | Industrial PC (Intel i9, 64GB RAM, RTX GPU) |
| Software | EdgeScan Pro Inspection Suite v3.2 |
| Display | 27-inch Touchscreen Monitor |
| Power | AC 220V 50/60Hz 3kW |
| Air | 0.6 MPa Clean Dry Air |
| Cooling | Air Conditioned Cabinet Cooling |
| Mechanical Configuration | Heavy-duty Gantry Structure |
| Data Output | Ethernet |

## 9. Interfaces / Data

| Item | Specification |
|---|---|
| PLC | Supported |
| MES | Supported |
| OPC-UA | Supported |
| EtherNet/IP | Supported |
| PROFINET | Not Applicable |
| Modbus | Supported |
| Ethernet | Supported |
| Digital I/O | Supported |
| Analog I/O | Supported |
| API | REST API / C++ SDK (Supported) |
| Data Format | CSV, JSON, Binary Profile Data |
| Data Storage | 2TB Local NVMe SSD + Network NAS |
| Network | 10GbE High Speed Industrial Ethernet |
| Other Interfaces | RS-232C, USB 3.0 |

## 10. Environment

| Item | Specification |
|---|---|
| Operating Temperature | 5 ~ 40 °C |
| Storage Temperature | -10 ~ 50 °C |
| Humidity | 20 ~ 85 %RH |
| Installation Space | 2000(W) × 1500(D) × 1800(H) mm |
| Site Power Requirement | AC 220V ±10%, Single Phase |
| Vibration Requirement | VC-A Anti-Vibration Isolation |
| Dust | Dust-proof IP54 Enclosure |
| Installation Environment | Cleanroom Facility |
| Clean Room | Class 10,000 (ISO Class 7) |

## 11. Safety

| Item | Specification |
|---|---|
| Safety Standard | CE Mark, KC Certification |
| Laser Class | Class 2 |
| Interlock | Supported |
| Emergency Stop | Supported |
| Safety Sensor | Optical Light Curtain (Supported) |
| Protective Cover | Full Enclosure Metal Safety Cover |

## 12. Sources / Notes

| Item | Specification |
|---|---|
| Source File | SPEC-030.md |
| Notes | Specialized system for inline battery electrode edge defect inspection. |
