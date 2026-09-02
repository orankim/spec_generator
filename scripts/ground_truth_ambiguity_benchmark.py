"""
Ground Truth Ambiguity Benchmark — Ollama를 전혀 호출하지 않는다. scripts/
ranking_failure_benchmark.py가 실제 Ollama로 이미 만들어 둔
benchmark_results/ranking_failure_cache.json을 그대로 분석한다.

tests/ground_truth/regression_cases.json은 수정하지 않는다 — 대신 "향후 Acceptable
Candidates로 추가 검토할 수 있는 후보" 목록을 별도 분석 결과 파일로만 만든다
(benchmark_results/ground_truth_ambiguity_candidates.json).

사용법:
    .venv/Scripts/python.exe scripts/ground_truth_ambiguity_benchmark.py
    .venv/Scripts/python.exe scripts/ground_truth_ambiguity_benchmark.py --cache-path benchmark_results/ranking_failure_cache.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ground_truth_ambiguity_lib import (  # noqa: E402
    MULTIPLE_VALID,
    UNIQUE_VALID,
    analyze_cache,
    compute_metrics,
    load_cache,
)

_DEFAULT_CACHE = _REPO_ROOT / "benchmark_results" / "ranking_failure_cache.json"
_RESULTS_DIR = _REPO_ROOT / "benchmark_results"


def _fmt(v):
    return f"{v:.3f}" if v is not None else "N/A"


def run(cache_path: Path) -> dict:
    if not cache_path.exists():
        raise SystemExit(
            f"[BLOCKED] 캐시가 없습니다: {cache_path}. "
            "먼저 scripts/ranking_failure_benchmark.py를 실행해 real Ollama 캐시를 만드세요."
        )
    cache = load_cache(cache_path)
    results_by_k = analyze_cache(cache)

    print("=" * 90)
    print("Ground Truth Ambiguity 분석 (Ollama 미사용 — 기존 real RAG 캐시 재분석)")
    print("=" * 90)
    print(f"  cache: {cache_path}")
    print(f"  embedding_model={cache['environment']['embedding_model']} llm_model={cache['environment']['llm_model']}")

    summaries = {}
    for k, results in results_by_k.items():
        summary = compute_metrics(results)
        summaries[k] = summary
        print(f"\n--- k={k} ---")
        print(f"  evaluable={summary.n_evaluable}")
        print(f"  category_counts={summary.category_counts}")
        print(
            f"  strict_top1={_fmt(summary.strict_top1_rate)}  acceptable_top1={_fmt(summary.acceptable_top1_rate)}  "
            f"requirement_satisfaction_top1={_fmt(summary.requirement_satisfaction_top1_rate)}  "
            f"ground_truth_unique_accuracy={_fmt(summary.ground_truth_unique_accuracy)}(n_unique_valid={summary.n_unique_valid})"
        )

    # Ground Truth 개선 후보 목록(제안만, regression_cases.json은 수정하지 않음).
    default_k = 10 if 10 in results_by_k else list(results_by_k.keys())[0]
    candidates_suggestion = []
    for r in results_by_k[default_k]:
        if r.category == MULTIPLE_VALID:
            candidates_suggestion.append({
                "test_id": r.test_id,
                "current_expected": r.expected_source,
                "suggested_acceptable_candidates": sorted(set([r.expected_source] + r.other_pass_candidates + ([r.top1_source] if r.top1_source else []))),
                "reason": "PASS 항목 집합이 Expected와 동일한 다른 후보가 존재(MULTIPLE_VALID) — Acceptable Candidates 목록 확장을 검토할 가치가 있음",
            })

    options_comparison = {
        "A_keep_single_expected": {
            "description": "현재 형태 유지 — expected_pass_candidates 단일/소수 리스트만 사용, 그 외 동등 PASS 후보는 무시.",
            "pros": ["스키마 변경 없음, 구현 비용 0", "회귀 테스트가 '정확히 이 후보'를 기대하므로 실수로 잘못된 후보를 허용할 여지가 없음(엄격함)"],
            "cons": [
                f"MULTIPLE_VALID이 k=10에서 43개 중 24개(55.8%)로 대다수 — Strict Top1 지표가 실제 랭킹 품질이 아니라 GT 임의성에 의해 좌우됨",
                "k를 늘릴수록(Recall 개선) Strict Top1이 오히려 낮아지는 역설이 계속 발생(H1로 확인됨)",
            ],
            "regression_test_fitness": "낮음 — 현재 Strict Top1 assertion을 쓰는 테스트는 GT 임의성 때문에 k 튜닝/랭킹 개선을 검증하기 어려움",
            "corpus_scalability": "낮음 — corpus가 커질수록 동등 대안 후보가 늘어나 MULTIPLE_VALID 비율이 더 커질 것으로 예상됨",
            "implementation_complexity": "없음(현행 유지)",
        },
        "B_expected_candidates_list": {
            "description": "expected_pass_candidates를 항상 리스트로 바꾸고, PASS 항목 집합이 Expected와 동일한 모든 후보를 포함.",
            "pros": [
                "Acceptable Top1(Top1 in expected_candidates)을 GT 스키마 차원에서 직접 표현 가능",
                "이번 분석에서 이미 이 리스트 후보(24개 MULTIPLE_VALID 사례)를 실제로 산출해 두었음(본 파일 candidates 필드)",
            ],
            "cons": [
                "기존 '단일 정답' 가정에 의존하는 코드/테스트가 있다면 전부 리스트 처리로 바꿔야 함",
                "누가/언제 '동등하다'를 판정했는지 근거를 계속 유지·검증해야 함(자동 산출 후 수동 검수 필요)",
            ],
            "regression_test_fitness": "높음 — Strict/Acceptable 두 지표를 동시에 계속 추적할 수 있어 랭킹 성능과 GT 임의성을 계속 분리해서 볼 수 있음",
            "corpus_scalability": "중간 — 신규 SPEC 추가 시 기존 케이스의 동등 후보 목록도 재검토가 필요할 수 있음",
            "implementation_complexity": "중간 — regression_cases.json 스키마 변경 + 이를 소비하는 모든 코드 경로 수정 필요",
        },
        "C_top1_plus_acceptable": {
            "description": "expected_top1(엄격한 단일 정답, 있는 경우만) + acceptable_candidates(동등 대안) 두 필드로 분리.",
            "pros": [
                "UNIQUE_VALID 케이스(expected_top1만 존재)와 MULTIPLE_VALID 케이스(둘 다 존재)를 스키마 차원에서 구분 가능 — Ground Truth Unique Accuracy를 스키마가 직접 지원",
                "B안보다 의미가 명확함('진짜 유일한 정답'과 '허용 가능한 대안'을 섞지 않음)",
            ],
            "cons": ["B안보다 필드가 하나 더 많아 스키마/파서 복잡도가 약간 더 높음"],
            "regression_test_fitness": "가장 높음 — 이번 작업에서 만든 UNIQUE_VALID/MULTIPLE_VALID 분류와 1:1로 대응되어 Ground Truth Unique Accuracy 같은 지표를 스키마에서 바로 얻을 수 있음",
            "corpus_scalability": "중간 — B안과 동일한 유지보수 부담",
            "implementation_complexity": "중간-높음 — B안 대비 필드 하나 추가 + expected_top1이 없는(=UNIQUE_VALID 아님) 케이스 처리 로직 필요",
        },
        "recommendation": (
            "본 분석은 세 옵션 중 어느 것도 적용하지 않음(regression_cases.json 미변경). "
            "다만 데이터상 C안이 이번 작업에서 이미 확립한 분류(UNIQUE_VALID/MULTIPLE_VALID)와 "
            "가장 잘 맞아떨어지므로, 향후 GT 스키마를 바꾸기로 결정한다면 C안을 우선 검토할 것을 제안함 "
            "— 단, 이 제안은 PROPOSE 수준이며 즉시 적용 대상이 아님."
        ),
    }

    _RESULTS_DIR.mkdir(exist_ok=True)
    (_RESULTS_DIR / "ground_truth_ambiguity_candidates.json").write_text(
        json.dumps(
            {
                "k": default_k,
                "note": "제안 목록일 뿐 regression_cases.json은 수정하지 않았음",
                "candidates": candidates_suggestion,
                "options_comparison": options_comparison,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n제안 목록 저장됨(regression_cases.json은 수정하지 않음): {_RESULTS_DIR / 'ground_truth_ambiguity_candidates.json'}")

    return {"results_by_k": results_by_k, "summaries": summaries, "candidates_suggestion": candidates_suggestion, "cache": cache}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-path", type=str, default=str(_DEFAULT_CACHE))
    args = parser.parse_args()
    run(Path(args.cache_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
