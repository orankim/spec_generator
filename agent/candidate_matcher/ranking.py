"""
근접 중복(Near-duplicate) 탐지 + 최종 후보 랭킹 — agent/candidate_matcher/
__init__.py 참고. core.py의 build_candidates()가 만든 CandidateEquipment 목록만
입력으로 받는다(문서 재파싱/재검색 없음).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..schemas import CandidateEquipment

def _annotate_near_duplicates(candidates: List[CandidateEquipment]) -> None:
    """근접 중복(Near-duplicate) 탐지: status/pass_count/unknown_count/fail_count가
    전부 같고, PASS한 항목의 field_key 집합까지 완전히 같은 후보들을 하나의
    그룹으로 묶어 서로를 CandidateEquipment.near_duplicates에 채운다.

    select_best_candidate()가 이런 그룹 안에서도 total_margin/rag_similarity_score/
    source_document로 최종 하나를 고르지만(4~6순위), 그 판정이 "이 장비만 유일하게
    맞다"는 뜻은 아니다 — 근거(PASS한 항목)만 놓고 보면 여러 장비가 동등하게
    유효한 선택지다(Ground Truth Ambiguity 분석에서 MULTIPLE_VALID라 부르던
    개념을 production 후보 목록 자체에 반영한 것). 그룹 판정에 total_margin/
    rag_similarity_score를 넣지 않는 이유: 이 두 값은 "그룹 안에서 무엇을 먼저
    보여줄지"를 정하는 기준이지, "이 후보가 근거상 동등한 대안인지"를 바꾸지
    않기 때문이다 — SPEC-003(margin=0)과 SPEC-033(margin=300)은 margin이
    달라도 정확히 같은 항목들을 PASS했으므로 서로 근접 중복이다.
    """
    # FAIL 후보는 제외한다 — "PASS한 항목이 하나도 없다"는 이유만으로 서로 전혀
    # 다른 이유로 탈락한 FAIL 후보들이 근접 중복으로 묶이면(둘 다 passed_fields가
    # 빈 집합이 되므로) "대안"이라는 의미가 없는 잡음이 된다. PASS/PARTIAL만
    # 실제로 "이 후보 대신 저 후보를 봐도 된다"는 유용한 신호다.
    groups: Dict[Tuple[str, int, int, int, frozenset], List[CandidateEquipment]] = defaultdict(list)
    for c in candidates:
        if c.status == "FAIL":
            continue
        passed_fields = frozenset(m.field_key for m in c.matches if m.result == "PASS")
        key = (c.status, c.pass_count, c.unknown_count, c.fail_count, passed_fields)
        groups[key].append(c)

    for group in groups.values():
        if len(group) < 2:
            continue
        for c in group:
            c.near_duplicates = sorted(
                f"{o.manufacturer or '?'} {o.model or '?'} ({o.source_document})" for o in group if o is not c
            )


_STATUS_RANK = {"PASS": 0, "PARTIAL": 1, "FAIL": 2}


def select_best_candidate(candidates: List[CandidateEquipment]) -> Optional[CandidateEquipment]:
    """
    최종 랭킹 우선순위:
    1순위: Hard Requirement PASS 수가 많은 후보 (-c.pass_count) 또는 status (PASS: 0 > PARTIAL: 1 > FAIL: 2)
    2순위: UNKNOWN 수가 적은 후보 (unknown_count 오름차순)
    3순위: FAIL 수가 적은 후보 (fail_count 오름차순)
    4순위: 요구조건에 더 타이트하게 맞는 후보 (c.total_margin 오름차순 — 아래 설명)
    5순위: RAG similarity가 높은 후보 (-(c.rag_similarity_score or 0.0) 내림차순)
    6순위: 후보 문서 순서 (source_document 오름차순 — 예: "SPEC-003.md" < "SPEC-033.md")

    4순위(total_margin)는 build_candidates()가 이미 계산해 둔, "사용자가 실제로
    요구한 항목들만" 놓고 합산한 여유치다(CandidateFieldMatch.margin — 예: 요구
    범위 1~500μm에 후보가 1~500μm면 margin=0, 1~800μm면 margin=300). 오름차순
    으로 정렬하므로 margin이 작을수록(=필요 이상으로 과한 스펙이 아닐수록,
    즉 요구조건에 더 "타이트하게" 맞을수록) 먼저 온다 — 과잉 스펙 장비보다
    딱 맞는 장비를 추천한다는 실사용 관점의 정책 결정이다.

    이 기준은 과거 한 차례 시도됐다가 되돌려진 적이 있다(-c.total_margin,
    즉 "여유가 **많은**" 후보를 우선하는 정반대 방향이었다 — 그 실험은 3개
    회귀 테스트의 기존 기대값과 충돌해 되돌려졌다). 이번에는 방향을 반대로
    ("여유가 **적은**", 더 타이트한 후보 우선)하고, 이 정책을 실제로 채택하기로
    한 결정에 맞춰 그 3개 테스트의 기대값도 함께 검토·갱신했다 — 코드를 테스트에
    끼워 맞춘 것이 아니라, 랭킹 정책 자체를 바꾸기로 한 결정이 먼저이고 테스트는
    그 결정을 반영한 것이다. 다중 항목 요구에서는 서로 다른 물리량(예: mm 폭
    margin과 mm/s 속도 margin)의 margin을 합산하므로 이 총합이 "물리적으로
    정확한 종합 여유"를 의미하지는 않는다 — 단일 hard requirement가 결정적인
    동점 상황(가장 흔한 경우)에서는 정확히 의도대로 동작하고, 여러 항목이 동시에
    타이트한 다른 후보와 비교될 때는 근사치로 취급한다.

    6순위는 원래 candidate_id("cand-3", "cand-33", ... — build_candidates()가
    source_document를 알파벳순 정렬한 뒤 그 순서대로 부여하는 문자열)를 그대로
    비교했었다. 그런데 이 필드는 문자열이라 "cand-3" > "cand-26"처럼 자릿수가
    다르면 사전식 비교가 숫자 크기와 어긋난다(파이썬 문자열 비교는 자릿수를
    맞추지 않는다) — corpus가 10~52개일 때는 이 어긋남이 우연히 드러나지
    않다가, 100개로 늘면서 실제로 엉뚱한 동점 후보가 선택되는 사례가 나타났다.
    source_document는 이 corpus에서 항상 3자리로 0-padding되어 있어
    ("SPEC-003.md") 사전식 비교가 숫자 비교와 정확히 일치하므로, 비교 대상
    필드만 candidate_id에서 source_document로 바꿔 이 버그를 고친다.
    """
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda c: (
            _STATUS_RANK[c.status],
            -c.pass_count,
            c.unknown_count,
            c.fail_count,
            c.total_margin,
            -(c.rag_similarity_score or 0.0),
            c.source_document,
        ),
    )[0]
