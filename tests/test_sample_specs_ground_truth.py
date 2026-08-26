"""
sample_specs/SPEC-011.md ~ SPEC-050.md(신규 40개 테스트 장비)이
tests/ground_truth_data.py의 GROUND_TRUTH와 정확히 일치하는지 자동 검증한다.

핵심 원칙(요청서 14절): UNKNOWN 검증은 문자열 "UNKNOWN"이 없는지만 보는 게
아니라, agent.candidate_matcher가 실제로 쓰는 것과 동일한 파서로 해당 필드
자체가 구조적으로 비어 있는지("정보가 원문에 아예 없음")까지 확인한다 —
"Accuracy: UNKNOWN" 같은 명시적 표기뿐 아니라 "Accuracy" 행 자체가 없는지도
검사한다는 뜻이다.

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
    _extract_candidate_fact,
    _extract_table_rows,
)
from tests.ground_truth_data import GROUND_TRUTH, ITEM_DEFECT_LABELS, defect_type_items

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"

_NEW_SPEC_IDS = [f"SPEC-{i:03d}" for i in range(11, 51)]

# SPEC-001~010은 이 데이터셋 작업 이전(원본) 그대로여야 한다 — 실수로 손댔다면
# 이 테스트가 즉시 실패한다. 수정 시각(mtime)은 git 체크아웃/CI 환경마다
# 신뢰할 수 없으므로(예: fresh checkout은 전부 같은 mtime) 내용 기반(sha256)으로
# 검증한다.
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

# 문서 내에서 "Z Resolution" 값을 확인하기 위한 검증 전용 헬퍼(agent 쪽에는 아직
# Resolution을 hard requirement로 다루는 로직이 없으므로 별도 정규식을 둔다 —
# candidate_matcher.py를 이 검증만을 위해 확장하지 않는다).
_RESOLUTION_ROW_LABEL_RE = re.compile(r"resolution", re.IGNORECASE)


def _resolution_value_um(text: str) -> float | None:
    from agent import units

    for label, value in _extract_table_rows(text):
        if _RESOLUTION_ROW_LABEL_RE.search(label) and "z" in label.lower():
            parsed = units.parse_value_unit(value)
            if parsed is not None:
                return parsed[0]
    return None


def _load(spec_id: str) -> tuple[str, Document]:
    path = _SAMPLE_SPECS_DIR / f"{spec_id}.md"
    text = path.read_text(encoding="utf-8")
    return text, Document(page_content=text, metadata={"filename": f"{spec_id}.md"})


# ---------------------------------------------------------------
# 1. 파일 개수 / 기존 파일 무결성
# ---------------------------------------------------------------
def test_exactly_40_new_spec_files_exist():
    for spec_id in _NEW_SPEC_IDS:
        assert (_SAMPLE_SPECS_DIR / f"{spec_id}.md").exists(), f"{spec_id}.md가 없습니다"
    all_files = sorted(_SAMPLE_SPECS_DIR.glob("SPEC-*.md"))
    new_files = [p for p in all_files if p.stem in set(_NEW_SPEC_IDS)]
    assert len(new_files) == 40, f"신규 파일이 정확히 40개가 아닙니다: {len(new_files)}개"
    assert len(all_files) == 50, f"sample_specs/ 전체가 50개가 아닙니다: {len(all_files)}개"


def test_spec_001_to_010_are_completely_untouched():
    for filename, expected_hash in _EXPECTED_SHA256.items():
        path = _SAMPLE_SPECS_DIR / filename
        assert path.exists(), f"{filename}이 삭제되었습니다"
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, (
            f"{filename}의 내용이 원본과 다릅니다 — 기존 사양서는 절대 수정 금지 규칙 위반"
        )


# ---------------------------------------------------------------
# 2. 문자열 "UNKNOWN"이 신규 문서 어디에도 없어야 한다(가장 기본적인 안전망).
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
# 3~13. 필드별 Ground Truth 일치 검증 (agent.candidate_matcher의 실제 추출기 재사용)
# ---------------------------------------------------------------
@pytest.mark.parametrize("gt", GROUND_TRUTH, ids=[gt.spec_id for gt in GROUND_TRUTH])
def test_new_spec_matches_ground_truth(gt):
    text, doc = _load(gt.spec_id)
    fact = _extract_candidate_fact([doc])

    # 3/4. Manufacturer/Model 존재 + Ground Truth와 일치
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

    # 5. Inspection Mode
    assert fact.inspection_mode == gt.mode.lower(), (
        f"{gt.spec_id}: Inspection Mode 불일치 — 실제 '{fact.inspection_mode}' vs GT '{gt.mode}'"
    )

    # 6. Maximum Electrode Width
    if gt.width_mm is None:
        assert fact.width_mm is None, f"{gt.spec_id}: Width가 UNKNOWN이어야 하는데 {fact.width_mm}이 추출됨"
        assert "Maximum Electrode Width" not in text and "Maximum Width" not in text
    else:
        assert fact.width_mm == float(gt.width_mm), (
            f"{gt.spec_id}: Width 불일치 — 실제 {fact.width_mm} vs GT {gt.width_mm}"
        )

    # 7. Measurement Speed
    if gt.speed_mm_s is None:
        assert fact.speed is None, f"{gt.spec_id}: Speed가 UNKNOWN이어야 하는데 {fact.speed}이 추출됨"
    else:
        assert fact.speed == (float(gt.speed_mm_s), "mm/s"), (
            f"{gt.spec_id}: Speed 불일치 — 실제 {fact.speed} vs GT {gt.speed_mm_s} mm/s"
        )

    # 8. Measurement Range
    if gt.range_um is None:
        assert fact.range is None, f"{gt.spec_id}: Range가 UNKNOWN이어야 하는데 {fact.range}이 추출됨"
        assert "Measurement Range" not in text
    else:
        lo, hi = gt.range_um
        assert fact.range == (float(lo), float(hi), "um"), (
            f"{gt.spec_id}: Range 불일치 — 실제 {fact.range} vs GT {gt.range_um}"
        )

    # 9. Accuracy
    if gt.accuracy_um is None:
        assert fact.accuracy is None, f"{gt.spec_id}: Accuracy가 UNKNOWN이어야 하는데 {fact.accuracy}이 추출됨"
        assert not re.search(r"\|\s*Accuracy\s*\|", text), f"{gt.spec_id}: Accuracy 행이 남아있습니다"
    else:
        assert fact.accuracy == (float(gt.accuracy_um), "um"), (
            f"{gt.spec_id}: Accuracy 불일치 — 실제 {fact.accuracy} vs GT {gt.accuracy_um}"
        )

    # 10. Z Resolution (candidate_matcher에는 아직 구조적 추출기가 없어 검증 전용
    # 헬퍼로 확인한다 — agent 코드를 이 테스트만을 위해 확장하지 않는다).
    resolution_value = _resolution_value_um(text)
    if gt.resolution_um is None:
        assert resolution_value is None, (
            f"{gt.spec_id}: Resolution이 UNKNOWN이어야 하는데 {resolution_value}가 문서에 있습니다"
        )
        # "Resolution"이라는 단어 자체는 Measurement Principle 값("High Resolution
        # Vision" 등, GT에 실존하는 값)에 정당하게 등장할 수 있으므로 전체 문서에서
        # 그 단어를 금지하지 않는다 — 위 _resolution_value_um()의 표 행 기반 구조적
        # 부재 확인이 이미 "Z Resolution 수치 정보 자체가 없음"을 검증한다.
        assert not re.search(r"\|\s*Z\s*Resolution\s*\|", text)
    else:
        assert resolution_value == float(gt.resolution_um), (
            f"{gt.spec_id}: Resolution 불일치 — 실제 {resolution_value} vs GT {gt.resolution_um}"
        )

    # 11. Minimum Detectable Defect
    if gt.min_defect_um is None:
        assert fact.defect_size is None, (
            f"{gt.spec_id}: Min Detectable Defect가 UNKNOWN이어야 하는데 {fact.defect_size}이 추출됨"
        )
        assert "Minimum Detectable Defect" not in text
    else:
        assert fact.defect_size == (float(gt.min_defect_um), "um"), (
            f"{gt.spec_id}: Min Detectable Defect 불일치 — 실제 {fact.defect_size} vs GT {gt.min_defect_um}"
        )

    # 12. Measurement Principle — 문서 원문이 GT 값을 그대로 담고 있는지(문자열 그대로).
    pm = _MEASUREMENT_PRINCIPLE_RE.search(text)
    assert pm is not None, f"{gt.spec_id}: Measurement Principle이 없습니다"
    assert pm.group(1).strip() == gt.principle, (
        f"{gt.spec_id}: Measurement Principle 불일치 — 실제 '{pm.group(1).strip()}' vs GT '{gt.principle}'"
    )

    # 13. Inspection Items — 결함형 항목은 Defect Types에 전부 등장해야 하고,
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

    # thickness: Range가 알려져 있으면(즉 UNKNOWN 테스트 장비가 아니면) 구조적으로
    # 확인 가능해야 한다(fact.range 존재 = candidate_matcher의 실제 thickness 판정 근거).
    if "thickness" in gt.items and gt.range_um is not None:
        assert fact.range is not None

    # profile_3d: Equipment Type/Principle 텍스트 자체가 "3d" 계열 키워드를
    # 담고 있는 경우에만 앱이 실제로 판정 가능하다 — GT의 Equipment Type이 그런
    # 텍스트를 담고 있지 않은 조합(예: "Multi Inspection")은 앱 관점에서 정직하게
    # UNKNOWN으로 남는 것이 맞다(허위로 "3D"를 문서에 끼워넣지 않기 위함).
    if "profile_3d" in gt.items:
        capability_text = " ".join(t for t in (gt.equipment_type, gt.principle) if t)
        if categorical_match.match_inspection_item_capability("profile_3d", capability_text) is True:
            fact_capability_text = " ".join(
                t for t in (fact.equipment_type_text, fact.measurement_principle_text) if t
            )
            assert categorical_match.match_inspection_item_capability("profile_3d", fact_capability_text) is True


# ---------------------------------------------------------------
# 15. Ground Truth에 없는 핵심 성능값(정확도/범위/폭/속도/분해능/최소 결함
# 크기)을 임의로 추가하지 않았는지 — Measurement Performance 표의 행 개수가
# GT에서 값이 있는 필드 개수를 절대 넘지 않아야 한다.
# ---------------------------------------------------------------
@pytest.mark.parametrize("gt", GROUND_TRUTH, ids=[gt.spec_id for gt in GROUND_TRUTH])
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
