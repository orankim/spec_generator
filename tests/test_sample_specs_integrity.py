"""
sample_specs/ Corpus 데이터 무결성 회귀 테스트.

scripts/audit_sample_specs.py의 audit_corpus()를 그대로 재사용한다(별도 로직을
중복 구현하지 않음). 이 테스트의 목적은 "중복이 있으면 무조건 실패"가 아니라
다음 두 가지를 보장하는 것이다.

1. 새로운(리뷰되지 않은) 중복 장비명이 조용히 들어오면 반드시 실패로 드러난다
   (사람이 반드시 검토하게 만든다 — silently 넘어가지 않는다).
2. Manufacturer/Model처럼 후보 식별에 반드시 필요한 필드가 누락되면 실패한다.

SPEC-044.md/SPEC-051.md의 "MultiInspect MI-800" 중복은 직전 조사에서 실제로
서로 다른 스펙(정확도 ±0.8 vs ±1.0, 서로 다른 Measurement Principle/Defect
Types)을 가진 문서로 확인되었고, tests/regression_lib.py가 이미 spec_id 기반
명시적 구분(candidate_spec_ids)으로 안전하게 처리하도록 고쳐졌다 — 따라서 이미
알려져 있고 리뷰된 중복으로 허용 목록에 등록해둔다. 이 목록에 없는 새 중복
장비명이 발견되면 테스트가 실패해, 회귀 테스트가 우연히 잘못된 후보를 조용히
가리키는 사고(이번에 발견된 문제)를 사전에 막는다.
"""
from __future__ import annotations

from scripts.audit_sample_specs import audit_corpus

# 이미 사람이 검토해 "서로 다른 실제 스펙을 가진, 우연한 이름 중복"으로 확인된
# 장비명 목록. 새 중복이 여기 없는 이름으로 나타나면 반드시 검토가 필요하므로
# 테스트를 실패시킨다. sample_specs/에 새 SPEC 파일을 추가할 때 기존 장비명과
# 우연히 겹치지 않았는지 이 테스트가 자동으로 확인해준다.
_REVIEWED_DUPLICATE_EQUIPMENT_NAMES = {
    "MultiInspect MI-800",  # SPEC-044.md vs SPEC-051.md — 원인 분석 완료, 서로 다른 실측 스펙(정확도 0.8 vs 1.0)
}


def test_no_missing_required_identity_fields():
    """Manufacturer/Model은 후보 식별의 최소 조건이므로 절대 누락되면 안 된다."""
    result = audit_corpus()
    assert not result.missing_required_fields, (
        f"Manufacturer/Model이 누락된 사양서가 있습니다: {result.missing_required_fields}"
    )


def test_no_duplicate_spec_ids():
    result = audit_corpus()
    assert not result.duplicate_spec_ids, f"SPEC ID 중복: {result.duplicate_spec_ids}"


def test_no_exact_duplicate_documents():
    result = audit_corpus()
    assert not result.exact_duplicate_files, f"완전히 동일한 사양서 파일이 있습니다: {result.exact_duplicate_files}"


def test_duplicate_equipment_names_are_all_reviewed():
    """
    새 중복 장비명이 리뷰 없이 들어오면 실패한다 — corpus에 새 SPEC을 추가할 때
    기존 장비명(Manufacturer + Model)과 우연히 겹치는 실수를 여기서 잡는다.
    이미 검토된 중복(_REVIEWED_DUPLICATE_EQUIPMENT_NAMES)은 통과시킨다.
    """
    result = audit_corpus()
    unreviewed = set(result.duplicate_equipment_names) - _REVIEWED_DUPLICATE_EQUIPMENT_NAMES
    assert not unreviewed, (
        f"새로 발견된, 아직 검토되지 않은 중복 장비명이 있습니다: "
        f"{ {k: result.duplicate_equipment_names[k] for k in unreviewed} } — "
        "sample_specs/의 실제 스펙을 비교해 우연한 중복인지 확인하고, 문제 없으면 "
        "tests/test_sample_specs_integrity.py의 _REVIEWED_DUPLICATE_EQUIPMENT_NAMES에 "
        "등록하세요. 동일 이름을 Key로 쓰는 코드(예: tests/regression_lib.py)가 있다면 "
        "spec_id 기반으로 안전하게 구분되는지도 함께 확인하세요."
    )


def test_reviewed_duplicates_still_exist_and_are_genuinely_different():
    """
    허용 목록에 있는 중복이 우연히 사라지거나(파일 삭제/이름 변경) 더 이상
    중복이 아니게 되면 허용 목록도 함께 정리해야 한다는 신호를 준다 — 허용
    목록이 죽은 채로 방치되는 것을 막는다.
    """
    result = audit_corpus()
    stale = _REVIEWED_DUPLICATE_EQUIPMENT_NAMES - set(result.duplicate_equipment_names)
    assert not stale, (
        f"더 이상 corpus에 존재하지 않는(또는 더 이상 중복이 아닌) 리뷰 목록 항목입니다: "
        f"{stale} — tests/test_sample_specs_integrity.py의 "
        "_REVIEWED_DUPLICATE_EQUIPMENT_NAMES에서 제거하세요."
    )
