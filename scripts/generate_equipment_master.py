"""
ground_truth/equipment_master.md을 생성한다 — 사람이 확인하기 쉬운 표 형태로:

1. SPEC-011~050(신규)의 Ground Truth(tests/ground_truth_data.py, 사용자가 지정한
   값 그대로)
2. SPEC-001~010(기존)의 실제 문서 값 — agent.candidate_matcher가 실제로 원문에서
   추출하는 것과 동일한 파서로 뽑아 수기 전사 오류를 없앤다.

이 파일은 ground_truth/ 폴더에 있으며 sample_specs/가 아니다 — build_rag_ollama.py는
sample_specs/*.md만 globbing하므로 RAG 인덱싱 대상이 아니다(요청서 13절).

사용법: python scripts/generate_equipment_master.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from langchain_core.documents import Document  # noqa: E402

from agent.candidate_matcher import _extract_candidate_fact  # noqa: E402
from tests.ground_truth_data import GROUND_TRUTH  # noqa: E402

_OUT_PATH = _REPO_ROOT / "ground_truth" / "equipment_master.md"


def _fmt(value) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt_range(range_tuple) -> str:
    if range_tuple is None:
        return "UNKNOWN"
    lo, hi = range_tuple[0], range_tuple[1]
    return f"{_fmt(lo)}~{_fmt(hi)}"


def _new_equipment_table() -> str:
    header = (
        "| SPEC | Model | Equipment Type | Mode | Width mm | Speed mm/s | Range μm | "
        "Accuracy μm | Resolution μm | Min Detectable Defect μm | Principle | Inspection Items |\n"
        "|---|---|---|---|---:|---:|---|---:|---:|---:|---|---|\n"
    )
    rows = []
    for gt in GROUND_TRUTH:
        rows.append(
            f"| {gt.spec_id} | {gt.model_full} | {gt.equipment_type} | {gt.mode} | "
            f"{_fmt(gt.width_mm)} | {_fmt(gt.speed_mm_s)} | {_fmt_range(gt.range_um)} | "
            f"{_fmt(gt.accuracy_um)} | {_fmt(gt.resolution_um)} | {_fmt(gt.min_defect_um)} | "
            f"{gt.principle} | {', '.join(gt.items)} |"
        )
    return header + "\n".join(rows) + "\n"


def _existing_equipment_table() -> str:
    header = (
        "| SPEC | Manufacturer/Model | Mode | Width mm | Speed | Range | Accuracy | "
        "Min Detectable Defect | Principle | Defect Types |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for i in range(1, 11):
        spec_id = f"SPEC-{i:03d}"
        path = _REPO_ROOT / "sample_specs" / f"{spec_id}.md"
        text = path.read_text(encoding="utf-8")
        fact = _extract_candidate_fact([Document(page_content=text, metadata={"filename": f"{spec_id}.md"})])
        model = f"{fact.manufacturer or '?'} {fact.model or '?'}"
        speed = f"{fact.speed[0]:g} {fact.speed[1]}" if fact.speed else "UNKNOWN"
        range_txt = f"{fact.range[0]:g}~{fact.range[1]:g} {fact.range[2]}" if fact.range else "UNKNOWN"
        accuracy = f"{fact.accuracy[0]:g} {fact.accuracy[1]}" if fact.accuracy else "UNKNOWN"
        defect_size = f"{fact.defect_size[0]:g} {fact.defect_size[1]}" if fact.defect_size else "UNKNOWN"
        rows.append(
            f"| {spec_id} | {model} | {fact.inspection_mode or 'UNKNOWN'} | "
            f"{fact.width_mm if fact.width_mm is not None else 'UNKNOWN'} | {speed} | {range_txt} | "
            f"{accuracy} | {defect_size} | {fact.measurement_principle or 'UNKNOWN'} | "
            f"{fact.defect_types_text or 'N/A'} |"
        )
    return header + "\n".join(rows) + "\n"


def main() -> None:
    _OUT_PATH.parent.mkdir(exist_ok=True)
    content = f"""# Equipment Ground Truth Master

이 파일은 `sample_specs/`에 있는 테스트용 장비 사양서의 정답(Ground Truth)을
사람이 확인하기 쉬운 표로 정리한 것이다.

**주의: 이 파일은 RAG 인덱싱 대상이 아니다.** `build_rag_ollama.py`는
`sample_specs/*.md`만 globbing하므로 `ground_truth/` 폴더의 이 파일은 벡터
DB에 들어가지 않는다 — 검색 결과 정답지를 검색 대상 자체에 섞지 않기 위함이다.

`UNKNOWN`은 "값이 존재하지만 모른다"는 뜻이 아니라, **해당 사양서 원문에
그 정보 자체가 아예 기재되어 있지 않다**는 뜻이다(의도적 설계 — RAG/Hard
Requirement 검증이 "정보 없음"을 UNKNOWN으로 정직하게 처리하는지 테스트하기
위함). `sample_specs/SPEC-0NN.md`에 `UNKNOWN`이라는 문자열이나 해당 필드의
값을 유추할 수 있는 다른 표현이 있으면 안 된다.

## 1. 신규 장비 (SPEC-011 ~ SPEC-050) — Ground Truth

이 값들은 `tests/ground_truth_data.py`(`GROUND_TRUTH`)에 정의되어 있고,
`scripts/generate_sample_specs_011_050.py`가 이 값 그대로
`sample_specs/SPEC-011.md` ~ `SPEC-050.md`를 생성했다.
`tests/test_sample_specs_ground_truth.py`가 생성된 문서와 이 값이 정확히
일치하는지(값이 있는 필드는 값이, UNKNOWN인 필드는 그 정보 자체가 문서에
없는지) 자동 검증한다.

{_new_equipment_table()}

## 2. 기존 장비 (SPEC-001 ~ SPEC-010) — 실제 문서 값

아래 값은 `agent/candidate_matcher.py`가 실제로 각 문서 원문에서 추출하는
것과 동일한 파서로 뽑은 값이다(수기 전사 오류 방지 목적으로
`scripts/generate_equipment_master.py`가 자동 생성).

{_existing_equipment_table()}
"""
    _OUT_PATH.write_text(content, encoding="utf-8")
    print(f"작성 완료: {_OUT_PATH}")


if __name__ == "__main__":
    main()
