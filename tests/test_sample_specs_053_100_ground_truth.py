"""
sample_specs/SPEC-053.md ~ SPEC-100.md(SPEC 100개 확장 Phase 1, 신규 48개)이
tests/ground_truth_data_053_100.py의 GROUND_TRUTH_053_100과 정확히 일치하는지
자동 검증한다. tests/test_sample_specs_ground_truth.py(SPEC-011~050용)와 완전히
동일한 방법론을 SPEC-053~100에 적용한다 — agent.candidate_matcher가 실제로
쓰는 것과 동일한 정규식/추출기로 확인하므로, "문서가 그럴듯해 보이는가"가 아니라
"운영 파이프라인이 실제로 이 값을 뽑아낼 수 있는가"를 검증한다.

이 파일은 sample_specs/*.md 원본을 읽기만 하며 절대 수정하지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from langchain_core.documents import Document

from agent import categorical_match
from agent.candidate_matcher import (
    _EQUIPMENT_TYPE_RE,
    _MANUFACTURER_RE,
    _MEASUREMENT_PRINCIPLE_RE,
    _MODEL_RE,
    _THICKNESS_NOT_SUPPORTED_RE,
    _extract_candidate_fact,
    _extract_table_rows,
)
from tests.ground_truth_data import ITEM_DEFECT_LABELS, defect_type_items
from tests.ground_truth_data_053_100 import GROUND_TRUTH_053_100

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"

_NEW_SPEC_IDS = [f"SPEC-{i:03d}" for i in range(53, 101)]
_EXISTING_SPEC_IDS = [f"SPEC-{i:03d}" for i in range(1, 53)]

# SPEC-001~052(Phase 1 이전의 전체 corpus)는 이 작업에서 완전히 그대로여야 한다.
# 파일 52개 전부의 sha256을 이 스크립트 작성 시점(SPEC-053~100 생성 직후, 아직
# 001~052는 건드리기 전)에 실측해 고정했다 — mtime은 checkout 환경마다 달라
# 신뢰할 수 없으므로 내용 기반으로만 비교한다.
_EXPECTED_SHA256 = {
    "SPEC-001.md": "a2324dc19931a00632290d8fa6e6fe6b04084a45ecc53bde10644a252d1408e6",
    "SPEC-002.md": "7ed41e169e5ae1e2b521c346a117a733c9409146be1ccedef3b53dddb7d6829d",
    "SPEC-003.md": "fdc0218af56f4ba07c430ebf8976ab8bee1c38a985895a48d53cc2458cd815af",
    "SPEC-004.md": "5b88cc6621f6a5fa2e9e07b912680f4f2f0af57fff4899ed9bf5e048dfa500b3",
    "SPEC-005.md": "4cd72fcb71408e180fb15db7ab1c2cf9b297ee16eadc1b5bb1fe2f41b6e97c52",
    "SPEC-006.md": "5e141dda4326af4665465a3093181d4643373d9e8494b3a50cf7a211feb32cdd",
    "SPEC-007.md": "fb9d64f12ff7a8ee38a62677a8b31c3c2afb2453041898077f008f85001461ca",
    "SPEC-008.md": "07e4d8280ed6761d56055f8c6be9a8e3c9633f30e7c07a8b19ae29285dbb4d9a",
    "SPEC-009.md": "49906bb0a1f40dc1278cad6f50ddf944a5a563c19e1a43308a1765149b3b34fa",
    "SPEC-010.md": "138eac32fc10a53452c5c906627f1d84f0ab2cef5024c17c5d8b87aec0082033",
}


def _load(spec_id: str) -> tuple[str, Document]:
    path = _SAMPLE_SPECS_DIR / f"{spec_id}.md"
    text = path.read_text(encoding="utf-8")
    return text, Document(page_content=text, metadata={"filename": f"{spec_id}.md"})


# ---------------------------------------------------------------
# 1. 파일 개수 / 기존 파일 무결성
# ---------------------------------------------------------------
def test_exactly_48_new_spec_files_exist():
    for spec_id in _NEW_SPEC_IDS:
        assert (_SAMPLE_SPECS_DIR / f"{spec_id}.md").exists(), f"{spec_id}.md가 없습니다"
    all_files = sorted(_SAMPLE_SPECS_DIR.glob("SPEC-*.md"))
    new_files = [p for p in all_files if p.stem in set(_NEW_SPEC_IDS)]
    assert len(new_files) == 48, f"신규 파일이 정확히 48개가 아닙니다: {len(new_files)}개"
    assert len(all_files) == 100, f"sample_specs/ 전체가 정확히 100개여야 합니다: {len(all_files)}개"


def test_spec_001_to_010_are_completely_untouched():
    """SPEC-001~010은 SHA256으로 원본과 완전히 동일함을 확인한다(가장 오래된
    표본 — 우연히라도 건드렸으면 즉시 실패한다)."""
    for filename, expected_hash in _EXPECTED_SHA256.items():
        path = _SAMPLE_SPECS_DIR / filename
        assert path.exists(), f"{filename}이 삭제되었습니다"
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, (
            f"{filename}의 내용이 원본과 다릅니다 — 기존 사양서는 절대 수정 금지 규칙 위반"
        )


def test_all_52_existing_specs_have_manufacturer_and_model():
    """SPEC-001~052 전체가 여전히 정상적으로 파싱 가능한 상태인지(파일이 깨지지
    않았는지) 가벼운 스모크 테스트로 확인한다 — 001~010처럼 정확한 해시까지
    고정하지는 않지만, 최소한 "존재하고 파싱된다"는 사실은 전수 확인한다."""
    for spec_id in _EXISTING_SPEC_IDS:
        path = _SAMPLE_SPECS_DIR / f"{spec_id}.md"
        assert path.exists(), f"{spec_id}.md가 사라졌습니다"
        text = path.read_text(encoding="utf-8")
        assert _MANUFACTURER_RE.search(text) is not None, f"{spec_id}: Manufacturer를 찾을 수 없음(파일 손상 의심)"
        assert _MODEL_RE.search(text) is not None, f"{spec_id}: Model을 찾을 수 없음(파일 손상 의심)"


# ---------------------------------------------------------------
# 2. 문자열 "UNKNOWN"이 신규 문서 어디에도 없어야 한다.
# ---------------------------------------------------------------
@pytest.mark.parametrize("spec_id", _NEW_SPEC_IDS)
def test_no_literal_unknown_string_in_new_docs(spec_id):
    text, _ = _load(spec_id)
    assert re.search(r"unknown", text, re.IGNORECASE) is None, (
        f"{spec_id}.md에 'UNKNOWN' 계열 문자열이 남아있습니다 — Ground Truth가 UNKNOWN인 "
        f"필드는 문자열로 표시하지 말고 정보 자체를 생략해야 합니다."
    )
    for banned in ("N/A", "Not specified", "Not Available"):
        assert banned.lower() not in text.lower(), f"{spec_id}.md에 금지된 표현 '{banned}'가 있습니다"


# ---------------------------------------------------------------
# 3. Manufacturer+Model이 기존 52개와 겹치지 않아야 한다(신규 이름 정책).
# ---------------------------------------------------------------
def test_new_equipment_names_do_not_collide_with_existing_52():
    existing_names = set()
    for spec_id in _EXISTING_SPEC_IDS:
        text, _ = _load(spec_id)
        doc = Document(page_content=text, metadata={"filename": f"{spec_id}.md"})
        fact = _extract_candidate_fact([doc])
        if fact.manufacturer and fact.model:
            existing_names.add(f"{fact.manufacturer} {fact.model}")

    new_names = [gt.model_full for gt in GROUND_TRUTH_053_100]
    assert len(new_names) == len(set(new_names)), "신규 48개 사이에 중복된 Manufacturer+Model이 있습니다"
    overlap = set(new_names) & existing_names
    assert overlap == set(), f"신규 장비명이 기존 52개와 겹칩니다: {overlap}"


# ---------------------------------------------------------------
# 4~15. 필드별 Ground Truth 일치 검증 (agent.candidate_matcher의 실제 추출기 재사용)
# ---------------------------------------------------------------
@pytest.mark.parametrize("gt", GROUND_TRUTH_053_100, ids=[gt.spec_id for gt in GROUND_TRUTH_053_100])
def test_new_spec_matches_ground_truth(gt):
    text, doc = _load(gt.spec_id)
    fact = _extract_candidate_fact([doc])

    # Manufacturer/Model 존재 + Ground Truth와 일치
    assert fact.manufacturer, f"{gt.spec_id}: Manufacturer를 추출하지 못했습니다"
    assert fact.model, f"{gt.spec_id}: Model을 추출하지 못했습니다"
    assert f"{fact.manufacturer} {fact.model}" == gt.model_full, (
        f"{gt.spec_id}: Manufacturer/Model 불일치 — 실제 '{fact.manufacturer} {fact.model}' "
        f"vs GT '{gt.model_full}'"
    )
    assert _MANUFACTURER_RE.search(text) is not None
    assert _MODEL_RE.search(text) is not None

    # Equipment Type
    m = _EQUIPMENT_TYPE_RE.search(text)
    assert m is not None, f"{gt.spec_id}: Equipment Type이 없습니다"
    assert m.group(1).strip() == gt.equipment_type

    # Inspection Mode
    assert fact.inspection_mode == gt.mode.lower(), (
        f"{gt.spec_id}: Inspection Mode 불일치 — 실제 '{fact.inspection_mode}' vs GT '{gt.mode}'"
    )

    # Maximum Electrode Width
    if gt.width_mm is None:
        assert fact.width_mm is None, f"{gt.spec_id}: Width가 UNKNOWN이어야 하는데 {fact.width_mm}이 추출됨"
        assert "Maximum Electrode Width" not in text and "Maximum Width" not in text
    else:
        assert fact.width_mm == float(gt.width_mm), (
            f"{gt.spec_id}: Width 불일치 — 실제 {fact.width_mm} vs GT {gt.width_mm}"
        )

    # Measurement Speed
    if gt.speed_mm_s is None:
        assert fact.speed is None, f"{gt.spec_id}: Speed가 UNKNOWN이어야 하는데 {fact.speed}이 추출됨"
    else:
        assert fact.speed == (float(gt.speed_mm_s), "mm/s"), (
            f"{gt.spec_id}: Speed 불일치 — 실제 {fact.speed} vs GT {gt.speed_mm_s} mm/s"
        )

    # Measurement Range
    if gt.range_um is None:
        assert fact.range is None, f"{gt.spec_id}: Range가 UNKNOWN이어야 하는데 {fact.range}이 추출됨"
        assert "Measurement Range" not in text
    else:
        lo, hi = gt.range_um
        assert fact.range == (float(lo), float(hi), "um"), (
            f"{gt.spec_id}: Range 불일치 — 실제 {fact.range} vs GT {gt.range_um}"
        )

    # Accuracy
    if gt.accuracy_um is None:
        assert fact.accuracy is None, f"{gt.spec_id}: Accuracy가 UNKNOWN이어야 하는데 {fact.accuracy}이 추출됨"
        assert not re.search(r"\|\s*Accuracy\s*\|", text), f"{gt.spec_id}: Accuracy 행이 남아있습니다"
    else:
        assert fact.accuracy == (float(gt.accuracy_um), "um"), (
            f"{gt.spec_id}: Accuracy 불일치 — 실제 {fact.accuracy} vs GT {gt.accuracy_um}"
        )

    # Minimum Detectable Defect
    if gt.min_defect_um is None:
        assert fact.defect_size is None, (
            f"{gt.spec_id}: Min Detectable Defect가 UNKNOWN이어야 하는데 {fact.defect_size}이 추출됨"
        )
        assert "Minimum Detectable Defect" not in text
    else:
        assert fact.defect_size == (float(gt.min_defect_um), "um"), (
            f"{gt.spec_id}: Min Detectable Defect 불일치 — 실제 {fact.defect_size} vs GT {gt.min_defect_um}"
        )

    # Measurement Principle — 문서 원문이 GT 값을 그대로 담고 있는지(문자열 그대로).
    pm = _MEASUREMENT_PRINCIPLE_RE.search(text)
    assert pm is not None, f"{gt.spec_id}: Measurement Principle이 없습니다"
    assert pm.group(1).strip() == gt.principle, (
        f"{gt.spec_id}: Measurement Principle 불일치 — 실제 '{pm.group(1).strip()}' vs GT '{gt.principle}'"
    )

    # Inspection Items — 결함형 항목은 Defect Types에 전부 등장해야 하고,
    # 항목이 하나도 없으면 Defect Inspection 자체가 "Not Supported"여야 한다.
    defect_items = defect_type_items(gt.items)
    if defect_items:
        assert fact.defect_types_text is not None, (
            f"{gt.spec_id}: Defect Types가 없는데 GT 결함형 항목이 있습니다: {defect_items}"
        )
        for item in defect_items:
            label = ITEM_DEFECT_LABELS[item]
            assert label.lower() in fact.defect_types_text.lower(), (
                f"{gt.spec_id}: Defect Types에 '{label}'({item})이 없습니다 — '{fact.defect_types_text}'"
            )
    else:
        assert fact.defect_inspection_not_supported is True, (
            f"{gt.spec_id}: 결함형 검사 항목이 없으면 Defect Inspection이 'Not Supported'여야 합니다"
        )

    # thickness_not_supported(Group G 전용) — 명시적 "## Thickness Measurement /
    # Not Supported" 절이 실제로 존재하고 candidate_matcher가 인식하는지 확인한다.
    if gt.thickness_not_supported:
        assert _THICKNESS_NOT_SUPPORTED_RE.search(text) is not None, (
            f"{gt.spec_id}: thickness_not_supported=True인데 문서에 해당 절이 없습니다"
        )
        assert fact.thickness_not_supported is True
        assert "thickness" not in gt.items, (
            f"{gt.spec_id}: thickness_not_supported=True와 items에 thickness가 동시에 있으면 모순입니다"
        )
    else:
        assert fact.thickness_not_supported is False

    # thickness: Range가 알려져 있으면(즉 UNKNOWN 테스트 장비가 아니면) 구조적으로
    # 확인 가능해야 한다.
    if "thickness" in gt.items and gt.range_um is not None:
        assert fact.range is not None

    # profile_3d: Equipment Type/Principle 텍스트 자체가 "3d" 계열 키워드를
    # 담고 있는 경우에만 앱이 실제로 판정 가능하다.
    if "profile_3d" in gt.items:
        capability_text = " ".join(t for t in (gt.equipment_type, gt.principle) if t)
        if categorical_match.match_inspection_item_capability("profile_3d", capability_text) is True:
            fact_capability_text = " ".join(
                t for t in (fact.equipment_type_text, fact.measurement_principle_text) if t
            )
            assert categorical_match.match_inspection_item_capability("profile_3d", fact_capability_text) is True


# ---------------------------------------------------------------
# 16. Ground Truth에 없는 핵심 성능값을 임의로 추가하지 않았는지 — Measurement
# Performance 표의 행 개수가 GT에서 값이 있는 필드 개수를 절대 넘지 않아야 한다.
# ---------------------------------------------------------------
@pytest.mark.parametrize("gt", GROUND_TRUTH_053_100, ids=[gt.spec_id for gt in GROUND_TRUTH_053_100])
def test_no_extra_core_values_beyond_ground_truth(gt):
    text, _ = _load(gt.spec_id)
    mp_match = re.search(r"## Measurement Performance\n\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    mp_rows = _extract_table_rows(mp_match.group(1)) if mp_match else []
    expected_row_count = sum(
        1 for v in (gt.range_um, gt.accuracy_um, gt.resolution_um, gt.speed_mm_s) if v is not None
    )
    assert len(mp_rows) == expected_row_count, (
        f"{gt.spec_id}: Measurement Performance 표 행 개수가 GT와 다릅니다 — "
        f"실제 {len(mp_rows)}행 {mp_rows} vs 기대 {expected_row_count}행"
    )


# ---------------------------------------------------------------
# 17. 다양성 검증(요청서 1단계: "단순 복사본이 되어서는 안 된다") — 측정 원리
# 종류가 충분히 다양한지, Inline/Offline이 둘 다 있는지 자동 확인한다.
# ---------------------------------------------------------------
def test_new_specs_cover_diverse_measurement_principles():
    principles = {gt.principle for gt in GROUND_TRUTH_053_100}
    assert len(principles) >= 15, f"측정 원리 다양성이 부족합니다: {len(principles)}종 {sorted(principles)}"


def test_new_specs_cover_both_inline_and_offline():
    modes = {gt.mode for gt in GROUND_TRUTH_053_100}
    assert modes == {"Inline", "Offline"}
    inline_count = sum(1 for gt in GROUND_TRUTH_053_100 if gt.mode == "Inline")
    offline_count = sum(1 for gt in GROUND_TRUTH_053_100 if gt.mode == "Offline")
    assert inline_count >= 10 and offline_count >= 10, (
        f"Inline({inline_count})/Offline({offline_count}) 분포가 한쪽으로 치우쳐 있습니다"
    )


def test_new_specs_include_thickness_only_and_defect_only_and_both_scenarios():
    """요청서 1단계 예시 시나리오 — Thickness만 지원/Surface Defect만 지원(명시적
    미지원 포함)/둘 다 지원 — 이 실제로 각각 하나 이상 존재하는지 확인한다."""
    thickness_only = [gt for gt in GROUND_TRUTH_053_100 if "thickness" in gt.items and "surface_defect" not in gt.items and not defect_type_items(gt.items)]
    defect_only_explicit_no_thickness = [gt for gt in GROUND_TRUTH_053_100 if gt.thickness_not_supported]
    both = [gt for gt in GROUND_TRUTH_053_100 if "thickness" in gt.items and defect_type_items(gt.items)]

    assert len(thickness_only) >= 5, f"Thickness 전용 시나리오가 부족합니다: {len(thickness_only)}개"
    assert len(defect_only_explicit_no_thickness) >= 3, f"Thickness 명시적 미지원 시나리오가 부족합니다: {len(defect_only_explicit_no_thickness)}개"
    assert len(both) >= 3, f"Thickness+Surface Defect 동시 지원 시나리오가 부족합니다: {len(both)}개"


def test_new_specs_include_wide_narrow_range_and_speed_accuracy_tradeoff_scenarios():
    """폭은 크지만 범위가 좁은 경우 / 범위는 크지만 해상도가 낮은 경우 /
    고속-저정밀 / 저속(Offline)-고정밀 시나리오가 실제로 존재하는지 확인한다."""
    wide_narrow = [
        gt for gt in GROUND_TRUTH_053_100
        if gt.width_mm and gt.width_mm >= 1200 and gt.range_um and (gt.range_um[1] - gt.range_um[0]) <= 200
    ]
    large_range_low_res = [
        gt for gt in GROUND_TRUTH_053_100
        if gt.range_um and (gt.range_um[1] - gt.range_um[0]) >= 900 and gt.resolution_um and gt.resolution_um >= 1.0
    ]
    fast_low_precision = [
        gt for gt in GROUND_TRUTH_053_100
        if gt.speed_mm_s and gt.speed_mm_s >= 1800 and (
            (gt.accuracy_um and gt.accuracy_um >= 2.5) or (gt.min_defect_um and gt.min_defect_um >= 12)
        )
    ]
    slow_high_precision = [
        gt for gt in GROUND_TRUTH_053_100
        if gt.mode == "Offline" and (
            (gt.accuracy_um and gt.accuracy_um <= 0.1) or (gt.min_defect_um and gt.min_defect_um <= 0.5)
        )
    ]

    assert len(wide_narrow) >= 1, "광폭+좁은 측정 범위 시나리오가 없습니다"
    assert len(large_range_low_res) >= 1, "넓은 범위+낮은 해상도 시나리오가 없습니다"
    assert len(fast_low_precision) >= 1, "고속-저정밀 시나리오가 없습니다"
    assert len(slow_high_precision) >= 1, "저속(Offline)-초정밀 시나리오가 없습니다"
