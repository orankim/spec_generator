"""
장비명(Manufacturer/Model) 기반 SPEC 조회 — Phase 6(사양+견적 통합)에서
"ES-200의 사양/견적을 알려줘", "ES-200과 MI-800을 비교해줘"처럼 요구사항이
아니라 **특정 장비 이름**으로 질문하는 경우를 지원한다.

기존 candidate_matcher.build_candidates()는 RequirementSchema(폭/정확도 등
요구조건)를 입력으로 받아 RAG 검색 결과에서 후보를 뽑는다 — "이름으로 콕
집어 찾기"에는 맞지 않는 별도 경로다. 여기서는 RAG/LLM을 전혀 쓰지 않고
sample_specs/ 전체를 직접 스캔해 결정론적 문자열 매칭만 한다(요청서: 하드
판정은 Python 코드로).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from glob import glob
from typing import List, Optional

from .candidate_matcher import extract_manufacturer_model
from .paths import DEFAULT_SAMPLE_SPECS_DIR


@dataclass
class EquipmentIdentity:
    spec_id: str  # 예: "SPEC-001"
    filename: str  # 예: "SPEC-001.md"
    path: str
    manufacturer: Optional[str]
    model: Optional[str]

    @property
    def equipment_name(self) -> str:
        return f"{self.manufacturer or '?'} {self.model or '?'}"


def _load_all_identities(specs_dir: Optional[str] = None) -> List[EquipmentIdentity]:
    base = specs_dir or DEFAULT_SAMPLE_SPECS_DIR
    identities = []
    for path in sorted(glob(os.path.join(base, "SPEC-*.md"))):
        filename = os.path.basename(path)
        spec_id = os.path.splitext(filename)[0]
        text = open(path, "r", encoding="utf-8").read()
        mfr, model = extract_manufacturer_model(text)
        identities.append(EquipmentIdentity(spec_id=spec_id, filename=filename, path=path, manufacturer=mfr, model=model))
    return identities


def find_specs_by_mentioned_names(text: str, specs_dir: Optional[str] = None) -> List[EquipmentIdentity]:
    """text 안에 등장하는 모델명(예: 'ES-200', 'MI-800')과 일치하는 SPEC을 전부
    찾는다. 모델 코드가 corpus 전체에서 충분히 구별되는 문자열이라는 전제로
    대소문자 무시 부분 문자열 매칭을 쓴다 — 정규식 특수문자가 모델명에 섞여
    있어도(예: 'TP-800') re.escape로 안전하게 처리한다. 매칭 순서는 text에
    등장하는 순서를 최대한 보존한다(비교 질문에서 "A와 B를 비교" 순서가
    사용자 기대와 같아야 함)."""
    identities = _load_all_identities(specs_dir)
    text_lower = text.lower()
    matched: List[EquipmentIdentity] = []
    seen_spec_ids = set()
    for ident in identities:
        if not ident.model:
            continue
        pattern = re.escape(ident.model.lower())
        m = re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text_lower)
        if m:
            matched.append((m.start(), ident))
    matched.sort(key=lambda pair: pair[0])
    result = []
    for _, ident in matched:
        if ident.spec_id in seen_spec_ids:
            continue
        seen_spec_ids.add(ident.spec_id)
        result.append(ident)
    return result
