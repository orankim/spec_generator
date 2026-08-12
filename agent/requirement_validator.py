"""
RequirementValidator — LLM이 값을 추측하지 못하도록, 부족한 정보를
순수 Python 규칙으로 탐지하고 사용자에게 물어볼 질문을 만든다.
(기획안 8절: "AI가 추측해서 값을 채우지 않도록 한다")
"""
from __future__ import annotations

from .schemas import RequirementSchema, ValidationResult


def validate_requirement(requirement: RequirementSchema) -> ValidationResult:
    missing_fields: list[str] = []
    questions: list[str] = []

    if not requirement.target.material:
        missing_fields.append("target.material")
        questions.append("검사 대상이 무엇인가요? (예: 양극, 음극, 분리막, 전극 전반)")

    if requirement.target.width_mm is None:
        missing_fields.append("target.width_mm")
        questions.append("검사 대상의 폭(width, mm)은 얼마인가요?")

    if not requirement.inspection_items:
        missing_fields.append("inspection_items")
        questions.append("어떤 항목을 검사해야 하나요? (예: 두께, 표면 결함, 3D 프로파일, 코팅)")

    items = set(requirement.inspection_items)

    # 두께 검사를 요청했다면, 두께 범위와 정확도가 있어야 사양을 좁힐 수 있다.
    if "thickness" in items:
        if requirement.target.thickness_range_um is None:
            missing_fields.append("target.thickness_range_um")
            questions.append("검사 대상 전극의 두께 범위는 어떻게 되나요? (예: 0~200um)")
        if requirement.required_accuracy_um is None:
            missing_fields.append("required_accuracy_um")
            questions.append("요구되는 두께 측정 정확도는 얼마인가요? (um 단위)")

    # 표면 결함/3D 프로파일 검사를 요청했다면, 최소 검출 결함 크기가 있어야 한다.
    if items & {"surface_defect", "profile_3d"}:
        if requirement.minimum_defect_size_um is None:
            missing_fields.append("minimum_defect_size_um")
            questions.append("최소 검출해야 하는 결함(또는 형상) 크기는 얼마인가요? (um 단위)")

    # 코팅 검사를 요청했다면, 요구 정확도가 있어야 한다.
    if "coating" in items and requirement.required_accuracy_um is None and "required_accuracy_um" not in missing_fields:
        missing_fields.append("required_accuracy_um")
        questions.append("요구되는 코팅 두께 측정 정확도는 얼마인가요? (um 단위)")

    if requirement.measurement_method is None:
        # 필수는 아니지만 있으면 검색/생성 정확도가 크게 올라가므로 안내성 질문으로 추가
        # (missing_fields에는 넣지 않아 is_valid 판정에는 영향을 주지 않는다)
        questions.append("측정 방식은 비접촉(non-contact)과 접촉(contact) 중 무엇을 선호하시나요? (선택 사항)")

    return ValidationResult(
        is_valid=len(missing_fields) == 0,
        missing_fields=missing_fields,
        questions=questions,
    )
