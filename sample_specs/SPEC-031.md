# OCTInspect OI-300

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | OCTInspect OI-300 |
| Equipment Type | OCT Inspection |
| Manufacturer | OCTInspect |
| Model | OI-300 |
| Version | v2.0 |
| Application | Lithium-ion Battery Electrode Production Line |
| Inspection Method | Non-contact Optical Inspection |
| Measurement Principle | OCT |
| Inline / Offline | inline |
| Measurement Type | non-contact |

## 2. Inspection Target

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Material | - | Lithium-ion Battery Electrode Roll | VERIFIED | SPEC-031.md |
| Product Type | - | Cathode / Anode Coated Sheet | VERIFIED | SPEC-031.md |
| Electrode Type | - | Battery Electrode Coating / Internal Structure | VERIFIED | SPEC-031.md |
| Width | mm | 300 | VERIFIED | SPEC-031.md |
| Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-031.md |
| Thickness | μm | 50 ~ 300 | VERIFIED | SPEC-031.md |
| Coating Thickness | μm | 20 ~ 150 | VERIFIED | SPEC-031.md |
| Substrate | - | Copper Foil (10 μm) / Aluminum Foil (15 μm) | VERIFIED | SPEC-031.md |
| Inspection Direction | - | Top & Bottom Dual Side | VERIFIED | SPEC-031.md |
| Target Line Speed | mm/s | 300 | VERIFIED | SPEC-031.md |

## 3. Inspection Requirements

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Inspection Items | - | thickness, void | VERIFIED | SPEC-031.md |
| Inspection Area | - | Full Electrode Width & Length | VERIFIED | SPEC-031.md |
| Inspection Width | mm | 300 | VERIFIED | SPEC-031.md |
| Inspection Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-031.md |
| Sampling Interval | μm | 20 | VERIFIED | SPEC-031.md |
| Inspection Frequency | Hz | 1000 | VERIFIED | SPEC-031.md |
| Inspection Mode | - | inline | VERIFIED | SPEC-031.md |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | μm | 5 ~ 300 | VERIFIED | SPEC-031.md |
| Resolution | μm | 0.5 | VERIFIED | SPEC-031.md |
| Accuracy | μm | ±1 | VERIFIED | SPEC-031.md |
| Repeatability | μm | ±0.5 | VERIFIED | SPEC-031.md |
| Reproducibility | μm | ±0.8 | VERIFIED | SPEC-031.md |
| Linearity | % | ±0.1 | VERIFIED | SPEC-031.md |
| Measurement Speed | mm/s | 300 | VERIFIED | SPEC-031.md |
| Sampling Rate | Hz | 5 kHz | VERIFIED | SPEC-031.md |

## 5. Spatial Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| X Range | mm | 300 | VERIFIED | SPEC-031.md |
| Y Range | mm | Continuous | VERIFIED | SPEC-031.md |
| Z Range | μm | 5 ~ 300 | VERIFIED | SPEC-031.md |
| X Resolution | μm | 20 | VERIFIED | SPEC-031.md |
| Y Resolution | μm | 20 | VERIFIED | SPEC-031.md |
| Z Resolution | μm | 0.5 | VERIFIED | SPEC-031.md |
| FOV | mm | 300 mm | VERIFIED | SPEC-031.md |
| Working Distance | mm | 100 | VERIFIED | SPEC-031.md |
| Pixel Size | μm | 5.0 | VERIFIED | SPEC-031.md |
| Point Spacing | μm | 20 | VERIFIED | SPEC-031.md |
| Profile Spacing | μm | 50 | VERIFIED | SPEC-031.md |
| Spatial Sampling Interval | μm | 20 | VERIFIED | SPEC-031.md |

## 6. Optical System

| Item | Specification |
|---|---|
| Light Source | Near Infrared |
| Wavelength | 850 nm |
| Spectral Range | 400 ~ 700 nm |
| Optical Method | Low Coherence Interferometry |
| Interferometry | Supported |
| Reflectometry | Not Applicable |
| OCT | Supported |
| Laser | Not Applicable |
| Sensor Type | OCT Line Sensor |
| Camera | CMOS |
| Camera Resolution | 4096 × 3072 |
| Lens | Telecentric Lens Assembly |
| Objective | 10X Telecentric Lens |
| Optical Working Distance | 100 mm |

## 7. Defect Inspection

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Defect Detection | - | Supported | VERIFIED | SPEC-031.md |
| Minimum Defect Size | μm | 15 | VERIFIED | SPEC-031.md |
| Defect Types | - | void | VERIFIED | SPEC-031.md |
| Detection Resolution | μm | 0.5 | VERIFIED | SPEC-031.md |
| Defect Detection Accuracy | % | 99.5 | VERIFIED | SPEC-031.md |
| False Positive Rate | % | 0.1 | VERIFIED | SPEC-031.md |
| False Negative Rate | % | 0.01 | VERIFIED | SPEC-031.md |
| Classification | - | Supported | VERIFIED | SPEC-031.md |

## 7-1. Inspection Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Scan Speed | mm/s | 300 | VERIFIED | SPEC-031.md |
| Line Speed | mm/s | 300 | VERIFIED | SPEC-031.md |
| Overall Measurement Speed | mm/s | 300 | VERIFIED | SPEC-031.md |
| Tact Time | s | 3.3 | VERIFIED | SPEC-031.md |
| Inspection Width | mm | 300 | VERIFIED | SPEC-031.md |

## 8. System Configuration

| Item | Specification |
|---|---|
| Automation Level | Fully Automated Inline System |
| Stage | Precision Motorized Stage Assembly |
| Motion System | High Precision Linear Servo Motor |
| Sensor | Multi-head Sensor Package |
| Controller | Real-Time Embedded Controller |
| PC | Industrial PC (Intel i9, 64GB RAM, RTX GPU) |
| Software | OCTInspect Inspection Suite v3.2 |
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
| OPC-UA | Not Applicable |
| EtherNet/IP | Not Applicable |
| PROFINET | Not Applicable |
| Modbus | Not Applicable |
| Ethernet | Supported |
| Digital I/O | Supported |
| Analog I/O | Not Applicable |
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
| Laser Class | Not Applicable |
| Interlock | Not Applicable |
| Emergency Stop | Supported |
| Safety Sensor | Optical Light Curtain (Supported) |
| Protective Cover | Full Enclosure Metal Safety Cover |

## 12. Sources / Notes

| Item | Specification |
|---|---|
| Source File | SPEC-031.md |
| Notes | Combines OCT-based thickness and internal structure inspection for inline use. |
