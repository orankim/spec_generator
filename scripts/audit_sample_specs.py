"""
sample_specs/ Corpus 데이터 무결성 Audit 도구.

실행:
    python scripts/audit_sample_specs.py

이 스크립트는 sample_specs/*.md 전체를 실제 운영 파이프라인이 쓰는 것과 동일한
파서(build_rag_ollama.parse_markdown_file)와 필드 추출기
(agent.candidate_matcher._extract_candidate_fact)로 읽어, 아래 항목을 검사한다.

  A. SPEC ID(파일명) 중복
  B/C. Equipment Name(= Manufacturer + Model) 중복
       (agent/tests 전체에서 Equipment Name은 항상 "Manufacturer Model" 형태로
       조합되므로 B와 C는 동일한 검사다 — tests/regression_lib.py:candidate_name 참고)
  D. 문서 내용 중복 — 파일 전체 완전 동일 / 주요 Metadata(제조사/모델/장비유형/
     원리/검사모드) 동일 / 주요 Spec 필드(범위/정확도/분해능/폭/속도) 동일, 3단계
  E. 필수 Metadata(Manufacturer/Model) 누락

새 DB나 별도 유사도 엔진을 추가하지 않고, 이미 운영 코드가 쓰는 결정론적
정규식/추출 로직만 재사용한다(RAG 동작 자체를 바꾸지 않음).

이 스크립트가 발견한 "중복"은 자동으로 오류 처리되지 않는다 — 동일 장비명이
서로 다른 사양(정확도/원리 등)을 가리키는 경우가 있을 수 있으므로, 사람이
직접 CandidateComparison 절을 보고 판단해야 한다(README/TESTING.md 참고).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from glob import glob
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from build_rag_ollama import parse_markdown_file  # noqa: E402
from agent.candidate_matcher import _extract_candidate_fact  # noqa: E402

# 현재 Hard Requirement/Candidate 매칭 로직이 실제로 "이 값이 없으면 후보를
# 사람이 식별/추천할 수 없다"고 취급하는 필드만 필수로 간주한다. 나머지(범위/
# 정확도/분해능/폭/속도/결함 크기 등)는 ground_truth/equipment_master.md에
# 명시된 대로 "정보 없음 = UNKNOWN"이 의도된 설계이므로 선택 필드로 분류한다.
REQUIRED_FIELDS = ("manufacturer", "model")
OPTIONAL_FIELDS = (
    "equipment_type_text",
    "measurement_principle",
    "inspection_mode",
    "measurement_method",
    "range",
    "accuracy",
    "resolution",
    "width_mm",
    "speed",
    "defect_size",
    "defect_types_text",
)


@dataclass
class SpecRecord:
    spec_id: str
    path: str
    manufacturer: Optional[str]
    model: Optional[str]
    equipment_name: str
    equipment_type: Optional[str]
    measurement_principle: Optional[str]
    inspection_mode: Optional[str]
    measurement_method: Optional[str]
    range: Optional[Tuple[float, float, str]]
    accuracy: Optional[Tuple[float, str]]
    resolution: Optional[Tuple[float, str]]
    width_mm: Optional[float]
    speed: Optional[Tuple[float, str]]
    defect_size: Optional[Tuple[float, str]]
    defect_types_text: Optional[str]
    content_hash: str
    missing_required: List[str] = field(default_factory=list)


@dataclass
class AuditResult:
    records: List[SpecRecord]
    duplicate_spec_ids: Dict[str, List[str]]
    duplicate_equipment_names: Dict[str, List[str]]
    exact_duplicate_files: Dict[str, List[str]]
    duplicate_core_metadata: Dict[Tuple, List[str]]
    duplicate_spec_fields: Dict[Tuple, List[str]]
    missing_required_fields: Dict[str, List[str]]

    @property
    def status(self) -> str:
        if self.missing_required_fields or self.duplicate_spec_ids or self.exact_duplicate_files:
            return "FAIL"
        if self.duplicate_equipment_names or self.duplicate_core_metadata or self.duplicate_spec_fields:
            return "WARNING"
        return "PASS"


def _load_record(path: str) -> SpecRecord:
    spec_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # parse_markdown_file은 진행 상황을 print()로 출력한다 — audit 리포트를
    # 깔끔하게 유지하기 위해 여기서는 표준출력을 잠시 흡수한다.
    with contextlib.redirect_stdout(io.StringIO()):
        docs = parse_markdown_file(path)
    fact = _extract_candidate_fact(docs)

    manufacturer = fact.manufacturer
    model = fact.model
    equipment_name = f"{manufacturer or '?'} {model or '?'}"

    missing_required = []
    if not manufacturer:
        missing_required.append("manufacturer")
    if not model:
        missing_required.append("model")

    return SpecRecord(
        spec_id=spec_id,
        path=path,
        manufacturer=manufacturer,
        model=model,
        equipment_name=equipment_name,
        equipment_type=fact.equipment_type_text,
        measurement_principle=fact.measurement_principle,
        inspection_mode=fact.inspection_mode,
        measurement_method=fact.measurement_method,
        range=fact.range,
        accuracy=fact.accuracy,
        resolution=fact.resolution,
        width_mm=fact.width_mm,
        speed=fact.speed,
        defect_types_text=fact.defect_types_text,
        defect_size=fact.defect_size,
        content_hash=content_hash,
        missing_required=missing_required,
    )


def _group_duplicates(records: List[SpecRecord], key_fn) -> Dict:
    groups: Dict = defaultdict(list)
    for r in records:
        key = key_fn(r)
        if key is None:
            continue
        groups[key].append(r.spec_id)
    return {k: v for k, v in groups.items() if len(v) > 1}


def audit_corpus(sample_specs_dir: str = "sample_specs") -> AuditResult:
    base = sample_specs_dir if os.path.isabs(sample_specs_dir) else os.path.join(_REPO_ROOT, sample_specs_dir)
    paths = sorted(glob(os.path.join(base, "SPEC-*.md")))
    records = [_load_record(p) for p in paths]

    duplicate_spec_ids = _group_duplicates(records, lambda r: r.spec_id)

    duplicate_equipment_names = _group_duplicates(
        records, lambda r: r.equipment_name if (r.manufacturer and r.model) else None
    )

    exact_duplicate_files = _group_duplicates(records, lambda r: r.content_hash)

    duplicate_core_metadata = _group_duplicates(
        records,
        lambda r: (
            r.manufacturer,
            r.model,
            r.equipment_type,
            r.measurement_principle,
            r.inspection_mode,
            r.measurement_method,
        )
        if (r.manufacturer and r.model)
        else None,
    )

    duplicate_spec_fields = _group_duplicates(
        records,
        lambda r: (r.range, r.accuracy, r.resolution, r.width_mm, r.speed)
        if (r.manufacturer and r.model)
        else None,
    )

    missing_required_fields = {r.spec_id: r.missing_required for r in records if r.missing_required}

    return AuditResult(
        records=records,
        duplicate_spec_ids=duplicate_spec_ids,
        duplicate_equipment_names=duplicate_equipment_names,
        exact_duplicate_files=exact_duplicate_files,
        duplicate_core_metadata=duplicate_core_metadata,
        duplicate_spec_fields=duplicate_spec_fields,
        missing_required_fields=missing_required_fields,
    )


def format_report(result: AuditResult) -> str:
    lines: List[str] = []
    lines.append("Sample Specs Corpus Audit")
    lines.append("")
    lines.append(f"Total Documents: {len(result.records)}")
    unique_names = {r.equipment_name for r in result.records if r.manufacturer and r.model}
    lines.append(f"Unique Equipment Names: {len(unique_names)}")
    lines.append("")

    lines.append("Duplicate SPEC ID:")
    if result.duplicate_spec_ids:
        for name, ids in sorted(result.duplicate_spec_ids.items()):
            lines.append(f"- {name}")
            for i in ids:
                lines.append(f"  - {i}.md")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append("Duplicate Equipment Names (Manufacturer + Model):")
    if result.duplicate_equipment_names:
        for name, ids in sorted(result.duplicate_equipment_names.items()):
            lines.append(f"- {name}")
            for i in ids:
                lines.append(f"  - {i}.md")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append("Exact Duplicate Documents (파일 전체 SHA256 동일):")
    if result.exact_duplicate_files:
        for h, ids in sorted(result.exact_duplicate_files.items()):
            lines.append(f"- {h[:12]}...")
            for i in ids:
                lines.append(f"  - {i}.md")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append("Same Core Metadata (Manufacturer/Model/Equipment Type/Principle/Mode/Method 전부 동일):")
    if result.duplicate_core_metadata:
        for key, ids in sorted(result.duplicate_core_metadata.items(), key=lambda kv: kv[1]):
            lines.append(f"- {key[0]} {key[1]} ({key[2]}, {key[3]}, {key[4]}, {key[5]})")
            for i in ids:
                lines.append(f"  - {i}.md")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append("Same Core Spec Fields (Range/Accuracy/Resolution/Width/Speed 전부 동일):")
    if result.duplicate_spec_fields:
        for key, ids in sorted(result.duplicate_spec_fields.items(), key=lambda kv: kv[1]):
            lines.append(f"- range={key[0]} accuracy={key[1]} resolution={key[2]} width_mm={key[3]} speed={key[4]}")
            for i in ids:
                lines.append(f"  - {i}.md")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append("Potential Metadata Issues (필수 필드 Manufacturer/Model 누락):")
    if result.missing_required_fields:
        for spec_id, missing in sorted(result.missing_required_fields.items()):
            lines.append(f"- {spec_id}.md: {', '.join(missing)} 누락")
    else:
        lines.append("(없음)")
    lines.append("")

    lines.append(f"Result: {result.status}")
    return "\n".join(lines)


if __name__ == "__main__":
    result = audit_corpus()
    print(format_report(result))
    sys.exit(1 if result.status == "FAIL" else 0)
