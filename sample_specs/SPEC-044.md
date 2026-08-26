# MultiInspect MI-800

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | MultiInspect MI-800 |
| Equipment Type | Multi Inspection |
| Manufacturer | MultiInspect |
| Model | MI-800 |
| Version | v3.0 |
| Application | Lithium-ion Battery Electrode Production Line |
| Inspection Method | Non-contact Optical Inspection |
| Measurement Principle | Multi-sensor |
| Inline / Offline | inline |
| Measurement Type | non-contact |

## 2. Inspection Target

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Material | - | Lithium-ion Battery Electrode Roll | VERIFIED | SPEC-044.md |
| Product Type | - | Cathode / Anode Coated Sheet | VERIFIED | SPEC-044.md |
| Electrode Type | - | Battery Electrode | VERIFIED | SPEC-044.md |
| Width | mm | 800 | VERIFIED | SPEC-044.md |
| Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-044.md |
| Thickness | μm | 50 ~ 300 | VERIFIED | SPEC-044.md |
| Coating Thickness | μm | 20 ~ 150 | VERIFIED | SPEC-044.md |
| Substrate | - | Copper Foil (10 μm) / Aluminum Foil (15 μm) | VERIFIED | SPEC-044.md |
| Inspection Direction | - | Top & Bottom Dual Side | VERIFIED | SPEC-044.md |
| Target Line Speed | mm/s | 600 | VERIFIED | SPEC-044.md |

## 3. Inspection Requirements

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Inspection Items | - | thickness, surface_defect | VERIFIED | SPEC-044.md |
| Inspection Area | - | Full Electrode Width & Length | VERIFIED | SPEC-044.md |
| Inspection Width | mm | 800 | VERIFIED | SPEC-044.md |
| Inspection Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-044.md |
| Sampling Interval | μm | 20 | VERIFIED | SPEC-044.md |
| Inspection Frequency | Hz | 1000 | VERIFIED | SPEC-044.md |
| Inspection Mode | - | inline | VERIFIED | SPEC-044.md |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | μm | 0 ~ 500 | VERIFIED | SPEC-044.md |
| Resolution | μm | 0.1 | VERIFIED | SPEC-044.md |
| Accuracy | μm | ±0.8 | VERIFIED | SPEC-044.md |
| Repeatability | μm | ±0.4 | VERIFIED | SPEC-044.md |
| Reproducibility | μm | ±0.6 | VERIFIED | SPEC-044.md |
| Linearity | % | ±0.1 | VERIFIED | SPEC-044.md |
| Measurement Speed | mm/s | 600 | VERIFIED | SPEC-044.md |
| Sampling Rate | Hz | 5 kHz | VERIFIED | SPEC-044.md |

## 5. Spatial Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| X Range | mm | 800 | VERIFIED | SPEC-044.md |
| Y Range | mm | Continuous | VERIFIED | SPEC-044.md |
| Z Range | μm | 0 ~ 500 | VERIFIED | SPEC-044.md |
| X Resolution | μm | 20 | VERIFIED | SPEC-044.md |
| Y Resolution | μm | 20 | VERIFIED | SPEC-044.md |
| Z Resolution | μm | 0.1 | VERIFIED | SPEC-044.md |
| FOV | mm | 800 mm | VERIFIED | SPEC-044.md |
| Working Distance | mm | 100 | VERIFIED | SPEC-044.md |
| Pixel Size | μm | 5.0 | VERIFIED | SPEC-044.md |
| Point Spacing | μm | 20 | VERIFIED | SPEC-044.md |
| Profile Spacing | μm | 50 | VERIFIED | SPEC-044.md |
| Spatial Sampling Interval | μm | 20 | VERIFIED | SPEC-044.md |

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
| Defect Detection | - | Supported | VERIFIED | SPEC-044.md |
| Minimum Defect Size | μm | 3 | VERIFIED | SPEC-044.md |
| Defect Types | - | surface_defect | VERIFIED | SPEC-044.md |
| Detection Resolution | μm | 0.1 | VERIFIED | SPEC-044.md |
| Defect Detection Accuracy | % | 99.5 | VERIFIED | SPEC-044.md |
| False Positive Rate | % | 0.1 | VERIFIED | SPEC-044.md |
| False Negative Rate | % | 0.01 | VERIFIED | SPEC-044.md |
| Classification | - | Supported | VERIFIED | SPEC-044.md |

## 7-1. Inspection Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Scan Speed | mm/s | 600 | VERIFIED | SPEC-044.md |
| Line Speed | mm/s | 600 | VERIFIED | SPEC-044.md |
| Overall Measurement Speed | mm/s | 600 | VERIFIED | SPEC-044.md |
| Tact Time | s | 1.7 | VERIFIED | SPEC-044.md |
| Inspection Width | mm | 800 | VERIFIED | SPEC-044.md |

## 8. System Configuration

| Item | Specification |
|---|---|
| Automation Level | Fully Automated Inline System |
| Stage | Precision Motorized Stage Assembly |
| Motion System | High Precision Linear Servo Motor |
| Sensor | Multi-head Sensor Package |
| Controller | Real-Time Embedded Controller |
| PC | Industrial PC (Intel i9, 64GB RAM, RTX GPU) |
| Software | MultiInspect Inspection Suite v3.2 |
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
| EtherNet/IP | Not Applicable |
| PROFINET | Supported |
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
| Source File | SPEC-044.md |
| Notes | Combines multiple sensing modalities for comprehensive inline electrode inspection. |
