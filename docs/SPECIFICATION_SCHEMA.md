# Specification Schema

전극 검사기 사양서 자동 생성 Agent가 다루는 두 핵심 데이터 모델
(`agent/schemas.py`)에 대한 전체 문서다. 필드를 추가/변경하기 전에 먼저
[Design Principles](#design-principles)와 [Backward Compatibility 절차](#backward-compatibility)를
읽는다.

```
Requirement (사용자 요구사항)
    -> RequirementSchema
    -> RAG(과거 사양서 검색) + Candidate Equipment
    -> SpecificationSchema (Specification JSON, single source of truth)
    -> {Markdown, HTML, PPTX}  (표현 계층 — 서로 변환하지 않고 각자 JSON에서 독립 생성)
```

## Design Principles

1. **Schema는 데이터 구조, 렌더링은 표현이다.** Markdown/HTML/PPTX의 디자인 편의
   때문에 `SpecificationSchema`의 필드를 바꾸지 않는다. 반대로 세 포맷은 전부
   `renderers/common.py`의 `build_sections()`가 만드는 동일한 중간 모델(`RenderSection`/
   `RenderRow`)만 소비하므로 세 포맷 사이에 내용이 어긋나지 않는다.
2. **Requirement와 Specification은 절대 같은 모델에 섞지 않는다.** "사용자가 원하는 것"과
   "장비가 실제로 제공하는 것"은 서로 다른 생명주기를 갖는다 — Requirement는 대화 초기에
   고정되고, Specification은 RAG/LLM 생성 후에도 검증 단계에서 계속 다듬어진다. 둘을
   비교한 결과(PASS/FAIL)는 `ComplianceRecord`라는 **파생/계산 전용** 모델로만 존재하고,
   `SpecificationSchema`에는 저장하지 않는다 (`agent/spec_validator.build_compliance_report()`).
3. **모든 필드는 기본적으로 Optional이다.** 검사 원리(2D Vision / 3D Laser / OCT /
   Interferometry / Reflectometry / White Light Interferometry / Contact / Other)에 따라
   해당 없는 필드가 많으므로("접촉식 장비에 광학계 필드가 없는 것이 정상"), pydantic
   레벨에서 필수로 강제하지 않는다. "이 사양서가 충분히 채워졌는가"는
   `agent/spec_validator.py`의 **비즈니스 로직**이 판단한다 (Test 2 참고).
4. **수치 필드는 근거를 추적하고, 서술 필드는 추적하지 않는다.** 실용적 절충이다 — 모든
   필드에 Source를 달면 스키마가 지나치게 커진다. 비교/검증의 핵심인 성능 수치
   (Measurement/Spatial/Inspection Performance, Defect Detection의 수치 필드)만
   `SourcedNumber`로 감싼다.

## Status 정의

`SourcedNumber.status` (`agent/schemas.py`의 `Status` 타입)는 "이 값이 얼마나 신뢰할
만한가"를 나타낸다. LLM의 "느낌 점수"가 아니라 아래 4가지로 명확히 구분되는 카테고리다.

| Status | 의미 |
|---|---|
| `USER_DEFINED` | 사용자가 요구사항으로 직접 입력한 값. Requirement에서 그대로 넘어왔거나, 사용자가 생성 후 직접 수정한 값. |
| `VERIFIED` | 원본 문서(벤더 사양서, 과거 사내 사양서 등)에서 직접 확인된 값. `source.document`가 채워져 있어야 한다. |
| `INFERRED` | 계산이나 명확한 논리적 추론으로 얻은 값 (예: 관련 필드로부터 유추). 항상 사용자 확인이 필요한 값으로 취급하고, `SpecificationSchema.needs_confirmation`에 자동으로 들어간다 (`agent/spec_generator._collect_needs_confirmation()`). |
| `UNKNOWN` | 근거를 찾지 못함. **기본값** — 아무것도 채우지 않으면 항상 `UNKNOWN`이다. |

## Source 구조 (`SourceRef`)

```python
class SourceRef(BaseModel):
    document: Optional[str]      # 근거 문서 파일명 (예: "vendor_spec.pptx")
    page: Optional[int]          # PDF 등 페이지 번호
    slide: Optional[int]         # PPTX에서 왔다면 슬라이드 번호
    section: Optional[str]       # 문서 내 섹션/제목
    paragraph: Optional[str]     # 문단 식별자(있는 경우)
    table: Optional[str]         # 표 식별자(있는 경우)
    source_type: Optional[str]   # 문서 종류: "vendor_document", "internal_spec", "datasheet" 등
```

문서 형식에 따라 채우는 필드가 다르다 — PPTX 문서라면 `slide`, PDF라면 `page`가 채워지고
나머지는 `None`으로 둔다. 여러 개를 동시에 채워도 된다(예: PDF 변환본에 슬라이드 원본
번호를 같이 기록하고 싶은 경우).

## Confidence

`SourcedNumber.confidence`는 `0.0` ~ `1.0` 사이 실수(`Field(ge=0.0, le=1.0)`)다. 임의의
"LLM 느낌"이 아니라 아래처럼 **근거의 확실성 등급**에 대응해야 한다 (강제되는 규칙은
아니고, Agent 프롬프트/생성 로직이 지켜야 하는 관례다):

- `0.9~1.0` — 원본 문서에서 명시적 수치를 그대로 읽음 (`VERIFIED`)
- `0.5~0.8` — 관련 필드로부터 계산/추론했고 근거가 비교적 명확함 (`INFERRED`)
- `0.5` 미만 — 추정 근거가 약함, 반드시 사용자 확인 필요 (`INFERRED`)
- `None` — confidence 자체를 매길 수 없음 (`UNKNOWN`, 또는 `USER_DEFINED`처럼 애초에
  "확신도"라는 개념이 적용되지 않는 값)

## SourcedNumber

```python
class SourcedNumber(BaseModel):
    value: Optional[float]
    unit: Optional[str]
    operator: Optional[Operator]   # "<=" | ">=" | "=" | "<" | ">"
    status: Status = "UNKNOWN"
    confidence: Optional[float]    # 0.0 ~ 1.0
    source: Optional[SourceRef]
```

`operator`는 이 수치가 Requirement와 비교될 때 어떤 방향이 "충족"인지를 값 자체에
싣는다 (예: accuracy는 작을수록 좋으므로 `<=`). 렌더러가 모든 필드를 "작을수록 좋다"로
하드코딩하지 않기 위한 설계다. `agent.spec_validator.build_compliance_report()`가
`operator`(없으면 기본값 `<=`)를 사용해 PASS/FAIL을 계산한다.

### 레거시 마이그레이션 (`from_legacy`)

v1 시절 `SourcedNumber(source_type: str, source: str)` 형태로 저장된 데이터를 v2
(`status` + `source: SourceRef`)로 옮길 때 쓰는 헬퍼다.

```python
SourcedNumber.from_legacy(value=0.5, unit="um", source_type="document", source="old.pptx")
# -> SourcedNumber(value=0.5, unit="um", status="VERIFIED", source=SourceRef(document="old.pptx"))
```

`source_type` -> `status` 매핑: `user_requirement`->`USER_DEFINED`, `document`->`VERIFIED`,
`inferred`->`INFERRED`, `default`(또는 미지정)->`UNKNOWN`.

## RequirementSchema

사용자가 입력/선택한 "요구사항"만 담는다. `SpecificationSchema`와 필드가 겹쳐 보여도
절대 같은 모델이 아니다 (Design Principle 2).

| Field | Type | 설명 |
|---|---|---|
| `raw_text` | `Optional[str]` | 사용자가 입력한 원본 자연어 |
| `target` | `RequirementTarget` | 검사 대상 개요 (material, product_type, width_mm, length_mm, thickness_range_um, substrate) |
| `inspection_items` | `List[str]` | 예: `thickness`, `surface_defect`, `profile_3d`, `coating`, `edge`, `other` |
| `measurement_method` | `Optional["non_contact"\|"contact"]` | |
| `measurement_principle` | `Optional["laser"\|"oct"\|"interferometry"\|"vision"\|"other"]` | |
| `required_accuracy_um` | `Optional[float]` | Requirement Compliance 비교에 쓰이는 원값(수치, 단위 없음 — um 고정) |
| `required_resolution_um` | `Optional[float]` | 〃 |
| `minimum_defect_size_um` | `Optional[float]` | 〃 |
| `scan_speed_requirement` | `Optional[str]` | |
| `notes` | `List[str]` | |

## SpecificationSchema

13개 섹션 + 메타 필드로 구성된다. "Optional/Required"는 pydantic 필수 여부가 아니라
(Design Principle 3에 따라 전부 Optional) **비즈니스 로직상 의미 있는 값이 없으면 검사기
용도상 불완전하다고 볼지**를 나타낸다.

### 1. Equipment (`equipment`)

| Field | Type | Unit | 설명 |
|---|---|---|---|
| `name` | `Optional[str]` | - | 설비명 |
| `equipment_type` | `Optional[str]` | - | 예: "In-line Optical Inspection System" |
| `manufacturer` | `Optional[str]` | - | |
| `model` | `Optional[str]` | - | |
| `version` | `Optional[str]` | - | |
| `application` | `Optional[str]` | - | 적용 공정 |
| `inspection_method` | `Optional[str]` | - | |
| `measurement_principle` | `Optional[str]` | - | 자유 텍스트 (RequirementSchema의 Literal과 달리 제약 없음 — 다양한 원리를 표현하기 위함) |
| `inline_offline` | `Optional["inline"\|"offline"]` | - | |

### 2. Inspection Target (`inspection_target`)

| Field | Type | Unit |
|---|---|---|
| `material` | `Optional[str]` | - |
| `product_type` | `Optional[str]` | - |
| `electrode_type` | `Optional[str]` | - |
| `width_mm` | `Optional[float]` | mm |
| `length_mm` | `Optional[float]` | mm |
| `thickness_um` | `Optional[float]` | um |
| `coating_thickness_um` | `Optional[float]` | um |
| `substrate` | `Optional[str]` | - |
| `inspection_direction` | `Optional[str]` | - |
| `line_speed_mm_s` | `Optional[SourcedNumber]` | mm/s |

### 3. Inspection Requirements (`inspection_requirements`)

검사 조건(무엇을 어떤 범위/주기로 검사하는지)이며, Inspection Target(대상 자체의 물성)과
별개다.

| Field | Type | Unit |
|---|---|---|
| `inspection_area` | `Optional[str]` | - |
| `inspection_width_mm` | `Optional[float]` | mm |
| `inspection_length_mm` | `Optional[float]` | mm |
| `sampling_interval` | `Optional[SourcedNumber]` | mm |
| `inspection_frequency` | `Optional[str]` | - |
| `inspection_mode` | `Optional[str]` | - |

(`SpecificationSchema.inspection_items: List[str]`도 이 섹션에 표시되지만 필드 자체는
top-level에 있다 — RequirementSchema와의 대응을 쉽게 하기 위함.)

### 4. Measurement Performance (`measurement_performance`)

전부 `Optional[SourcedNumber]`.

| Field | Unit |
|---|---|
| `measurement_range` | um |
| `resolution_um` | um |
| `accuracy_um` | um |
| `repeatability_um` | um |
| `reproducibility_um` | um |
| `linearity` | % |
| `measurement_speed` | mm/s |
| `sampling_rate` | Hz/kHz |

### 5. Spatial Performance (`spatial_performance`)

2D/3D 검사 장비를 고려해 Measurement Performance와 분리 유지한다. 전부
`Optional[SourcedNumber]`.

| Field | Unit |
|---|---|
| `x_range`, `y_range`, `z_range` | mm |
| `x_resolution_um`, `y_resolution_um`, `z_resolution_um` | um |
| `fov_mm` | mm |
| `working_distance` | mm |
| `pixel_size` | um |
| `point_spacing`, `profile_spacing` | um/mm |
| `sampling_interval_um` | um |

### 6. Optical System (`optical_system`)

광학식이 아닌 장비(접촉식 등)에는 해당 없는 필드가 많으므로 전부 Optional이고,
`SourcedNumber`가 아닌 서술형 필드다(광학계 자체가 "성능 수치 비교"의 대상이 아니라
"구성 설명"이기 때문).

| Field | Type | 설명 |
|---|---|---|
| `light_source` | `Optional[str]` | |
| `wavelength` | `Optional[str]` | |
| `spectral_range` | `Optional[str]` | |
| `optical_method` | `Optional[str]` | |
| `interferometry`, `reflectometry`, `oct`, `laser` | `Optional[bool]` | 측정 원리 지원 여부 플래그 (item 28: 다양한 측정 원리를 태그처럼 표시) |
| `sensor_type`, `camera`, `camera_resolution`, `lens`, `objective` | `Optional[str]` | |
| `working_distance` | `Optional[str]` | 문서화상 "Optical Working Distance"로 렌더링됨(Spatial Performance의 수치형 `working_distance`와 라벨 충돌 방지) |

접촉식 장비는 이 섹션 전체가 비어 있는 것이 정상이며, `SpecificationValidator`는
`optical_system`이 비어 있다는 이유로 에러를 내지 않는다 (Test 8).

### 7. Defect Inspection (`defect_detection`)

| Field | Type | Unit |
|---|---|---|
| `defect_detection` | `Optional[bool]` | - |
| `minimum_defect_size_um` | `Optional[SourcedNumber]` | um |
| `defect_types` | `List[str]` | - (실제 문서에서 확인된 종류만. AI가 임의로 채우지 않음 — 기본값은 항상 빈 리스트) |
| `detection_resolution` | `Optional[SourcedNumber]` | um |
| `defect_detection_accuracy` | `Optional[SourcedNumber]` | % |
| `false_positive_rate`, `false_negative_rate` | `Optional[SourcedNumber]` | % |
| `classification` | `Optional[bool]` | - |

### 7-1. Inspection Performance (`inspection_performance`)

원래 있던 필드(요청서의 13개 섹션 목록에는 없었지만 기존 기능 유지 원칙에 따라 보존).
전부 `Optional[SourcedNumber]`.

| Field | Unit |
|---|---|
| `scan_speed_mm_s`, `line_speed_mm_s`, `measurement_speed` | mm/s |
| `tact_time_s` | s |
| `inspection_width_mm` | mm |

### 8. System Configuration (`system`)

전부 `Optional[str]` (서술형).

`automation_level`, `stage`, `motion_system`, `sensor`, `controller`, `pc`, `software`,
`display`, `power`, `air`, `cooling`, `mechanical_configuration`, `data_output`.

### 9. Interfaces / Data (`interfaces`)

| Field | Type |
|---|---|
| `plc`, `mes`, `opc_ua`, `ethernet_ip`, `profinet`, `modbus`, `ethernet`, `digital_io`, `analog_io`, `api` | `Optional[bool]` (지원 여부) |
| `data_format`, `data_storage`, `network` | `Optional[str]` |
| `other_interfaces` | `List[str]` |

존재하지 않는 인터페이스는 `None`(=렌더링 시 `UNKNOWN`)으로 둔다. `False`(명시적 미지원)와
`None`(확인 안 됨)을 구분한다.

### 10. Environment (`environment`)

전부 `Optional[str]` (서술형 — 범위/조건을 문자열로 표현, 예: `"15~30 degC"`).

`operating_temperature`, `storage_temperature`, `humidity`, `installation_space`, `power`
(설치 현장의 전력 요구사항 — System Configuration의 `power`는 설비 자체 스펙이라 다른
개념), `vibration_requirement`, `dust`, `installation_environment`, `clean_room`.

### 11. Safety (`safety`)

| Field | Type |
|---|---|
| `safety_standard`, `laser_class` | `Optional[str]` |
| `interlock`, `emergency_stop`, `safety_sensor`, `protective_cover` | `Optional[bool]` |

### 메타 필드 (섹션 밖)

| Field | Type | 설명 |
|---|---|---|
| `notes` | `List[str]` | 자유 노트 |
| `assumptions` | `List[str]` | 생성 시 전제한 가정 |
| `sources` | `List[str]` | 이 사양서 생성에 참고한 문서 파일명 목록 |
| `needs_confirmation` | `List[str]` | `INFERRED`/`UNKNOWN`으로 채워져 사용자 확인이 필요한 필드의 dotted path 목록 (예: `"measurement_performance.accuracy_um"`) |

## Requirement vs Specification 분리 (재확인)

- `RequirementSchema` — 사용자가 원하는 것. Agent 파이프라인의 입력.
- `SpecificationSchema` — 장비가 실제로/제안상 제공하는 것. Agent 파이프라인의 출력.
- 이 둘을 비교한 결과(`ComplianceRecord`)는 **어느 쪽에도 저장되지 않는다.**
  `agent.spec_validator.build_compliance_report(spec, requirement)`가 렌더링 시점마다
  다시 계산한다.

```python
class ComplianceRecord(BaseModel):
    item: str                       # 사람이 읽을 항목명 (예: "Accuracy")
    unit: Optional[str]
    requirement: Optional[float]    # RequirementSchema에서 온 원하는 값
    specification: Optional[float]  # SpecificationSchema의 SourcedNumber.value
    operator: Optional[Operator]
    result: "PASS" | "FAIL" | "UNKNOWN"
    reason: str                     # 사람이 읽을 판정 근거 (예: "0.5um <= 1.0um")
    source: Optional[SourceRef]
```

현재 비교 로직이 정의된 항목은 `agent/spec_validator.py`의 `_COMPLIANCE_FIELDS`에
등록된 3개(Accuracy, Resolution, Minimum Defect Size)뿐이다 — 비교 기준이 없는 필드까지
`UNKNOWN`으로 채워 표를 불필요하게 늘리지 않기 위함이다. 새 비교 항목이 필요하면 이
목록에 `(requirement 필드명, spec 섹션명, spec 필드명, 라벨)` 튜플을 추가한다.

## ValidationResult

`SpecificationSchema`에도 저장되지 않는 파생 정보다. `agent.spec_validator.validate_specification()`이
매번 새로 계산한다.

```python
class ValidationIssue(BaseModel):
    level: "error" | "warning" | "info"
    field: str      # dotted path
    message: str

class ValidationResult(BaseModel):
    is_valid: bool           # error 레벨 issue가 하나도 없으면 True
    issues: List[ValidationIssue]
    missing_fields: List[str]
    questions: List[str]
```

검증 종류(`agent/spec_validator.py`): Schema(필수 비즈니스 필드 존재), Unit(필드명이
암시하는 단위와 실제 unit 일치), Range/Logic(분해능 <= 측정범위, 음수 값 등), Source
(status와 source 정합성), Requirement Coverage(요청한 검사 항목이 실제로 다뤄졌는지).

## Backward Compatibility

Schema를 변경해야 할 때는 항상 아래 순서로 진행한다:

1. **Migration strategy 작성** — 기존 데이터를 새 구조로 어떻게 옮길지 정의한다
   (`SourcedNumber.from_legacy()`가 실제 사례). 이 문서의 해당 섹션에 마이그레이션
   방법을 추가한다.
2. **기존 테스트 수정** — `tests/test_agent_pipeline.py`, `tests/test_renderers.py`,
   `tests/test_schema_validation.py`가 새 구조를 기준으로 통과하도록 갱신한다. 기존
   필드가 제거되지 않았는지 확인하는 회귀 테스트
   (`test_specification_schema_has_expected_top_level_sections`)를 유지한다.
3. **Backward compatibility 확인** — 가능하면 레거시 형태를 받아들이는 헬퍼(`from_legacy`류)를
   제공하고, 최소한 레거시 데이터를 읽었을 때 명확한 에러가 나는지 확인한다(조용히
   틀린 값이 되지 않도록).

### v1 -> v2 변경 이력 (참고용)

`SourcedNumber.source_type: Optional[str]` + `source: Optional[str]` (v1) ->
`SourcedNumber.status: Status` + `source: Optional[SourceRef]` (v2). "얼마나 신뢰할
만한가"(status)와 "어디서 왔는가"(source)가 서로 다른 축이라 분리했다. v1 데이터는
`SourcedNumber.from_legacy(value=..., unit=..., source_type=..., source=...)`로 변환한다.

## 관련 문서

- `docs/SPECIFICATION_MARKDOWN_FORMAT.md` — Markdown 렌더링/파싱 포맷 상세
- `docs/PPT_SLIDE_STRUCTURE.md` — PPTX 논리 슬라이드 구조
- `docs/examples/example_specification.json` — 공개 가능한 예시 Specification JSON 1건
- `templates/specification.md` — 빈 Markdown 스켈레톤
- `IMPLEMENTATION_PLAN.md` — Agent 파이프라인 전체 아키텍처
