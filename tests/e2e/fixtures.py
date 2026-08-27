"""
E2E 테스트용 canned API 응답 빌더.

main.py의 프론트엔드 JS가 그대로 소비할 수 있는 형태를 보장하기 위해, 필드를
손으로 나열한 raw dict를 쓰지 않고 실제 agent.schemas의 Pydantic 모델을 만들어
`.model_dump()`한다 — 스키마가 바뀌면(필드 추가/이름 변경) 이 fixture도 즉시
import 시점에 깨지므로, "실제로 존재하지 않는 필드로 프론트엔드를 속이며 테스트를
통과시키는" 상황을 방지한다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.schemas import (
    CandidateEquipment,
    CandidateEquipmentFact,
    ComplianceRecord,
    Equipment,
    InspectionTarget,
    MeasurementPerformance,
    RequirementRange,
    RequirementSchema,
    RequirementTarget,
    RequirementValue,
    SourcedNumber,
    SourcedRange,
    SourceRef,
    SpecificationSchema,
    ValidationResult,
)


def make_requirement(**overrides: Any) -> Dict[str, Any]:
    """Scenario 2 질문("폭 800mm 이상 ... Inline ... 0~500um ±1um ... 500mm/s 이상 두께 검사기")에
    대응하는 RequirementSchema. overrides로 개별 필드를 덮어써 후속 시나리오(정확도 제거 등)에
    재사용한다."""
    base = dict(
        raw_text="폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, "
        "0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘.",
        target=RequirementTarget(width_mm=800.0, material="전극"),
        inspection_items=["thickness"],
        inline_offline="inline",
        measurement_range=RequirementRange(min=0.0, max=500.0, unit="um"),
        accuracy=RequirementValue(value=1.0, unit="um", operator="<="),
        measurement_speed=RequirementValue(value=500.0, unit="mm/s", operator=">="),
    )
    base.update(overrides)
    req = RequirementSchema(**base)
    req.sync_legacy_fields()
    return req.model_dump()


def make_validation(is_valid: bool = True, questions: Optional[List[str]] = None) -> Dict[str, Any]:
    return ValidationResult(is_valid=is_valid, questions=questions or []).model_dump()


def make_analyze_response(requirement: Optional[Dict[str, Any]] = None, **validation_kwargs) -> Dict[str, Any]:
    return {
        "requirement": requirement if requirement is not None else make_requirement(),
        "validation": make_validation(**validation_kwargs),
    }


def make_update_response(
    requirement: Dict[str, Any],
    changed_summary: List[Dict[str, str]],
    **validation_kwargs,
) -> Dict[str, Any]:
    return {
        "requirement": requirement,
        "validation": make_validation(**validation_kwargs),
        "changed_fields": [],
        "changed_summary": changed_summary,
    }


def _sourced_number(value: float, unit: str, status: str = "VERIFIED", document: str = "SPEC-013.md") -> Dict[str, Any]:
    return SourcedNumber(
        value=value, unit=unit, status=status, source=SourceRef(document=document) if status == "VERIFIED" else None
    ).model_dump()


def _sourced_range(lo: float, hi: float, unit: str, status: str = "VERIFIED", document: str = "SPEC-013.md") -> Dict[str, Any]:
    return SourcedRange(
        min=lo, max=hi, unit=unit, status=status, source=SourceRef(document=document) if status == "VERIFIED" else None
    ).model_dump()


def make_specification(
    name: str = "ThicknessPro TP-800",
    manufacturer: str = "ThicknessPro",
    model: str = "TP-800",
    accuracy_status: str = "VERIFIED",
    include_unknowns: bool = False,
) -> Dict[str, Any]:
    spec = SpecificationSchema(
        equipment=Equipment(name=name, manufacturer=manufacturer, model=model, inline_offline="inline"),
        inspection_target=InspectionTarget(
            material="전극",
            width_mm=800.0,
            equipment_max_width_mm=_sourced_number(1200.0, "mm"),
        ),
        inspection_items=["thickness"],
        measurement_performance=MeasurementPerformance(
            measurement_range_full=_sourced_range(0.0, 500.0, "um"),
            equipment_accuracy_um=_sourced_number(0.8, "um", status=accuracy_status)
            if not include_unknowns
            else SourcedNumber(status="UNKNOWN").model_dump(),
            measurement_speed=_sourced_number(700.0, "mm/s"),
        ),
        sources=["SPEC-013.md"],
        primary_sources=["SPEC-013.md"],
    )
    return spec.model_dump()


def make_hard_requirement_report(scenario: str = "pass") -> List[Dict[str, Any]]:
    """
    scenario:
      - "pass": 모든 Hard Requirement PASS
      - "unknown": FAIL 없이 UNKNOWN 하나 이상 존재(banner: "일부 조건 확인 필요")
      - "fail": FAIL 하나 이상 존재(banner: "요구조건 미충족")
    """
    common = [
        ComplianceRecord(
            item="Width",
            unit="mm",
            requirement=800.0,
            specification=1200.0,
            operator=">=",
            result="PASS",
            reason="장비 대응 폭 1200mm >= 요구 800mm → PASS",
            source=SourceRef(document="SPEC-013.md"),
            hard=True,
        ),
        ComplianceRecord(
            item="Inspection Mode (Inline/Offline)",
            requirement=None,
            specification=None,
            result="PASS",
            reason="Inline 지원 확인 → PASS",
            source=SourceRef(document="SPEC-013.md"),
            hard=True,
        ),
    ]
    if scenario == "pass":
        common.append(
            ComplianceRecord(
                item="Accuracy",
                unit="um",
                requirement=1.0,
                specification=0.8,
                operator="<=",
                result="PASS",
                reason="장비 정확도 0.8um <= 요구 1.0um → PASS",
                source=SourceRef(document="SPEC-013.md"),
                hard=True,
            )
        )
    elif scenario == "unknown":
        common.append(
            ComplianceRecord(
                item="Accuracy",
                unit="um",
                requirement=1.0,
                specification=None,
                operator="<=",
                result="UNKNOWN",
                reason="사양서에서 정확도 값을 확인할 수 없음 → UNKNOWN",
                hard=True,
            )
        )
    elif scenario == "fail":
        common.append(
            ComplianceRecord(
                item="Accuracy",
                unit="um",
                requirement=1.0,
                specification=2.5,
                operator="<=",
                result="FAIL",
                reason="장비 정확도 2.5um > 요구 1.0um → FAIL",
                source=SourceRef(document="SPEC-013.md"),
                hard=True,
            )
        )
    return [r.model_dump() for r in common]


def make_candidate(status: str = "PASS") -> Dict[str, Any]:
    return CandidateEquipment(
        candidate_id="cand-1",
        manufacturer="ThicknessPro",
        model="TP-800",
        source_document="SPEC-013.md",
        status=status,
        hard_requirements_pass=(status != "FAIL"),
        equipment_fact=CandidateEquipmentFact(
            equipment_type="Thickness Inspection",
            inline_offline="inline",
            measurement_method="non_contact",
            width_mm=1200.0,
            range_min=0.0,
            range_max=800.0,
            range_unit="um",
            accuracy_value=0.8,
            accuracy_unit="um",
            speed_value=800.0,
            speed_unit="mm/s",
        ),
    ).model_dump()


def make_generate_spec_response(
    scenario: str = "pass",
    retrieved_sources_count: int = 3,
    include_candidate: bool = True,
) -> Dict[str, Any]:
    candidate_status = {"pass": "PASS", "unknown": "PARTIAL", "fail": "FAIL"}[scenario]
    return {
        "specification": make_specification(include_unknowns=(scenario == "unknown")),
        "validation": make_validation(),
        "retrieved_sources": [
            {"source": "SPEC-013.md", "excerpt": "Thickness Inspection ..."} for _ in range(retrieved_sources_count)
        ],
        "hard_requirement_report": make_hard_requirement_report(scenario),
        "chosen_candidate": make_candidate(candidate_status) if include_candidate else None,
        "recommendation_reasons": [],
        "unconfirmed_items": [],
        "comparison_table": [],
    }


def make_build_candidate_markdown_response(file_name: str = "electrode_inspection_candidate_test1234.md") -> Dict[str, Any]:
    return {
        "status": "success",
        "file_name": file_name,
        "download_url": f"/api/download/{file_name}",
    }
