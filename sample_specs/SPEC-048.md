# BasicInspect BI-600

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | BasicInspect BI-600 |
| Equipment Type | Basic Inspection |
| Manufacturer | BasicInspect |
| Model | BI-600 |
| Version | v1.0 |
| Application | Lithium-ion Battery Electrode Production Line |
| Inspection Method | Non-contact Optical Inspection |
| Measurement Principle | Optical |
| Inline / Offline | inline |
| Measurement Type | non-contact |

## 2. Inspection Target

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Material | - | Lithium-ion Battery Electrode Roll | VERIFIED | SPEC-048.md |
| Product Type | - | Cathode / Anode Coated Sheet | VERIFIED | SPEC-048.md |
| Electrode Type | - | Battery Electrode | VERIFIED | SPEC-048.md |
| Width | mm | 600 | VERIFIED | SPEC-048.md |
| Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-048.md |
| Thickness | μm | 50 ~ 300 | VERIFIED | SPEC-048.md |
| Coating Thickness | μm | 20 ~ 150 | VERIFIED | SPEC-048.md |
| Substrate | - | Copper Foil (10 μm) / Aluminum Foil (15 μm) | VERIFIED | SPEC-048.md |
| Inspection Direction | - | Top & Bottom Dual Side | VERIFIED | SPEC-048.md |
| Target Line Speed | mm/s | 200 | VERIFIED | SPEC-048.md |

## 3. Inspection Requirements

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Inspection Items | - | thickness | VERIFIED | SPEC-048.md |
| Inspection Area | - | Full Electrode Width & Length | VERIFIED | SPEC-048.md |
| Inspection Width | mm | 600 | VERIFIED | SPEC-048.md |
| Inspection Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-048.md |
| Sampling Interval | μm | 20 | VERIFIED | SPEC-048.md |
| Inspection Frequency | Hz | 1000 | VERIFIED | SPEC-048.md |
| Inspection Mode | - | inline | VERIFIED | SPEC-048.md |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | μm | 0 ~ 200 | VERIFIED | SPEC-048.md |
| Resolution | μm | 0.5 | VERIFIED | SPEC-048.md |
| Accuracy | μm | ±1.5 | VERIFIED | SPEC-048.md |
| Repeatability | μm | ±0.8 | VERIFIED | SPEC-048.md |
| Reproducibility | μm | ±1.2 | VERIFIED | SPEC-048.md |
| Linearity | % | ±0.1 | VERIFIED | SPEC-048.md |
| Measurement Speed | mm/s | 200 | VERIFIED | SPEC-048.md |
| Sampling Rate | Hz | 5 kHz | VERIFIED | SPEC-048.md |

## 5. Spatial Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| X Range | mm | 600 | VERIFIED | SPEC-048.md |
| Y Range | mm | Continuous | VERIFIED | SPEC-048.md |
| Z Range | μm | 0 ~ 200 | VERIFIED | SPEC-048.md |
| X Resolution | μm | 20 | VERIFIED | SPEC-048.md |
| Y Resolution | μm | 20 | VERIFIED | SPEC-048.md |
| Z Resolution | μm | 0.5 | VERIFIED | SPEC-048.md |
| FOV | mm | 600 mm | VERIFIED | SPEC-048.md |
| Working Distance | mm | 100 | VERIFIED | SPEC-048.md |
| Pixel Size | μm | 5.0 | VERIFIED | SPEC-048.md |
| Point Spacing | μm | 20 | VERIFIED | SPEC-048.md |
| Profile Spacing | μm | 50 | VERIFIED | SPEC-048.md |
| Spatial Sampling Interval | μm | 20 | VERIFIED | SPEC-048.md |

## 6. Optical System

| Item | Specification |
|---|---|
| Light Source | LED |
| Wavelength | Broadband |
| Spectral Range | 400 ~ 700 nm |
| Optical Method | High Resolution Telecentric Optics |
| Interferometry | Not Applicable |
| Reflectometry | Not Applicable |
| OCT | Not Applicable |
| Laser | Not Applicable |
| Sensor Type | Area Scan CMOS Sensor |
| Camera | CMOS |
| Camera Resolution | 4096 × 3072 |
| Lens | Telecentric Lens Assembly |
| Objective | 10X Telecentric Lens |
| Optical Working Distance | 100 mm |

## 7. Defect Inspection

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Defect Detection | - | Supported | VERIFIED | SPEC-048.md |
| Minimum Defect Size | μm | 20 | VERIFIED | SPEC-048.md |
| Defect Types | - | surface_defect | VERIFIED | SPEC-048.md |
| Detection Resolution | μm | 0.5 | VERIFIED | SPEC-048.md |
| Defect Detection Accuracy | % | 99.5 | VERIFIED | SPEC-048.md |
| False Positive Rate | % | 0.1 | VERIFIED | SPEC-048.md |
| False Negative Rate | % | 0.01 | VERIFIED | SPEC-048.md |
| Classification | - | Supported | VERIFIED | SPEC-048.md |

## 7-1. Inspection Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Scan Speed | mm/s | 200 | VERIFIED | SPEC-048.md |
| Line Speed | mm/s | 200 | VERIFIED | SPEC-048.md |
| Overall Measurement Speed | mm/s | 200 | VERIFIED | SPEC-048.md |
| Tact Time | s | 5.0 | VERIFIED | SPEC-048.md |
| Inspection Width | mm | 600 | VERIFIED | SPEC-048.md |

## 8. System Configuration

| Item | Specification |
|---|---|
| Automation Level | Fully Automated Inline System |
| Stage | Precision Motorized Stage Assembly |
| Motion System | High Precision Linear Servo Motor |
| Sensor | Multi-head Sensor Package |
| Controller | Real-Time Embedded Controller |
| PC | Industrial PC (Intel i9, 64GB RAM, RTX GPU) |
| Software | BasicInspect Inspection Suite v3.2 |
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
| PROFINET | Supported |
| Modbus | Not Applicable |
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
| Laser Class | Not Applicable |
| Interlock | Not Applicable |
| Emergency Stop | Supported |
| Safety Sensor | Optical Light Curtain (Supported) |
| Protective Cover | Full Enclosure Metal Safety Cover |

## 12. Sources / Notes

| Item | Specification |
|---|---|
| Source File | SPEC-048.md |
| Notes | Entry-level inline thickness inspection system. |
