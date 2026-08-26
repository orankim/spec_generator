# PrecisionGauge PG-600

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | PrecisionGauge PG-600 |
| Equipment Type | Thickness Inspection |
| Manufacturer | PrecisionGauge |
| Model | PG-600 |
| Version | v2.0 |
| Application | Lithium-ion Battery Electrode Production Line |
| Inspection Method | Non-contact Optical Inspection |
| Measurement Principle | OCT |
| Inline / Offline | offline |
| Measurement Type | non-contact |

## 2. Inspection Target

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Material | - | Lithium-ion Battery Electrode Roll | VERIFIED | SPEC-016.md |
| Product Type | - | Cathode / Anode Coated Sheet | VERIFIED | SPEC-016.md |
| Electrode Type | - | Battery Electrode | VERIFIED | SPEC-016.md |
| Width | mm | 600 | VERIFIED | SPEC-016.md |
| Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-016.md |
| Thickness | μm | 50 ~ 300 | VERIFIED | SPEC-016.md |
| Coating Thickness | μm | 20 ~ 150 | VERIFIED | SPEC-016.md |
| Substrate | - | Copper Foil (10 μm) / Aluminum Foil (15 μm) | VERIFIED | SPEC-016.md |
| Inspection Direction | - | Top & Bottom Dual Side | VERIFIED | SPEC-016.md |
| Target Line Speed | mm/s | 700 | VERIFIED | SPEC-016.md |

## 3. Inspection Requirements

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Inspection Items | - | thickness | VERIFIED | SPEC-016.md |
| Inspection Area | - | Full Electrode Width & Length | VERIFIED | SPEC-016.md |
| Inspection Width | mm | 600 | VERIFIED | SPEC-016.md |
| Inspection Length | mm | Unlimited (continuous measurement) | VERIFIED | SPEC-016.md |
| Sampling Interval | μm | 20 | VERIFIED | SPEC-016.md |
| Inspection Frequency | Hz | 1000 | VERIFIED | SPEC-016.md |
| Inspection Mode | - | offline | VERIFIED | SPEC-016.md |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | μm | 0 ~ 600 | VERIFIED | SPEC-016.md |
| Resolution | μm | 0.05 | VERIFIED | SPEC-016.md |
| Accuracy | μm | ±0.5 | VERIFIED | SPEC-016.md |
| Repeatability | μm | ±0.2 | VERIFIED | SPEC-016.md |
| Reproducibility | μm | ±0.4 | VERIFIED | SPEC-016.md |
| Linearity | % | ±0.1 | VERIFIED | SPEC-016.md |
| Measurement Speed | mm/s | 700 | VERIFIED | SPEC-016.md |
| Sampling Rate | Hz | 5 kHz | VERIFIED | SPEC-016.md |

## 5. Spatial Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| X Range | mm | 600 | VERIFIED | SPEC-016.md |
| Y Range | mm | Continuous | VERIFIED | SPEC-016.md |
| Z Range | μm | 0 ~ 600 | VERIFIED | SPEC-016.md |
| X Resolution | μm | 20 | VERIFIED | SPEC-016.md |
| Y Resolution | μm | 20 | VERIFIED | SPEC-016.md |
| Z Resolution | μm | 0.05 | VERIFIED | SPEC-016.md |
| FOV | mm | 600 mm | VERIFIED | SPEC-016.md |
| Working Distance | mm | 100 | VERIFIED | SPEC-016.md |
| Pixel Size | μm | 5.0 | VERIFIED | SPEC-016.md |
| Point Spacing | μm | 20 | VERIFIED | SPEC-016.md |
| Profile Spacing | μm | 50 | VERIFIED | SPEC-016.md |
| Spatial Sampling Interval | μm | 20 | VERIFIED | SPEC-016.md |

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
| Defect Detection | - | Supported | VERIFIED | SPEC-016.md |
| Minimum Defect Size | μm | 30 | VERIFIED | SPEC-016.md |
| Defect Types | - | surface_defect, scratch | VERIFIED | SPEC-016.md |
| Detection Resolution | μm | 0.05 | VERIFIED | SPEC-016.md |
| Defect Detection Accuracy | % | 99.5 | VERIFIED | SPEC-016.md |
| False Positive Rate | % | 0.1 | VERIFIED | SPEC-016.md |
| False Negative Rate | % | 0.01 | VERIFIED | SPEC-016.md |
| Classification | - | Supported | VERIFIED | SPEC-016.md |

## 7-1. Inspection Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Scan Speed | mm/s | 700 | VERIFIED | SPEC-016.md |
| Line Speed | mm/s | 700 | VERIFIED | SPEC-016.md |
| Overall Measurement Speed | mm/s | 700 | VERIFIED | SPEC-016.md |
| Tact Time | s | 1.4 | VERIFIED | SPEC-016.md |
| Inspection Width | mm | 600 | VERIFIED | SPEC-016.md |

## 8. System Configuration

| Item | Specification |
|---|---|
| Automation Level | Fully Automated Inline System |
| Stage | Precision Motorized Stage Assembly |
| Motion System | High Precision Linear Servo Motor |
| Sensor | Multi-head Sensor Package |
| Controller | Real-Time Embedded Controller |
| PC | Industrial PC (Intel i9, 64GB RAM, RTX GPU) |
| Software | PrecisionGauge Inspection Suite v3.2 |
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
| Operating Temperature | 18 ~ 28 °C |
| Storage Temperature | -10 ~ 50 °C |
| Humidity | 30 ~ 70 %RH |
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
| Source File | SPEC-016.md |
| Notes | Optimized for offline high-precision electrode thickness measurement. |
