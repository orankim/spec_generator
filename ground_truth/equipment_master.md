# Equipment Ground Truth Master

이 파일은 `sample_specs/`에 있는 테스트용 장비 사양서의 정답(Ground Truth)을
사람이 확인하기 쉬운 표로 정리한 것이다.

**주의: 이 파일은 RAG 인덱싱 대상이 아니다.** `build_rag_ollama.py`는
`sample_specs/*.md`만 globbing하므로 `ground_truth/` 폴더의 이 파일은 벡터
DB에 들어가지 않는다 — 검색 결과 정답지를 검색 대상 자체에 섞지 않기 위함이다.

`UNKNOWN`은 "값이 존재하지만 모른다"는 뜻이 아니라, **해당 사양서 원문에
그 정보 자체가 아예 기재되어 있지 않다**는 뜻이다(의도적 설계 — RAG/Hard
Requirement 검증이 "정보 없음"을 UNKNOWN으로 정직하게 처리하는지 테스트하기
위함). `sample_specs/SPEC-0NN.md`에 `UNKNOWN`이라는 문자열이나 해당 필드의
값을 유추할 수 있는 다른 표현이 있으면 안 된다.

## 1. 신규 장비 (SPEC-011 ~ SPEC-050) — Ground Truth

이 값들은 `tests/ground_truth_data.py`(`GROUND_TRUTH`)에 정의되어 있고,
`scripts/generate_sample_specs_011_050.py`가 이 값 그대로
`sample_specs/SPEC-011.md` ~ `SPEC-050.md`를 생성했다.
`tests/test_sample_specs_ground_truth.py`가 생성된 문서와 이 값이 정확히
일치하는지(값이 있는 필드는 값이, UNKNOWN인 필드는 그 정보 자체가 문서에
없는지) 자동 검증한다.

| SPEC | Model | Equipment Type | Mode | Width mm | Speed mm/s | Range μm | Accuracy μm | Resolution μm | Min Detectable Defect μm | Principle | Inspection Items |
|---|---|---|---|---:|---:|---|---:|---:|---:|---|---|
| SPEC-011 | ThicknessPro TP-200 | Thickness Inspection | Inline | 500 | 300 | 0~200 | 0.5 | 0.1 | UNKNOWN | Laser | thickness |
| SPEC-012 | ThicknessPro TP-500 | Thickness Inspection | Inline | 800 | 500 | 0~500 | 2 | 0.2 | UNKNOWN | Laser | thickness |
| SPEC-013 | ThicknessPro TP-800 | Thickness Inspection | Inline | 1200 | 800 | 0~800 | 0.8 | 0.1 | UNKNOWN | Optical | thickness |
| SPEC-014 | PrecisionGauge PG-100 | Thickness Inspection | Offline | 300 | UNKNOWN | 0~100 | 0.1 | 0.01 | UNKNOWN | Interferometry | thickness |
| SPEC-015 | PrecisionGauge PG-300 | Thickness Inspection | Offline | 400 | UNKNOWN | 0~300 | 0.3 | 0.05 | UNKNOWN | Interferometry | thickness |
| SPEC-016 | PrecisionGauge PG-600 | Thickness Inspection | Offline | 600 | UNKNOWN | 0~600 | 0.5 | 0.05 | UNKNOWN | OCT | thickness |
| SPEC-017 | FastThickness FT-400 | Thickness Inspection | Inline | 600 | 1200 | 0~400 | 1.5 | 0.2 | UNKNOWN | Laser | thickness |
| SPEC-018 | WideThickness WT-1000 | Thickness Inspection | Inline | 1500 | 700 | 0~300 | 1 | 0.2 | UNKNOWN | Optical | thickness |
| SPEC-019 | VisionInspect VI-300 | Surface Inspection | Inline | 300 | 1000 | UNKNOWN | UNKNOWN | UNKNOWN | 10 | Machine Vision | scratch, contamination |
| SPEC-020 | VisionInspect VI-600 | Surface Inspection | Inline | 600 | 800 | UNKNOWN | UNKNOWN | UNKNOWN | 5 | Machine Vision | scratch, contamination, particle |
| SPEC-021 | VisionInspect VI-1000 | Surface Inspection | Inline | 1000 | 600 | UNKNOWN | UNKNOWN | UNKNOWN | 3 | Machine Vision | scratch, contamination, particle, pinhole |
| SPEC-022 | MicroDefect MD-200 | Surface Inspection | Offline | 200 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 1 | High Resolution Vision | scratch, crack, pinhole |
| SPEC-023 | MicroDefect MD-500 | Surface Inspection | Offline | 500 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 2 | Confocal Vision | scratch, particle, contamination |
| SPEC-024 | SurfaceScan SS-800 | Surface Inspection | Inline | 800 | 1000 | UNKNOWN | UNKNOWN | UNKNOWN | 2 | Line Scan Vision | surface_defect |
| SPEC-025 | SurfaceScan SS-1200 | Surface Inspection | Inline | 1200 | 500 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Optical Vision | scratch, contamination, coating_defect |
| SPEC-026 | EdgeVision EV-300 | Edge Inspection | Inline | 300 | 800 | UNKNOWN | UNKNOWN | UNKNOWN | 10 | Vision | edge_defect |
| SPEC-027 | EdgeVision EV-600 | Edge Inspection | Inline | 600 | 700 | UNKNOWN | UNKNOWN | UNKNOWN | 5 | Vision | edge_defect, edge_crack |
| SPEC-028 | EdgeVision EV-1000 | Edge Inspection | Inline | 1000 | 500 | UNKNOWN | UNKNOWN | UNKNOWN | 3 | High Resolution Vision | edge_defect, edge_crack, edge_chipping |
| SPEC-029 | EdgePrecision EP-400 | Edge Inspection | Offline | 400 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 1 | Microscope Vision | edge_defect, edge_crack |
| SPEC-030 | EdgeScan Pro ES-800 | Edge Inspection | Inline | 800 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 2 | Laser + Vision | edge_defect, edge_crack, edge_profile |
| SPEC-031 | OCTInspect OI-300 | OCT Inspection | Inline | 300 | 300 | 5~300 | 1 | 0.5 | UNKNOWN | OCT | thickness, void |
| SPEC-032 | OCTInspect OI-600 | OCT Inspection | Inline | 600 | 500 | 5~500 | 1 | 0.5 | UNKNOWN | OCT | thickness, void, coating_non_uniformity |
| SPEC-033 | OCTInspect OI-1000 | OCT Inspection | Inline | 1000 | 400 | 1~800 | 2 | 1 | UNKNOWN | OCT | thickness, void |
| SPEC-034 | CoatingOCT CO-400 | Coating Inspection | Offline | 400 | UNKNOWN | 1~400 | 0.5 | 0.1 | UNKNOWN | OCT | thickness, coating_non_uniformity, void |
| SPEC-035 | FilmInspect FI-500 | Coating Inspection | Inline | 500 | 600 | 0.1~500 | 0.8 | 0.1 | UNKNOWN | Spectral Interferometry | thickness, coating_non_uniformity |
| SPEC-036 | VoidScan VS-800 | Void Inspection | Inline | 800 | 300 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | OCT | void |
| SPEC-037 | ProfileScan PS-300 | 3D Profile Inspection | Inline | 300 | 500 | 0~300 | 1 | 0.2 | UNKNOWN | Laser Profiling | profile_3d |
| SPEC-038 | ProfileScan PS-600 | 3D Profile Inspection | Inline | 600 | 500 | 0~500 | 1 | 0.2 | UNKNOWN | Laser Profiling | profile_3d, surface_defect |
| SPEC-039 | ProfileScan PS-1000 | 3D Profile Inspection | Inline | 1000 | 700 | 0~1000 | 2 | 0.5 | UNKNOWN | 3D Laser | profile_3d |
| SPEC-040 | NanoProfile NP-500 | 3D Profile Inspection | Offline | 500 | UNKNOWN | 0~100 | 0.2 | 0.05 | UNKNOWN | Confocal | profile_3d, surface_defect |
| SPEC-041 | WideProfile WP-1200 | 3D Profile Inspection | Inline | 1200 | UNKNOWN | 0~500 | 1.5 | 0.3 | UNKNOWN | Laser Triangulation | profile_3d |
| SPEC-042 | MultiInspect MI-500 | Multi Inspection | Inline | 500 | 500 | 0~300 | 0.8 | 0.2 | 5 | Multi-sensor | thickness, surface_defect |
| SPEC-043 | MultiInspect MI-600 | Multi Inspection | Inline | 600 | 500 | 0~300 | 1.2 | 0.2 | 5 | Multi-sensor | thickness, surface_defect |
| SPEC-044 | MultiInspect MI-800 | Multi Inspection | Inline | 800 | 600 | 0~500 | 0.8 | 0.1 | 3 | Multi-sensor | thickness, surface_defect, profile_3d |
| SPEC-045 | MultiInspect MI-1000 | Multi Inspection | Inline | 1000 | 500 | 0~300 | 0.5 | 0.1 | 2 | Multi-sensor | thickness, surface_defect, edge_defect |
| SPEC-046 | TotalInspect TI-800 | Multi Inspection | Inline | 800 | 800 | 0~800 | 1 | 0.2 | 2 | Multi-sensor | thickness, surface_defect, edge_defect, profile_3d |
| SPEC-047 | TotalInspect TI-1200 | Multi Inspection | Inline | 1200 | 600 | 0~500 | UNKNOWN | 0.2 | UNKNOWN | Multi-sensor | thickness, surface_defect, void, coating_non_uniformity |
| SPEC-048 | BasicInspect BI-600 | Basic Inspection | Inline | 600 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Optical | thickness |
| SPEC-049 | VisionFlex VF-800 | Surface Inspection | Inline | 800 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Optical Vision | scratch, particle |
| SPEC-050 | HybridScan HS-1000 | Hybrid Inspection | Inline | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Hybrid Optical | thickness, void, surface_defect |


## 2. 기존 장비 (SPEC-001 ~ SPEC-010) — 실제 문서 값

아래 값은 `agent/candidate_matcher.py`가 실제로 각 문서 원문에서 추출하는
것과 동일한 파서로 뽑은 값이다(수기 전사 오류 방지 목적으로
`scripts/generate_equipment_master.py`가 자동 생성).

| SPEC | Manufacturer/Model | Mode | Width mm | Speed | Range | Accuracy | Min Detectable Defect | Principle | Defect Types |
|---|---|---|---|---|---|---|---|---|---|
| SPEC-001 | OptiScan ES-200 | inline | 500.0 | 100 mm/s | 0~200 um | 1 um | 30 um | Laser | Scratch, Pin Hole, Coating Defect |
| SPEC-002 | InterferoTech WI-300 | offline | UNKNOWN | 30 um | 0~300 um | 0.5 um | 5 um | Interferometry | Scratch, Pit, Particle |
| SPEC-003 | OCTVision OCT-E100 | inline | 300.0 | UNKNOWN | 1~500 um | 2 um | UNKNOWN | OCT | N/A |
| SPEC-004 | Reflecta RN-500 | offline | UNKNOWN | UNKNOWN | 0.1~50 um | 0.5 % | UNKNOWN | Spectral Reflectometry | N/A |
| SPEC-005 | LaserMetrix LP-500 | inline | 1000.0 | 200 mm/s | 0~500 um | 2 um | 50 um | Laser | Scratch, Crack, Particle |
| SPEC-006 | VisionMeasure VM-200 | inline | 600.0 | 300 mm/s | UNKNOWN | 20 um | 25 um | Vision | Scratch, Contamination, Edge Defect |
| SPEC-007 | NanoProfile NP-100 | offline | UNKNOWN | UNKNOWN | 0~100 um | 0.3 um | 3 um | Interferometry | Scratch, Pit, Particle |
| SPEC-008 | CoatingInspect CI-400 | inline | 500.0 | UNKNOWN | 5~400 um | 1.5 um | 20 um | OCT | Coating Non-uniformity, Void |
| SPEC-009 | FastScan FS-1000 | inline | 1200.0 | 1000 mm/s | 0~1000 um | 3 um | 100 um | Laser | Large Scratch, Crack, Edge Defect |
| SPEC-010 | MultiSense MS-600 | inline | 800.0 | 500 mm/s | 0~300 um | 0.8 um | 15 um | Vision | Scratch, Crack, Particle, Coating Defect |

