"""
사용자 요청("실제 Ollama + bge-m3 기반 RAG 검증 실행")의 R1~R5 5개 질의를 실제
Ollama(bge-m3 임베딩 + .env OLLAMA_MODEL LLM 파싱) + 실제 ChromaDB로 끝까지
실행하고, 요청서 7절이 요구하는 항목(Requirement Parsing/Retrieval/Candidate/
Hard Requirement/Recommendation Reason)과 9절 성능 지표를 사람이 읽을 수 있는
리포트로 출력하는 1회성 검증 스크립트.

tests/test_real_rag.py(기존, 커밋됨, 수정하지 않음)는 이미 real embedding + real
ChromaDB로 5개 질의를 검증하지만 Requirement Parsing은 "LLM 빈 응답" worst-case로
스텁한다(그 파일의 의도된 설계 — tests/regression_lib.py와 동일 철학). 이 스크립트는
그와 별개로, 실제 LLM 파싱까지 포함한 완전한 실제 파이프라인 한 번을 관찰하고 싶다는
이번 요청에 맞춰 추가했다 — production code는 전혀 건드리지 않고 tests/real_rag_lib.py
(이번에 새로 추가, 기존 파일 없음)를 통해 agent.* 함수를 있는 그대로 호출한다.

사용법:
    .venv/Scripts/python.exe scripts/verify_real_rag_r1_r5.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from tests import real_rag_lib as rag  # noqa: E402

_DB_PATH = str(_REPO_ROOT / "chroma_db_specs_real_rag_test")

_QUERIES = [
    ("R1", "폭 800 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있고, 0~500 μm 범위를 ±1 μm 이하 정확도로 측정할 수 있는 두께 검사기를 찾아줘."),
    ("R2", "폭 800 mm 이상의 전극 표면에서 3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는 Inline 비전 검사기를 찾아줘."),
    ("R3", "폭 1000 mm 이상의 전극을 500 mm/s 이상의 속도로 Inline 검사할 수 있는 3D Profile 검사기를 찾아줘."),
    ("R4", "폭 600 mm 이상의 전극을 Inline으로 검사하면서 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 측정 범위는 0~300 μm이다."),
    ("R5", "폭 600 mm 이상의 전극을 Inline으로 검사할 수 있고, 두께와 표면 결함을 동시에 검사할 수 있는 장비를 찾아줘. 정확도는 지정하지 않을게."),
]

_GT_PATH = _REPO_ROOT / "tests" / "ground_truth" / "regression_cases.json"
# R1/R2/R3/R5는 regression_cases.json의 T001/T003/T004/T005와 완전히 동일한 문장이다.
# R4는 T002(정확도 명시)와 검사 항목/범위는 같지만 정확도 조건이 빠져 있어 "근접 케이스"로만 쓴다.
_GT_MAP = {"R1": "T001", "R2": "T003", "R3": "T004", "R5": "T005"}


def _section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    _section("1. 환경 점검")
    env = rag.check_ollama_environment()
    print(json.dumps(env.__dict__, ensure_ascii=False, indent=2))
    if not env.server_reachable:
        print(f"\n[BLOCKED] Ollama 서버({env.ollama_host})에 연결할 수 없습니다: {env.error}")
        return 2
    if not env.embedding_model_installed:
        print(f"\n[BLOCKED] embedding model '{env.embedding_model}'이 설치되어 있지 않습니다.")
        print(f"          설치 명령: ollama pull {env.embedding_model}")
        return 2

    _section("2. 실제 bge-m3 임베딩으로 ChromaDB 재생성 (별도 테스트 디렉터리)")
    stats = rag.build_real_vector_db(_DB_PATH)
    print(f"  db_path              = {stats.db_path}")
    print(f"  embedding_model      = {stats.embedding_model}")
    print(f"  embedding_dimension  = {stats.embedding_dimension}")
    print(f"  indexed_spec_count   = {stats.indexed_spec_count} (sample_specs/*.md 입력 파일 수)")
    print(f"  indexed_chunk_count  = {stats.indexed_chunk_count} (컬렉션 총 chunk 수)")
    print(f"  build_seconds        = {stats.build_seconds:.2f}")

    gt_cases = {}
    if _GT_PATH.exists():
        gt_data = json.loads(_GT_PATH.read_text(encoding="utf-8"))
        gt_cases = {c["test_id"]: c for c in gt_data["cases"]}

    all_results = []
    for label, query in _QUERIES:
        _section(f"3. {label} 실행: {query}")
        result = rag.run_real_case(query, stats.db_path)
        all_results.append((label, result))
        req = result.requirement

        print("\n[Requirement Parsing]")
        print(f"  inspection_mode(inline_offline)  = {req.inline_offline!r}")
        print(f"  minimum_width(target.width_mm)   = {req.target.width_mm!r}")
        print(f"  inspection_items                 = {req.inspection_items!r}")
        print(f"  inspection_categories            = {req.inspection_categories!r}")
        print(f"  measurement_range                = {req.measurement_range!r}")
        print(f"  required_accuracy (accuracy / required_accuracy_um) = {req.accuracy!r} / {req.required_accuracy_um!r}")
        print(f"  required_speed(measurement_speed)= {req.measurement_speed!r}")
        print(f"  minimum_defect_size              = {req.minimum_defect_size!r}")
        print(f"  measurement_principle            = {req.measurement_principle!r}")

        print("\n[Retrieval]")
        print(f"  검색된 chunk 수(중복 제거 후) = {len(result.retrieved_docs)}")
        for i, doc in enumerate(result.top_retrieved(10), start=1):
            score_disp = f"{doc.similarity_score:.4f}" if doc.similarity_score is not None else "N/A"
            print(f"  [{i}] SPEC={doc.spec_id:16s} score={score_disp:>8}  ({doc.location})")
            print(f"       {doc.snippet!r}")

        print("\n[Candidate]")
        print(f"  후보 수 = {len(result.candidates)}")
        if result.chosen is not None:
            c = result.chosen
            print(f"  최종 후보 = {rag.candidate_name(c)}  (SPEC={c.source_document})")
            print(f"  candidate_score(match_score) = {c.match_score:.1f}")
            print(f"  status = {c.status}   pass={c.pass_count} unknown={c.unknown_count} fail={c.fail_count}")
            print(f"  rag_similarity_score = {c.rag_similarity_score!r}")
        else:
            print("  최종 후보 없음")

        print("\n[Hard Requirement]")
        for row in result.hard_requirement_rows():
            print(
                f"  {row.item:26s} {row.result:8s} 요구={str(row.requirement_display):>16} "
                f"장비={str(row.equipment_display):>16} 근거문서={row.source_document}"
            )

        print("\n[Recommendation Reason]")
        if result.chosen is not None:
            for r in result.chosen.recommendation_reasons:
                print(f"  {r}")
            for u in result.chosen.unconfirmed_items:
                print(f"  {u}")
            # 문서 근거 없는 PASS가 있는지 명시적으로 표시.
            unverified_pass = [
                m for m in result.chosen.matches
                if m.result == "PASS" and m.source is None and not m.evidence_text
            ]
            if unverified_pass:
                print(f"  [FAIL] 근거 문서 없이 PASS로 판정된 항목: {[m.item for m in unverified_pass]}")
            else:
                print("  [OK] 모든 PASS 항목이 근거 문서를 가지고 있음")
        else:
            print("  (후보 없음)")

        print("\n[Timing]")
        for k, v in result.timing.items():
            print(f"  {k:26s} = {v:.3f}s")

        gt_id = _GT_MAP.get(label)
        if gt_id and gt_id in gt_cases:
            print(f"\n[Ground Truth 비교: {gt_id}]")
            case = gt_cases[gt_id]
            exp = case["expected_requirement"]
            for field, expected in exp.items():
                if field == "inspection_items":
                    actual = set(req.inspection_items)
                    match = actual == set(expected)
                elif field == "measurement_range":
                    actual_obj = req.measurement_range
                    match = actual_obj is not None and actual_obj.min == expected.get("min") and actual_obj.max == expected.get("max")
                    actual = actual_obj
                elif field == "accuracy":
                    actual_obj = req.accuracy
                    match = (actual_obj is not None and actual_obj.value == expected.get("value")) if expected else actual_obj is None
                    actual = actual_obj
                elif field == "measurement_speed":
                    actual_obj = req.measurement_speed
                    match = (actual_obj is not None and actual_obj.value == expected.get("value")) if expected else actual_obj is None
                    actual = actual_obj
                elif field == "required_accuracy_um":
                    actual = req.required_accuracy_um
                    match = actual == expected
                elif field == "target.width_mm":
                    actual = req.target.width_mm
                    match = actual == expected
                else:
                    actual = getattr(req, field, "?")
                    match = actual == expected
                print(f"  {field:22s} expected={expected!r:30} actual={actual!r:30} match={match}")

            exp_pass = set(case.get("expected_pass_candidates", []))
            actual_name = rag.candidate_name(result.chosen)
            print(f"  expected_pass_candidates = {sorted(exp_pass)}")
            print(f"  actual chosen candidate  = {actual_name!r} (status={result.chosen.status if result.chosen else None})")
            print(f"  candidate name match     = {actual_name in exp_pass}")

    _section("4. 성능 요약 (5개 질의)")
    metrics = ["requirement_parsing_s", "single_embedding_call_s", "retrieval_s", "candidate_extraction_s", "total_pipeline_s"]
    for metric in metrics:
        values = [r.timing[metric] for _, r in all_results]
        print(f"  {metric:26s} avg={sum(values)/len(values):.3f}s  min={min(values):.3f}s  max={max(values):.3f}s")

    _section("5. R5 핵심 불변식 재확인 (Accuracy 미지정 -> None 유지)")
    r5_result = dict(all_results)["R5"]
    r5_ok = r5_result.requirement.required_accuracy_um is None and r5_result.requirement.accuracy is None
    print(f"  required_accuracy_um = {r5_result.requirement.required_accuracy_um!r}")
    print(f"  accuracy             = {r5_result.requirement.accuracy!r}")
    print(f"  판정 = {'PASS' if r5_ok else 'FAIL (자동 생성된 정확도 발견)'}")

    _section("6. UNKNOWN != PASS 불변식 재확인 (전체 5개 질의)")
    all_ok = True
    for label, result in all_results:
        if result.chosen is None:
            continue
        has_unknown = any(m.result == "UNKNOWN" for m in result.chosen.matches)
        bad = has_unknown and result.chosen.status == "PASS"
        if bad:
            all_ok = False
        print(f"  {label}: has_unknown={has_unknown} status={result.chosen.status} -> {'FAIL' if bad else 'OK'}")
    print(f"  전체 판정 = {'PASS' if all_ok else 'FAIL'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
