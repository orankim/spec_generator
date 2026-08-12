"""
전극 검사기 사양서 자동 생성 Agent의 Pydantic 스키마 정의.

Requirement(사용자 요구사항)와 Specification(최종 장비 사양서)을
서로 다른 모델로 분리한다 (기획안 6절). 수치/성능 계열 필드는
SourcedNumber로 감싸 근거(source)를 추적하고, 서술/분류 계열 필드는
일반 값으로 둔다 — 스키마 크기와 근거 추적 필요성 사이의 실용적 절충이며
자세한 이유는 IMPLEMENTATION_PLAN.md 2절에 기록되어 있다.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal["document", "user_requirement", "inferred", "default"]


class SourcedNumber(BaseModel):
    """근거가 있는 수치 필드. 문서에서 못 찾았고 사용자도 명시하지 않았다면 value=None으로 남긴다."""

    value: Optional[float] = None
    unit: Optional[str] = None
    source_type: Optional[SourceType] = None
    source: Optional[str] = Field(default=None, description="근거 문서 파일명 등 (source_type=document일 때)")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ==========================================
# Requirement Schema — 사용자가 입력/선택한 "요구사항"
# ==========================================
class RequirementTarget(BaseModel):
    material: Optional[str] = Field(default=None, description="검사 대상 (예: 양극, 음극, 분리막, 전극)")
    product_type: Optional[str] = None
    width_mm: Optional[float] = None
    length_mm: Optional[float] = None
    thickness_range_um: Optional[str] = Field(default=None, description="예: '0~200'")
    substrate: Optional[str] = None


class RequirementSchema(BaseModel):
    raw_text: Optional[str] = Field(default=None, description="사용자가 입력한 원본 자연어 (있는 경우)")
    target: RequirementTarget = Field(default_factory=RequirementTarget)
    inspection_items: List[str] = Field(
        default_factory=list,
        description="예: thickness, surface_defect, profile_3d, coating, edge, other",
    )
    measurement_method: Optional[Literal["non_contact", "contact"]] = None
    measurement_principle: Optional[Literal["laser", "oct", "interferometry", "vision", "other"]] = None
    required_accuracy_um: Optional[float] = None
    required_resolution_um: Optional[float] = None
    minimum_defect_size_um: Optional[float] = None
    scan_speed_requirement: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


# ==========================================
# Specification Schema — 최종 장비 사양서
# ==========================================
class Equipment(BaseModel):
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    measurement_principle: Optional[str] = None


class InspectionTarget(BaseModel):
    material: Optional[str] = None
    product_type: Optional[str] = None
    width_mm: Optional[float] = None
    length_mm: Optional[float] = None
    thickness_um: Optional[float] = None
    substrate: Optional[str] = None
    inspection_direction: Optional[str] = None


class MeasurementPerformance(BaseModel):
    measurement_range: Optional[SourcedNumber] = None
    resolution_um: Optional[SourcedNumber] = None
    accuracy_um: Optional[SourcedNumber] = None
    repeatability_um: Optional[SourcedNumber] = None
    reproducibility_um: Optional[SourcedNumber] = None


class SpatialPerformance(BaseModel):
    fov_mm: Optional[SourcedNumber] = None
    x_resolution_um: Optional[SourcedNumber] = None
    y_resolution_um: Optional[SourcedNumber] = None
    z_resolution_um: Optional[SourcedNumber] = None
    sampling_interval_um: Optional[SourcedNumber] = None


class InspectionPerformance(BaseModel):
    scan_speed_mm_s: Optional[SourcedNumber] = None
    line_speed_mm_s: Optional[SourcedNumber] = None
    measurement_speed: Optional[SourcedNumber] = None
    tact_time_s: Optional[SourcedNumber] = None
    inspection_width_mm: Optional[SourcedNumber] = None


class DefectDetection(BaseModel):
    minimum_defect_size_um: Optional[SourcedNumber] = None
    defect_types: List[str] = Field(default_factory=list)
    defect_detection_accuracy: Optional[SourcedNumber] = None
    false_positive_rate: Optional[SourcedNumber] = None
    false_negative_rate: Optional[SourcedNumber] = None


class OpticalSystem(BaseModel):
    light_source: Optional[str] = None
    wavelength: Optional[str] = None
    optical_method: Optional[str] = None
    sensor_type: Optional[str] = None
    camera_resolution: Optional[str] = None
    objective: Optional[str] = None
    working_distance: Optional[str] = None


class SystemConfig(BaseModel):
    automation_level: Optional[str] = None
    stage: Optional[str] = None
    motion_system: Optional[str] = None
    controller: Optional[str] = None
    software: Optional[str] = None
    data_output: Optional[str] = None


class Interfaces(BaseModel):
    ethernet: Optional[bool] = None
    digital_io: Optional[bool] = None
    plc: Optional[bool] = None
    mes: Optional[bool] = None
    opc_ua: Optional[bool] = None
    other_interfaces: List[str] = Field(default_factory=list)


class Environment(BaseModel):
    operating_temperature: Optional[str] = None
    humidity: Optional[str] = None
    installation_space: Optional[str] = None
    power: Optional[str] = None
    vibration_requirement: Optional[str] = None


class Safety(BaseModel):
    safety_standard: Optional[str] = None
    interlock: Optional[bool] = None
    emergency_stop: Optional[bool] = None


class SpecificationSchema(BaseModel):
    equipment: Equipment = Field(default_factory=Equipment)
    inspection_target: InspectionTarget = Field(default_factory=InspectionTarget)
    inspection_items: List[str] = Field(default_factory=list)
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
    needs_confirmation: List[str] = Field(
        default_factory=list,
        description="inferred/default로 채워져 사용자 확인이 필요한 필드의 dotted path 목록",
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
