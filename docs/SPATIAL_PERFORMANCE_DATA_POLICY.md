# Spatial Performance 데이터 생성 정책

`sample_specs/SPEC-001.md` ~ `SPEC-100.md`에 `## Spatial Performance` 절을
보강할 때 실제로 적용한 규칙을 기록한다. 생성 스크립트는
`scripts/enrich_spatial_performance.py`이며, 이 문서는 그 스크립트가 구현하는
정책을 사람이 읽을 수 있게 요약한 것이다(스크립트 자체가 최종 근거).

## 원칙

1. **새 정밀 숫자를 무작위로 만들지 않는다.** 모든 값은 그 SPEC 파일에 이미
   적혀 있는 값(Measurement Range/Resolution/Accuracy, Maximum (Electrode)
   Width, Maximum Measurement Area/Sample Size, 기존 X/Y/XY Resolution, 기존
   Field of View, Objective 배율)에서 재사용하거나 그대로 파생시킨다. 유일한
   예외는 마이크로스코프 대물렌즈 배율 → 표준 장동거리(Working Distance) 근사
   대응표(`_OBJECTIVE_WD_MM`) 하나뿐이다.
2. **장비 원리상 의미 없는 축은 억지로 채우지 않는다.** 근거가 없으면 해당
   항목 자체를 아예 쓰지 않는다(UNKNOWN으로 남김) — 이 corpus의 기존 관행
   (SPEC-002/007이 이미 일부 항목만 적어 두는 방식)과 동일하다.
3. **이미 다른 절에 있는 값은 원문에 중복으로 다시 적지 않는다.** Z Range/Z
   Resolution은 거의 모든 장비에서 `## Measurement Performance`의 "주" 측정
   범위/해상도와 같은 개념(두께/깊이 축)이므로, 문자 그대로 값을 중복 기재하는
   대신 `agent/candidate_matcher.py`가 `CandidateEquipmentFact` 조립 시점에
   코드로 그 값을 그대로 재사용한다. X/Y(/XY) Resolution도 카메라 비전 계열이
   이미 `## Measurement Performance`에 직접 적어 두는 값이면 마찬가지로 코드가
   직접 추출하고, 원문에는 다시 적지 않는다. (배경: 처음에는 이 값들도 전부
   `## Spatial Performance`에 중복으로 적었으나, heading 기반 RAG chunking이
   그 중복 텍스트로 새 chunk를 만들어 fake-hash 임베딩 기반 결정론적 테스트의
   검색 순위가 흔들리는 부작용이 실측되어 정책을 바꿨다.)
4. **SPEC-001~010 관련 이력.** `tests/test_sample_specs_ground_truth.py`에
   SPEC-001~010을 절대 수정하지 말라는 SHA256 고정 테스트가 있었으나, 이번
   작업 착수 시점에 이미 그 고정 해시가 실제 파일 내용과 어긋나 있어(이전
   어느 시점에 파일은 바뀌고 해시는 갱신되지 않은 것으로 보임) 실질적인 보호
   효과가 없는 상태였다. 사용자 확인 후 이 10개 파일도 다른 90개와 동일하게
   보강 대상에 포함했다.

## 장비 유형 분류 (Measurement Principle 키워드 기반)

| 분류 | 판정 키워드 | X Range | FOV | Pixel Size |
|---|---|---|---|---|
| Confocal | "confocal"(비전 제외) | 스캔형만 | 없음 | 없음 |
| OCT/Interferometry | "oct", "interferometry", "reflectometry" | 스캔형만 | 있으면 유지 | 없음 |
| Structured Light | "structured light" | 항상 | 있으면 유지 | 없음 |
| Laser Profilometer | "laser"(비전 제외) | 스캔형만 | 없음 | 없음 |
| Camera Vision | "vision" | 항상 | 있으면 유지 | 카메라 명시 시 |
| Multi-sensor/Hybrid | "multi-sensor", "laser"+"vision" | 항상 | 있으면 유지 | 카메라 명시 시 |
| 기타(Optical 등) | 위에 해당 없음 | 없음 | 없음 | 없음 |

"스캔형"은 Equipment Type/Measurement Principle에 3D/Profile/Profiling/
Profilometry/Multi-Modal 키워드가 있는 경우다 — 단순 "Thickness Inspection"
단일 지점 센서(예: 고정형 OCT/Confocal 두께 게이지)는 폭(X) 방향 스캔 근거가
없으므로 X Range를 채우지 않는다.

## 항목별 파생 규칙

- **X Range**: 스캔형 장비는 `Maximum (Electrode) Width`를 `0 ~ width`로 사용.
  유한 영역(`Maximum Measurement Area`/`Measurement Area`/`Maximum Sample
  Size`)이 있는 오프라인 장비는 그 값을 그대로 사용.
- **Y Range**: 유한 영역이 있는 오프라인 장비만 채운다. Inline 폭-스캔형
  장비는 진행 방향이 연속(무한)이라 만들어내지 않는다.
- **Z Range / Z Resolution**: 원문에 쓰지 않는다 — 코드가 `Measurement
  Performance`의 주 범위/해상도를 그대로 재사용한다(정책 3 참고).
- **X/Y Resolution**: 원문에 이미 있는 X/Y/XY Resolution 값을 코드가 직접
  추출한다(정책 3 참고). 없으면 채우지 않는다(만들어내지 않음).
- **FOV**: 기존 `Field of View`/`FOV` 행이 있으면 그대로 유지. 없으면 유한
  영역(`Maximum Measurement Area` 등)이 있을 때만 그 값을 사용.
- **Working Distance**: `Optical System`의 `Objective: 5X / 10X / ...` 배율이
  있을 때만, 최저 배율(=최대 WD)을 표준 장동거리 대응표에서 찾아 채운다.
- **Pixel Size**: 카메라(Camera/CMOS/CCD 명시) 기반 장비에서만, 이미 있는
  X/Y Resolution 값을 그대로 채택한다(이 corpus 수준에서 두 개념을 구분할
  별도 근거가 없어 동일 값 재사용이 새 숫자를 만드는 것보다 안전한 선택).
