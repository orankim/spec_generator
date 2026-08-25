"""
전극 검사기 사양서 자동 생성 Agent의 Pydantic 스키마 정의.

Requirement(사용자 요구사항)와 Specification(최종 장비 사양서)을
서로 다른 모델로 분리한다 (기획안 6절, 18절). 수치/성능 계열 필드는
SourcedNumber로 감싸 근거(source)를 추적하고, 서술/분류 계열 필드는
일반 값으로 둔다 — 스키마 크기와 근거 추적 필요성 사이의 실용적 절충이며
자세한 이유는 IMPLEMENTATION_PLAN.md 2절에 기록되어 있다.

v2 변경사항 (breaking change, docs/SPECIFICATION_SCHEMA.md 마이그레이션 절 참고):
- SourcedNumber.source_type(문자열) -> SourcedNumber.status(Status enum) + source(SourceRef 객체)로 분리.
  "이 값이 얼마나 신뢰할 만한가"(status)와 "어디서 왔는가"(source)는 서로 다른 축이라 분리했다.
- SourcedNumber.operator 추가: 이 수치가 요구사항과 비교될 때 어떤 방향(<=, >= 등)이 "좋음"인지
  값 자체에 싣는다. 이전 버전은 렌더러가 모든 필드를 "작을수록 좋다"로 하드코딩했었다.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ==========================================
# 공통: 근거가 있는 수치 필드
# ==========================================

#: 값의 신뢰도/출처 종류. LLM의 "느낌 점수"가 아니라 명확한 기준으로 정해진다
#: (docs/SPECIFICATION_SCHEMA.md "Status 정의" 절 참고).
#:   USER_DEFINED — 사용자가 직접 입력한 요구사항
#:   VERIFIED     — 원본 문서에서 직접 확인된 값
#:   INFERRED     — 계산/명확한 논리적 추론으로 얻은 값
#:   UNKNOWN      — 근거를 찾지 못함 (기본값)
Status = Literal["USER_DEFINED", "VERIFIED", "INFERRED", "UNKNOWN"]

Operator = Literal["<=", ">=", "=", "<", ">"]

# 이전 버전과의 호환을 위한 레거시 타입 별칭 (docs/SPECIFICATION_SCHEMA.md 마이그레이션 절 참고)
SourceType = Literal["document", "user_requirement", "inferred", "default"]

_LEGACY_SOURCE_TYPE_TO_STATUS = {
    "user_requirement": "USER_DEFINED",
    "document": "VERIFIED",
    "inferred": "INFERRED",
    "default": "UNKNOWN",
}


class SourceRef(BaseModel):
    """값의 구체적 근거 위치. PPTX에서 왔다면 slide, PDF라면 page를 채운다."""

    document: Optional[str] = Field(default=None, description="근거 문서 파일명")
    page: Optional[int] = None
    slide: Optional[int] = None
    section: Optional[str] = None
    paragraph: Optional[str] = None
    table: Optional[str] = None
    chunk_id: Optional[int] = Field(
        default=None, description="RAG chunk 순번 (build_rag_ollama.py가 markdown 소스에 부여, PPTX 소스는 None)"
    )
    source_type: Optional[str] = Field(
        default=None, description="문서 종류 (예: vendor_document, internal_spec, datasheet)"
    )


class SourcedRange(BaseModel):
    """
    근거가 있는 "범위" 필드(예: 측정 범위 0~200um). SourcedNumber는 값 하나만 담을 수
    있어 "장비가 실제로 커버하는 범위"를 표현하기에 부족하다 — 예: 요구 범위
    0~200um를 장비가 0~300um로 충족(포함)하는지는 min/max 둘 다 있어야 판정 가능하다
    (agent.units.range_covers). 기존 measurement_range(SourcedNumber, 하위호환 유지)와
    별도 필드로 둔다.
    """

    min: Optional[float] = None
    max: Optional[float] = None
    unit: Optional[str] = None
    status: Status = "UNKNOWN"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: Optional[SourceRef] = None
    reasoning: Optional[str] = None


class SourcedNumber(BaseModel):
    """근거가 있는 수치 필드. 문서에서 못 찾았고 사용자도 명시하지 않았다면 value=None으로 남긴다."""

    value: Optional[float] = None
    unit: Optional[str] = None
    operator: Optional[Operator] = Field(
        default=None, description="요구사항과 비교 시 어떤 방향이 '충족'인지 (예: accuracy는 '<=')"
    )
    status: Status = "UNKNOWN"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: Optional[SourceRef] = None
    reasoning: Optional[str] = Field(
        default=None,
        description="status가 INFERRED일 때 반드시 채운다 — 어떤 근거/계산으로 이 값을 추정했는지 (요청서 21절)",
    )

    @classmethod
    def from_legacy(
        cls,
        value: Optional[float] = None,
        unit: Optional[str] = None,
        source_type: Optional[str] = None,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        operator: Optional[Operator] = None,
    ) -> "SourcedNumber":
        """v1 형태(source_type: str, source: str)로 온 데이터를 v2로 변환한다."""
        status = _LEGACY_SOURCE_TYPE_TO_STATUS.get(source_type, "UNKNOWN") if source_type else "UNKNOWN"
        source_ref = SourceRef(document=source) if source else None
        return cls(value=value, unit=unit, operator=operator, status=status, confidence=confidence, source=source_ref)


# ==========================================
# Requirement 수치 필드 — "자연어의 숫자/단위를 문자열로만 저장하지 않는다" (요청서 5절)
# ==========================================
class RequirementValue(BaseModel):
    """단일 요구값 + 단위 + 비교 방향. 예: "정확도 1um 이하" -> {value:1.0, unit:"um", operator:"<="}."""

    value: Optional[float] = None
    unit: Optional[str] = None
    operator: Optional[Operator] = None


class RequirementRange(BaseModel):
    """범위 요구값. 예: "0~200um" -> {min:0, max:200, unit:"um"}."""

    min: Optional[float] = None
    max: Optional[float] = None
    unit: Optional[str] = None


# ==========================================
# Requirement Schema — 사용자가 입력/선택한 "요구사항"
# ==========================================
class RequirementTarget(BaseModel):
    material: Optional[str] = Field(default=None, description="검사 대상 (예: 양극, 음극, 분리막, 전극)")
    product_type: Optional[str] = None
    electrode_type: Optional[str] = None
    width_mm: Optional[float] = None
    length_mm: Optional[float] = None
    thickness_range_um: Optional[str] = Field(default=None, description="레거시 문자열 표기. 예: '0~200' (신규 입력은 thickness_range 사용 권장)")
    thickness_range: Optional[RequirementRange] = None
    coating_thickness: Optional[RequirementValue] = None
    line_speed: Optional[RequirementValue] = None
    substrate: Optional[str] = None


class RequirementSchema(BaseModel):
    raw_text: Optional[str] = Field(default=None, description="사용자가 입력한 원본 자연어 (있는 경우)")
    target: RequirementTarget = Field(default_factory=RequirementTarget)
    inspection_items: List[str] = Field(
        default_factory=list,
        description="예: thickness, surface_defect, profile_3d, coating, edge, other",
    )

    # Equipment
    equipment_type: Optional[str] = None
    measurement_method: Optional[Literal["non_contact", "contact"]] = None
    # 자유 문자열로 둔다("Spectral Reflectometry" 등 sample_specs 원문 그대로 담을 수
    # 있어야 함) — agent.categorical_match가 결정론적으로 canonical 라벨(OCT,
    # Interferometry, Laser, Vision, Spectral Reflectometry)로 정규화해 채운다.
    measurement_principle: Optional[str] = None
    inline_offline: Optional[Literal["inline", "offline"]] = None

    # Measurement Requirements — 레거시 float 필드는 하위호환을 위해 유지한다.
    # 신규 입력(자연어 파싱/구조화 UI)은 RequirementValue/RequirementRange 필드를 채우고,
    # RequirementSchema.sync_legacy_fields()가 두 표현을 서로 동기화한다.
    required_accuracy_um: Optional[float] = None
    required_resolution_um: Optional[float] = None
    minimum_defect_size_um: Optional[float] = None
    scan_speed_requirement: Optional[str] = None

    measurement_range: Optional[RequirementRange] = None
    accuracy: Optional[RequirementValue] = None
    resolution: Optional[RequirementValue] = None
    repeatability: Optional[RequirementValue] = None
    reproducibility: Optional[RequirementValue] = None
    measurement_speed: Optional[RequirementValue] = None
    sampling_rate: Optional[RequirementValue] = None
    sampling_interval: Optional[RequirementValue] = None

    # Defect Requirements
    defect_types: List[str] = Field(default_factory=list)
    minimum_defect_size: Optional[RequirementValue] = None
    detection_resolution: Optional[RequirementValue] = None
    detection_accuracy: Optional[RequirementValue] = None
    false_positive_rate: Optional[RequirementValue] = None
    false_negative_rate: Optional[RequirementValue] = None
    classification: Optional[bool] = None

    # System Requirements
    plc: Optional[bool] = None
    mes: Optional[bool] = None
    communication: Optional[str] = None
    data_output: Optional[str] = None
    installation_environment: Optional[str] = None

    # Production Requirements
    tact_time: Optional[RequirementValue] = None
    throughput: Optional[RequirementValue] = None
    uptime: Optional[RequirementValue] = None

    # Hard/Soft 분류 (요청서 16절) — dotted path(예: "accuracy", "target.width_mm")로
    # 이 요구사항 중 어떤 항목이 반드시 만족돼야 하는지(Hard)와 가능하면 만족하면
    # 좋은지(Soft)를 표시한다. 비워두면 agent.candidate_matcher의 기본 분류
    # (DEFAULT_HARD_REQUIREMENT_FIELDS)를 따른다.
    hard_requirements: List[str] = Field(default_factory=list)
    soft_requirements: List[str] = Field(default_factory=list)

    notes: List[str] = Field(default_factory=list)

    def sync_legacy_fields(self) -> "RequirementSchema":
        """
        신규 구조화 필드(accuracy/resolution/minimum_defect_size 등)와 레거시 float
        필드(required_accuracy_um 등)를 서로 채운다 — 둘 중 하나만 채워져 들어와도
        기존 코드(spec_generator/spec_validator/구 UI)와 신규 코드(candidate_matcher 등)
        양쪽에서 값을 읽을 수 있게 하기 위함이다. 값이 있는 쪽을 신뢰하며, 둘 다
        채워져 있으면 신규 구조화 필드를 우선한다(더 명시적인 unit/operator 정보를 담고 있으므로).
        """
        if self.accuracy and self.accuracy.value is not None:
            self.required_accuracy_um = self.accuracy.value
        elif self.required_accuracy_um is not None and self.accuracy is None:
            self.accuracy = RequirementValue(value=self.required_accuracy_um, unit="um", operator="<=")

        if self.resolution and self.resolution.value is not None:
            self.required_resolution_um = self.resolution.value
        elif self.required_resolution_um is not None and self.resolution is None:
            self.resolution = RequirementValue(value=self.required_resolution_um, unit="um", operator="<=")

        if self.minimum_defect_size and self.minimum_defect_size.value is not None:
            self.minimum_defect_size_um = self.minimum_defect_size.value
        elif self.minimum_defect_size_um is not None and self.minimum_defect_size is None:
            self.minimum_defect_size = RequirementValue(value=self.minimum_defect_size_um, unit="um", operator="<=")

        if self.target.thickness_range and self.target.thickness_range.min is not None:
            lo, hi = self.target.thickness_range.min, self.target.thickness_range.max
            self.target.thickness_range_um = f"{lo:g}~{hi:g}"
        elif self.target.thickness_range_um and self.target.thickness_range is None:
            from .units import parse_range

            parsed = parse_range(self.target.thickness_range_um + " um")
            if parsed:
                lo, hi, unit = parsed
                self.target.thickness_range = RequirementRange(min=lo, max=hi, unit=unit)

        return self


# ==========================================
# Specification Schema — 최종 장비 사양서
# ==========================================
class Equipment(BaseModel):
    name: Optional[str] = None
    equipment_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    version: Optional[str] = None
    application: Optional[str] = None
    inspection_method: Optional[str] = None
    measurement_principle: Optional[str] = None
    inline_offline: Optional[Literal["inline", "offline"]] = None
    measurement_method: Optional[Literal["non_contact", "contact"]] = Field(
        default=None,
        description="후보 문서에서 확인된 실제 접촉/비접촉 방식 (agent.candidate_matcher가 채움). "
        "requirement.measurement_method(사용자 요구값)와는 별개 — 요구값/실측값 혼동 방지 원칙(요청서)에 따름.",
    )


class InspectionTarget(BaseModel):
    material: Optional[str] = None
    product_type: Optional[str] = None
    electrode_type: Optional[str] = None
    width_mm: Optional[float] = None
    length_mm: Optional[float] = None
    thickness_um: Optional[float] = None
    coating_thickness_um: Optional[float] = None
    substrate: Optional[str] = None
    inspection_direction: Optional[str] = None
    line_speed_mm_s: Optional[SourcedNumber] = None


class InspectionRequirements(BaseModel):
    """검사 조건(무엇을 어떤 범위/주기로 검사하는지). Inspection Target(대상 자체의 물성)과는 별개."""

    inspection_area: Optional[str] = None
    inspection_width_mm: Optional[float] = None
    inspection_length_mm: Optional[float] = None
    sampling_interval: Optional[SourcedNumber] = None
    inspection_frequency: Optional[str] = None
    inspection_mode: Optional[str] = None


class MeasurementPerformance(BaseModel):
    measurement_range: Optional[SourcedNumber] = None
    measurement_range_full: Optional[SourcedRange] = Field(
        default=None,
        description="측정 범위(min~max). measurement_range(단일 값, 하위호환 유지)와 별도로, "
        "요구 범위 포함 여부 판정(agent.units.range_covers)과 UI의 '0~200 μm' 표시에 쓰인다.",
    )
    resolution_um: Optional[SourcedNumber] = None
    accuracy_um: Optional[SourcedNumber] = None
    equipment_accuracy_um: Optional[SourcedNumber] = Field(
        default=None,
        description="후보 문서(장비)에서 실제로 확인된 정확도. accuracy_um은 사용자가 요구사항에서 "
        "명시하면 SpecGenerator가 그 값으로 고정하는 필드(요구값 보호)이므로, 요구값과 장비의 "
        "실측값을 혼동하지 않도록 별도 필드에 둔다.",
    )
    repeatability_um: Optional[SourcedNumber] = None
    reproducibility_um: Optional[SourcedNumber] = None
    linearity: Optional[SourcedNumber] = None
    measurement_speed: Optional[SourcedNumber] = None
    sampling_rate: Optional[SourcedNumber] = None


class SpatialPerformance(BaseModel):
    """3D/2D 검사 장비를 고려해 Measurement Performance와 분리 유지 (요청서 7절)."""

    x_range: Optional[SourcedNumber] = None
    y_range: Optional[SourcedNumber] = None
    z_range: Optional[SourcedNumber] = None
    x_resolution_um: Optional[SourcedNumber] = None
    y_resolution_um: Optional[SourcedNumber] = None
    z_resolution_um: Optional[SourcedNumber] = None
    fov_mm: Optional[SourcedNumber] = None
    working_distance: Optional[SourcedNumber] = None
    pixel_size: Optional[SourcedNumber] = None
    point_spacing: Optional[SourcedNumber] = None
    profile_spacing: Optional[SourcedNumber] = None
    sampling_interval_um: Optional[SourcedNumber] = None


class InspectionPerformance(BaseModel):
    scan_speed_mm_s: Optional[SourcedNumber] = None
    line_speed_mm_s: Optional[SourcedNumber] = None
    measurement_speed: Optional[SourcedNumber] = None
    tact_time_s: Optional[SourcedNumber] = None
    inspection_width_mm: Optional[SourcedNumber] = None


class DefectDetection(BaseModel):
    defect_detection: Optional[bool] = Field(default=None, description="결함 검사 기능 지원 여부")
    minimum_defect_size_um: Optional[SourcedNumber] = None
    equipment_minimum_defect_size_um: Optional[SourcedNumber] = Field(
        default=None,
        description="후보 문서(장비)에서 실제로 확인된 최소 검출 결함 크기. minimum_defect_size_um은 "
        "사용자가 요구사항에서 명시하면 SpecGenerator가 그 값으로 고정하는 필드(요구값 보호)이므로, "
        "요구값과 장비의 실측값을 혼동하지 않도록 별도 필드에 둔다(measurement_performance."
        "equipment_accuracy_um과 동일한 원칙).",
    )
    defect_types: List[str] = Field(
        default_factory=list,
        description="실제 사양서/요구사항에서 확인된 결함 종류만 (예: pinhole, scratch, crack, "
        "contamination, coating_defect, particle) — AI가 임의로 추가하지 않는다",
    )
    detection_resolution: Optional[SourcedNumber] = None
    defect_detection_accuracy: Optional[SourcedNumber] = None
    false_positive_rate: Optional[SourcedNumber] = None
    false_negative_rate: Optional[SourcedNumber] = None
    classification: Optional[bool] = Field(default=None, description="결함 자동 분류 기능 지원 여부")


class OpticalSystem(BaseModel):
    """광학식이 아닌 장비(접촉식 등)에는 해당 없는 필드가 많으므로 전부 Optional."""

    light_source: Optional[str] = None
    wavelength: Optional[str] = None
    spectral_range: Optional[str] = None
    optical_method: Optional[str] = None
    interferometry: Optional[bool] = None
    reflectometry: Optional[bool] = None
    oct: Optional[bool] = None
    laser: Optional[bool] = None
    sensor_type: Optional[str] = None
    camera: Optional[str] = None
    camera_resolution: Optional[str] = None
    lens: Optional[str] = None
    objective: Optional[str] = None
    working_distance: Optional[str] = None


class SystemConfig(BaseModel):
    automation_level: Optional[str] = None
    stage: Optional[str] = None
    motion_system: Optional[str] = None
    sensor: Optional[str] = None
    controller: Optional[str] = None
    pc: Optional[str] = None
    software: Optional[str] = None
    display: Optional[str] = None
    power: Optional[str] = None
    air: Optional[str] = None
    cooling: Optional[str] = None
    mechanical_configuration: Optional[str] = None
    data_output: Optional[str] = None


class Interfaces(BaseModel):
    """존재하지 않는 인터페이스는 None(=UNKNOWN으로 렌더링)으로 둔다."""

    plc: Optional[bool] = None
    mes: Optional[bool] = None
    opc_ua: Optional[bool] = None
    ethernet_ip: Optional[bool] = None
    profinet: Optional[bool] = None
    modbus: Optional[bool] = None
    ethernet: Optional[bool] = None
    digital_io: Optional[bool] = None
    analog_io: Optional[bool] = None
    api: Optional[bool] = None
    data_format: Optional[str] = None
    data_storage: Optional[str] = None
    network: Optional[str] = None
    other_interfaces: List[str] = Field(default_factory=list)


class Environment(BaseModel):
    operating_temperature: Optional[str] = None
    storage_temperature: Optional[str] = None
    humidity: Optional[str] = None
    installation_space: Optional[str] = None
    power: Optional[str] = None
    vibration_requirement: Optional[str] = None
    dust: Optional[str] = None
    installation_environment: Optional[str] = None
    clean_room: Optional[str] = None


class Safety(BaseModel):
    safety_standard: Optional[str] = None
    laser_class: Optional[str] = None
    interlock: Optional[bool] = None
    emergency_stop: Optional[bool] = None
    safety_sensor: Optional[bool] = None
    protective_cover: Optional[bool] = None


class SpecificationSchema(BaseModel):
    equipment: Equipment = Field(default_factory=Equipment)
    inspection_target: InspectionTarget = Field(default_factory=InspectionTarget)
    inspection_items: List[str] = Field(default_factory=list)
    inspection_requirements: InspectionRequirements = Field(default_factory=InspectionRequirements)
    measurement_performance: MeasurementPerformance = Field(default_factory=MeasurementPerformance)
    spatial_performance: SpatialPerformance = Field(default_factory=SpatialPerformance)
    inspection_performance: InspectionPerformance = Field(default_factory=InspectionPerformance)
    defect_detection: DefectDetection = Field(default_factory=DefectDetection)
    optical_system: OpticalSystem = Field(default_factory=OpticalSystem)
    system: SystemConfig = Field(default_factory=SystemConfig)
    interfaces: Interfaces = Field(default_factory=Interfaces)
    environment: Environment = Field(default_factory=Environment)
    safety: Safety = Field(default_factory=Safety)
    notes: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list, description="이 사양서 생성에 참고한 문서 파일명 목록")
    primary_sources: List[str] = Field(
        default_factory=list,
        description="검색된 문서 전체(sources)가 아니라, 최종 사양의 각 필드값을 실제로 뒷받침하는"
        "(VERIFIED로 확인되었거나 후보 선정에 쓰인) 문서만 모은 목록 — UI에 우선 노출한다.",
    )
    needs_confirmation: List[str] = Field(
        default_factory=list,
        description="INFERRED/UNKNOWN으로 채워져 사용자 확인이 필요한 필드의 dotted path 목록",
    )


# ==========================================
# Validation
# ==========================================
class ValidationIssue(BaseModel):
    level: Literal["error", "warning", "info"]
    field: str
    message: str


class ValidationResult(BaseModel):
    is_valid: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)


# ==========================================
# Requirement Compliance — Requirement과 Specification의 필드별 비교 결과
# (SpecificationSchema에는 저장하지 않는다 — 렌더링/검증 시점에 계산되는 파생 정보.
#  agent/spec_validator.py의 build_compliance_report()가 생성한다.)
# ==========================================
class ComplianceRecord(BaseModel):
    item: str
    unit: Optional[str] = None
    requirement: Optional[float] = None
    specification: Optional[float] = None
    operator: Optional[Operator] = None
    result: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    reason: str = ""
    source: Optional[SourceRef] = None
    hard: bool = Field(default=False, description="Hard Requirement 항목이면 True (요청서 16절)")


# ==========================================
# Candidate Equipment — RAG 검색 결과를 Specification Generator에 바로 넘기지 않고,
# 후보 장비 단위로 그룹화 + 비교 + 랭킹한 결과 (요청서 13~18절).
# SpecificationSchema에는 저장하지 않는다 — 사용자가 후보를 선택하면 그 결과(주로
# VERIFIED 근거)가 SpecificationSchema 생성의 입력으로만 쓰이는 파생/중간 산출물이다.
# ==========================================
class CandidateFieldMatch(BaseModel):
    """후보 장비 하나가 Requirement 항목 하나를 만족하는지에 대한 판단 (agent.candidate_matcher가 생성)."""

    item: str = Field(description="사람이 읽을 항목명 (예: Accuracy)")
    field_key: str = Field(description="요구사항 dotted path (예: accuracy, target.width_mm)")
    hard: bool = False
    requirement_value: Optional[float] = None
    requirement_unit: Optional[str] = None
    operator: Optional[Operator] = None
    found_value: Optional[float] = None
    found_min: Optional[float] = Field(
        default=None, description="item이 범위(예: Measurement Range)일 때만 채움 — found_value는 그 범위의 max."
    )
    found_unit: Optional[str] = None
    requirement_text: Optional[str] = Field(
        default=None,
        description="범주형(문자열) 요구값 — 예: Inline/Offline, Non-contact/Contact, OCT. "
        "숫자 필드(requirement_value)로 표현할 수 없는 항목(Inspection Mode 등)에 쓴다.",
    )
    found_text: Optional[str] = Field(
        default=None, description="범주형(문자열) 후보 확인값. found_value(숫자)와 대칭되는 문자열 버전."
    )
    result: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    evidence_text: Optional[str] = Field(default=None, description="근거로 삼은 원문 발췌")
    source: Optional[SourceRef] = None


class CandidateEquipment(BaseModel):
    """RAG 검색 결과를 문서(장비) 단위로 그룹화한 후보 하나."""

    candidate_id: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    source_document: str
    matches: List[CandidateFieldMatch] = Field(default_factory=list)
    match_score: float = Field(default=0.0, ge=0.0, le=100.0)
    hard_requirements_pass: bool = Field(
        default=False, description="Hard Requirement 항목 중 FAIL이 하나도 없으면 True (UNKNOWN은 FAIL로 치지 않음)"
    )
    unknown_count: int = 0
    fail_count: int = 0
    pass_count: int = 0
