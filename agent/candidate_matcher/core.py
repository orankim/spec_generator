"""
CandidateMatcher — RAG 검색 결과(retrieved_docs)를 문서(장비) 단위로 그룹화하고,
측정 범위/정확도/최소 검출 결함 크기 같은 hard requirement를 실제 원문에서 추출해
agent.units의 순수 비교 함수(evaluate_hard_requirements/range_covers)로 PASS/FAIL을
판정한다.

핵심 원칙: LLM은 이 판정에 전혀 관여하지 않는다. 이미 agent.spec_retriever가
retrieved_docs를 만드는 과정에서 range_boost/identity_chunk 로직으로 각 후보 문서의
관련 chunk를 모아 놓았으므로, 여기서 벡터 DB를 다시 스캔하지 않고 그 결과를 그대로
입력으로 받는다(중복 구현 방지) — 평가에 필요한 chunk가 retrieved_docs에 없으면
evaluate_hard_requirements가 UNKNOWN으로 정직하게 표시한다.

이 파일은 build_candidates() 하나만 담당하는 orchestrator다 — 실제 문서 파싱은
extraction.py, hard requirement 정규화는 hard_requirements.py, thickness/coating
판정은 inspection_items.py, 마지막 근접 중복 탐지는 ranking.py에 있다(agent/
candidate_matcher/__init__.py 참고).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from langchain_core.documents import Document

from .. import categorical_match, units
from ..schemas import CandidateEquipment, CandidateEquipmentFact, CandidateFieldMatch, RequirementSchema
from ..spec_retriever import source_label
from .extraction import _extract_candidate_fact
from .hard_requirements import (
    _required_accuracy,
    _required_defect_size,
    _required_range,
    _required_speed,
    _required_width,
    _source_ref,
)
from .inspection_items import _INSPECTION_ITEM_DEFECT_KEYWORDS, _INSPECTION_ITEM_LABELS, _coating_evidence, _thickness_evidence
from .ranking import _annotate_near_duplicates

def build_candidates(requirement: RequirementSchema, retrieved_docs: List[Document]) -> List[CandidateEquipment]:
    """
    retrieved_docs를 문서(장비) 단위로 그룹화하고, 각 후보의 측정 범위/정확도를
    hard requirement로 PASS/FAIL 판정한다 — "LLM이 PASS/FAIL을 임의로 판단해서는
    안 된다"는 원칙에 따라 agent.units.evaluate_hard_requirements를 그대로 재사용한다.
    """
    by_source: Dict[str, List[Document]] = defaultdict(list)
    for doc in retrieved_docs:
        by_source[source_label(doc)].append(doc)

    required_range = _required_range(requirement)
    required_accuracy = _required_accuracy(requirement)
    required_defect_size = _required_defect_size(requirement)
    required_width = _required_width(requirement)
    required_speed = _required_speed(requirement)

    candidates: List[CandidateEquipment] = []
    for idx, (source, docs) in enumerate(sorted(by_source.items()), start=1):
        fact = _extract_candidate_fact(docs)
        matches: List[CandidateFieldMatch] = []

        if required_range is not None:
            candidate_range = fact.range
            try:
                ok, _reasons = units.evaluate_hard_requirements(required_range=required_range, candidate_range=candidate_range)
            except units.UnitError:
                ok, candidate_range = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_range is None else "FAIL")
            req_disp = f"{required_range[0]:g}~{required_range[1]:g} {required_range[2]}"
            spec_disp = f"{candidate_range[0]:g}~{candidate_range[1]:g} {candidate_range[2]}" if candidate_range else None
            margin_val = (candidate_range[1] - required_range[1]) if (result == "PASS" and candidate_range) else None
            margin_disp = f"+{margin_val:g} {required_range[2]}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {required_range[2]}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Range",
                    field_key="measurement_range",
                    hard=True,
                    requirement_value=required_range[1],
                    requirement_unit=required_range[2],
                    operator="<=",
                    found_value=candidate_range[1] if candidate_range else None,
                    found_min=candidate_range[0] if candidate_range else None,
                    found_unit=candidate_range[2] if candidate_range else None,
                    result=result,
                    evidence_text=fact.range_text,
                    source=_source_ref(fact.range_doc) if fact.range_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_accuracy is not None:
            candidate_accuracy = fact.accuracy
            req_value, req_unit, operator = required_accuracy
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_accuracy, candidate_accuracy=candidate_accuracy
                )
            except units.UnitError:
                ok, candidate_accuracy = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_accuracy is None else "FAIL")
            req_disp = f"{operator} {req_value:g} {req_unit}"
            spec_disp = f"±{candidate_accuracy[0]:g} {candidate_accuracy[1]}" if candidate_accuracy else None
            margin_val = (req_value - candidate_accuracy[0]) if (result == "PASS" and candidate_accuracy) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Accuracy",
                    field_key="accuracy",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_accuracy[0] if candidate_accuracy else None,
                    found_unit=candidate_accuracy[1] if candidate_accuracy else None,
                    result=result,
                    evidence_text=fact.accuracy_text,
                    source=_source_ref(fact.accuracy_doc) if fact.accuracy_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_defect_size is not None:
            candidate_defect_size = fact.defect_size
            req_value, req_unit, operator = required_defect_size
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_defect_size, candidate_accuracy=candidate_defect_size
                )
            except units.UnitError:
                ok, candidate_defect_size = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_defect_size is None else "FAIL")
            req_disp = f"{operator} {req_value:g} {req_unit}"
            spec_disp = f"{candidate_defect_size[0]:g} {candidate_defect_size[1]}" if candidate_defect_size else None
            margin_val = (req_value - candidate_defect_size[0]) if (result == "PASS" and candidate_defect_size) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Minimum Defect Size",
                    field_key="minimum_defect_size",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_defect_size[0] if candidate_defect_size else None,
                    found_unit=candidate_defect_size[1] if candidate_defect_size else None,
                    result=result,
                    evidence_text=fact.defect_size_text,
                    source=_source_ref(fact.defect_size_doc) if fact.defect_size_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_width is not None:
            req_value, req_unit, operator = required_width
            candidate_width = (fact.width_mm, "mm") if fact.width_mm is not None else None
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_width, candidate_accuracy=candidate_width
                )
            except units.UnitError:
                ok, candidate_width = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_width is None else "FAIL")
            req_disp = f">= {req_value:g} {req_unit}"
            spec_disp = f"{candidate_width[0]:g} {candidate_width[1]}" if candidate_width else None
            margin_val = (candidate_width[0] - req_value) if (result == "PASS" and candidate_width) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Width",
                    field_key="width",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_width[0] if candidate_width else None,
                    found_unit=candidate_width[1] if candidate_width else None,
                    result=result,
                    evidence_text=fact.width_mm_text,
                    source=_source_ref(fact.width_mm_doc) if fact.width_mm_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if required_speed is not None:
            req_value, req_unit, operator = required_speed
            candidate_speed = fact.speed
            try:
                ok, _reasons = units.evaluate_hard_requirements(
                    required_accuracy=required_speed, candidate_accuracy=candidate_speed
                )
            except units.UnitError:
                ok, candidate_speed = False, None
            result = "PASS" if ok else ("UNKNOWN" if candidate_speed is None else "FAIL")
            req_disp = f">= {req_value:g} {req_unit}"
            spec_disp = f"{candidate_speed[0]:g} {candidate_speed[1]}" if candidate_speed else None
            margin_val = (candidate_speed[0] - req_value) if (result == "PASS" and candidate_speed) else None
            margin_disp = f"+{margin_val:g} {req_unit}" if (margin_val is not None and margin_val > 0) else (f"{margin_val:g} {req_unit}" if margin_val is not None else None)
            matches.append(
                CandidateFieldMatch(
                    item="Speed",
                    field_key="speed",
                    hard=True,
                    requirement_value=req_value,
                    requirement_unit=req_unit,
                    operator=operator,
                    found_value=candidate_speed[0] if candidate_speed else None,
                    found_unit=candidate_speed[1] if candidate_speed else None,
                    result=result,
                    evidence_text=fact.speed_text,
                    source=_source_ref(fact.speed_doc) if fact.speed_doc else None,
                    margin=margin_val,
                    margin_display=margin_disp,
                    user_requirement_display=req_disp,
                    equipment_spec_display=spec_disp,
                )
            )

        if requirement.inline_offline is not None:
            candidate_mode = fact.inspection_mode
            if candidate_mode is None:
                mode_result = "UNKNOWN"
            elif candidate_mode == requirement.inline_offline:
                mode_result = "PASS"
            else:
                mode_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Inspection Mode",
                    field_key="inline_offline",
                    hard=True,
                    requirement_text=requirement.inline_offline,
                    found_text=candidate_mode,
                    result=mode_result,
                    evidence_text=fact.inspection_mode_text,
                    source=_source_ref(fact.inspection_mode_doc) if fact.inspection_mode_doc else None,
                    user_requirement_display=requirement.inline_offline.capitalize(),
                    equipment_spec_display=candidate_mode.capitalize() if candidate_mode else None,
                )
            )

        if requirement.measurement_method is not None:
            candidate_method = fact.measurement_method
            if candidate_method is None:
                method_result = "UNKNOWN"
            elif candidate_method == requirement.measurement_method:
                method_result = "PASS"
            else:
                method_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Method",
                    field_key="measurement_method",
                    hard=True,
                    requirement_text=requirement.measurement_method,
                    found_text=candidate_method,
                    result=method_result,
                    evidence_text=fact.measurement_method_text,
                    source=_source_ref(fact.measurement_method_doc) if fact.measurement_method_doc else None,
                    user_requirement_display=requirement.measurement_method.replace("_", "-").capitalize(),
                    equipment_spec_display=candidate_method.replace("_", "-").capitalize() if candidate_method else None,
                )
            )

        if requirement.measurement_principle is not None:
            required_principle = (
                categorical_match.extract_measurement_principle(requirement.measurement_principle)
                or requirement.measurement_principle
            )
            candidate_principle = fact.measurement_principle
            if candidate_principle is None:
                principle_result = "UNKNOWN"
            elif candidate_principle == required_principle:
                principle_result = "PASS"
            else:
                principle_result = "FAIL"
            matches.append(
                CandidateFieldMatch(
                    item="Measurement Principle",
                    field_key="measurement_principle",
                    hard=True,
                    requirement_text=required_principle,
                    found_text=candidate_principle,
                    result=principle_result,
                    evidence_text=fact.measurement_principle_text,
                    source=_source_ref(fact.measurement_principle_doc) if fact.measurement_principle_doc else None,
                    user_requirement_display=required_principle,
                    equipment_spec_display=candidate_principle if candidate_principle else None,
                )
            )

        for item in requirement.inspection_items:
            label = _INSPECTION_ITEM_LABELS.get(item, item.replace("_", " ").title())
            if item == "thickness":
                if fact.thickness_not_supported:
                    item_result = "FAIL"
                    found_text = "Not Supported"
                    evidence = "Thickness Measurement: Not Supported"
                    source_doc = fact.thickness_not_supported_doc
                else:
                    hit = _thickness_evidence(fact)
                    if hit is None:
                        item_result, found_text, evidence, source_doc = "UNKNOWN", None, None, None
                    else:
                        item_result = "PASS"
                        evidence_text, evidence_doc = hit
                        if fact.range is not None:
                            found_text = fact.range_text
                            evidence = f"{fact.range_text} (근거: {evidence_text})"
                            source_doc = fact.range_doc
                        else:
                            found_text = evidence_text
                            evidence = evidence_text
                            source_doc = evidence_doc
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=evidence,
                        source=_source_ref(source_doc) if source_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            if item == "coating":
                item_result, found_text, evidence, source_doc = _coating_evidence(fact, docs)
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=evidence,
                        source=_source_ref(source_doc) if source_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            if item in categorical_match.INSPECTION_ITEM_CAPABILITY_KEYWORDS:
                capability_doc = fact.equipment_type_doc or fact.measurement_principle_doc
                capability_text = " ".join(
                    t for t in (fact.equipment_type_text, fact.measurement_principle_text) if t
                )
                capability = categorical_match.match_inspection_item_capability(item, capability_text)
                if capability is True:
                    item_result, found_text = "PASS", capability_text
                elif capability is False:
                    item_result, found_text = "FAIL", capability_text
                else:
                    item_result, found_text, capability_doc = "UNKNOWN", None, None
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        found_text=found_text,
                        result=item_result,
                        evidence_text=capability_text or None,
                        source=_source_ref(capability_doc) if capability_doc else None,
                        user_requirement_display=label,
                        equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                    )
                )
                continue
            keywords = _INSPECTION_ITEM_DEFECT_KEYWORDS.get(item)
            if keywords is None:
                matches.append(
                    CandidateFieldMatch(
                        item=label,
                        field_key=f"inspection_item_{item}",
                        hard=True,
                        requirement_text=item,
                        result="UNKNOWN",
                        user_requirement_display=label,
                    )
                )
                continue
            if fact.defect_inspection_not_supported:
                item_result = "FAIL"
                found_text = "Not Supported"
                evidence = "Defect Inspection: Not Supported"
                source_doc = fact.defect_inspection_not_supported_doc
            elif fact.defect_types_text is not None:
                defect_types_lower = fact.defect_types_text.lower()
                item_result = "PASS" if any(kw in defect_types_lower for kw in keywords) else "FAIL"
                found_text = fact.defect_types_text
                evidence = f"Defect Types: {fact.defect_types_text}"
                source_doc = fact.defect_types_doc
            else:
                item_result = "UNKNOWN"
                found_text = None
                evidence = None
                source_doc = None
            matches.append(
                CandidateFieldMatch(
                    item=label,
                    field_key=f"inspection_item_{item}",
                    hard=True,
                    requirement_text=item,
                    found_text=found_text,
                    result=item_result,
                    evidence_text=evidence,
                    source=_source_ref(source_doc) if source_doc else None,
                    user_requirement_display=label,
                    equipment_spec_display=found_text or ("지원함" if item_result == "PASS" else ("미지원" if item_result == "FAIL" else None)),
                )
            )

        pass_count = sum(1 for m in matches if m.result == "PASS")
        fail_count = sum(1 for m in matches if m.result == "FAIL")
        unknown_count = sum(1 for m in matches if m.result == "UNKNOWN")
        hard_requirements_pass = fail_count == 0 and unknown_count == 0
        match_score = 100.0 * pass_count / len(matches) if matches else 0.0

        total_margin = sum(m.margin for m in matches if m.margin is not None)
        doc_scores = [doc.metadata.get("score") for doc in docs if doc.metadata.get("score") is not None]
        rag_sim_score = float(sum(doc_scores) / len(doc_scores)) if doc_scores else None

        recommendation_reasons = []
        unconfirmed_items = []
        for m in matches:
            if m.result == "PASS":
                if m.margin_display:
                    recommendation_reasons.append(f"✓ {m.item}: 요구 {m.user_requirement_display}, 장비 {m.equipment_spec_display} ({m.margin_display})")
                elif m.user_requirement_display and m.equipment_spec_display:
                    recommendation_reasons.append(f"✓ {m.item}: 요구 {m.user_requirement_display}, 장비 {m.equipment_spec_display}")
                else:
                    recommendation_reasons.append(f"✓ {m.item}: {m.user_requirement_display or m.item} 지원 확인")
            elif m.result == "UNKNOWN":
                unconfirmed_items.append(f"? {m.item}: 장비 사양서에서 확인하지 못함")

        if fail_count == 0 and unknown_count == 0:
            status = "PASS"
        elif fail_count == 0:
            status = "PARTIAL"
        else:
            status = "FAIL"

        # Markdown 사양서 내보내기 등에 쓰는 전체 사양 스냅샷 — 위 matches와 달리
        # 사용자가 그 항목을 요구조건으로 묻지 않았어도 문서에 실제로 있으면 채운다
        # (요청서: "추천된 장비의 정보를 기반으로 Markdown 사양서를 생성"). 근거
        # 없는 필드는 그대로 None/빈 리스트로 둔다 — 추측해서 채우지 않는다.
        equipment_fact = CandidateEquipmentFact(
            equipment_type=fact.equipment_type_text,
            measurement_principle=fact.measurement_principle,
            inline_offline=fact.inspection_mode,
            measurement_method=fact.measurement_method,
            width_mm=fact.width_mm,
            range_min=fact.range[0] if fact.range else None,
            range_max=fact.range[1] if fact.range else None,
            range_unit=fact.range[2] if fact.range else None,
            accuracy_value=fact.accuracy[0] if fact.accuracy else None,
            accuracy_unit=fact.accuracy[1] if fact.accuracy else None,
            resolution_value=fact.resolution[0] if fact.resolution else None,
            resolution_unit=fact.resolution[1] if fact.resolution else None,
            speed_value=fact.speed[0] if fact.speed else None,
            speed_unit=fact.speed[1] if fact.speed else None,
            defect_types=(
                [t.strip() for t in fact.defect_types_text.split(",") if t.strip()]
                if fact.defect_types_text and not fact.defect_inspection_not_supported
                else []
            ),
            min_defect_size_value=fact.defect_size[0] if fact.defect_size else None,
            min_defect_size_unit=fact.defect_size[1] if fact.defect_size else None,
            x_range_min=fact.x_range[0] if fact.x_range else None,
            x_range_max=fact.x_range[1] if fact.x_range else None,
            x_range_unit=fact.x_range[2] if fact.x_range else None,
            y_range_min=fact.y_range[0] if fact.y_range else None,
            y_range_max=fact.y_range[1] if fact.y_range else None,
            y_range_unit=fact.y_range[2] if fact.y_range else None,
            # Z Range/Resolution: "## Spatial Performance" 절에 명시적으로 있으면
            # 그 값을 쓰고, 없으면 "## Measurement Performance"의 주 측정 범위/
            # 해상도(fact.range/fact.resolution)를 그대로 재사용한다 — 이 corpus의
            # 장비 대부분은 두께/깊이(Z축)를 측정하는 것이 곧 "주" 측정 성능이므로
            # 같은 숫자를 "## Spatial Performance"에도 사양서 원문에 중복으로
            # 적어 넣을 필요가 없다(sample_specs 파일에 문자 그대로 중복 텍스트를
            # 추가하면 heading 기반 RAG chunking이 새 chunk를 만들어, fake-hash
            # 임베딩을 쓰는 결정론적 테스트의 검색 순위가 흔들리는 부작용이 실제로
            # 있었다 — Z Range/Resolution은 코드에서만 매핑하고 원문은 건드리지
            # 않는 것으로 정책을 바꿨다).
            z_range_min=fact.z_range[0] if fact.z_range else (fact.range[0] if fact.range else None),
            z_range_max=fact.z_range[1] if fact.z_range else (fact.range[1] if fact.range else None),
            z_range_unit=fact.z_range[2] if fact.z_range else (fact.range[2] if fact.range else None),
            x_resolution_value=fact.x_resolution[0] if fact.x_resolution else None,
            x_resolution_unit=fact.x_resolution[1] if fact.x_resolution else None,
            y_resolution_value=fact.y_resolution[0] if fact.y_resolution else None,
            y_resolution_unit=fact.y_resolution[1] if fact.y_resolution else None,
            z_resolution_value=fact.z_resolution[0] if fact.z_resolution else (fact.resolution[0] if fact.resolution else None),
            z_resolution_unit=fact.z_resolution[1] if fact.z_resolution else (fact.resolution[1] if fact.resolution else None),
            fov_display=fact.fov_display,
            working_distance_value=fact.working_distance[0] if fact.working_distance else None,
            working_distance_unit=fact.working_distance[1] if fact.working_distance else None,
            pixel_size_value=fact.pixel_size[0] if fact.pixel_size else None,
            pixel_size_unit=fact.pixel_size[1] if fact.pixel_size else None,
        )

        candidates.append(
            CandidateEquipment(
                candidate_id=f"cand-{idx}",
                manufacturer=fact.manufacturer,
                model=fact.model,
                source_document=source,
                matches=matches,
                equipment_fact=equipment_fact,
                match_score=match_score,
                hard_requirements_pass=hard_requirements_pass,
                unknown_count=unknown_count,
                fail_count=fail_count,
                pass_count=pass_count,
                total_margin=total_margin,
                rag_similarity_score=rag_sim_score,
                recommendation_reasons=recommendation_reasons,
                unconfirmed_items=unconfirmed_items,
                status=status,
            )
        )

    _annotate_near_duplicates(candidates)
    return candidates
