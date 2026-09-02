"""
Full Retrieval Recall Benchmark(T001~T027 + QA001~QA029)의 순수 로직 모듈.

이 파일은 Ollama를 전혀 필요로 하지 않는다 — Dataset 발견, Expected Candidate
정규화, Recall/Rank/MRR 계산 같은 "Benchmark 자체의 로직"만 담는다(요청서 5/18-1절:
"Ollama 없이 실행 가능한 테스트"가 검증하는 대상이 바로 이 모듈이다). 실제 Ollama
호출이 필요한 부분(임베딩/LLM 파싱/Retrieval 실행)은
scripts/full_retrieval_recall_benchmark.py가 담당하고, 이 모듈의 함수를 가져다
쓴다.

Production Retrieval/Ranking 로직(agent/spec_retriever.py, agent/candidate_matcher.py)은
여기서 재구현하지 않는다 — 이 모듈은 다음만 한다.

1. Dataset Discovery — tests/regression_lib.load_regression_cases()를 그대로 재사용
   (T001~T027/QA001~QA029라는 개수를 하드코딩하지 않고 JSON의 "cases" 배열을 그대로 읽음).
2. Expected Candidate Normalization — Ground Truth의 "장비 이름" 표기를 실제 SPEC
   파일 집합으로 바꾼다. 이때 agent.candidate_matcher.extract_manufacturer_model()
   (production 함수)을 sample_specs/*.md 전체에 적용해 이름->SPEC 매핑을 동적으로
   만든다 — 이름을 SPEC 파일에 하드코딩하지 않는다.
3. Candidate-Level Recall/Rank/MRR 계산 — agent.spec_retriever.retrieve_for_requirement()가
   반환한 Document 목록(그대로 받아옴, 재검색하지 않음)에서 "chunk 목록 -> SPEC 파일
   단위 best score"로 축약한 뒤 순위를 매긴다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"


# ==========================================
# 1. Dataset Discovery
# ==========================================
def discover_sample_spec_files() -> List[Path]:
    """sample_specs/SPEC-*.md를 매 실행 시점에 다시 스캔한다 — 개수를 하드코딩하지
    않으므로 SPEC-053.md 등이 추가되어도 코드 수정 없이 자동으로 포함된다."""
    return sorted(_SAMPLE_SPECS_DIR.glob("SPEC-*.md"))


def discover_benchmark_cases() -> List[Dict[str, Any]]:
    """tests/regression_lib.load_regression_cases()를 그대로 재사용한다 — T001~T027/
    QA001~QA029라는 구체적인 개수·범위를 이 파일 어디에도 하드코딩하지 않는다.
    tests/ground_truth/regression_cases.json에 T028, QA030 등이 추가되면 이 함수의
    반환값도 자동으로 늘어난다."""
    from tests.regression_lib import load_regression_cases

    return load_regression_cases()


# ==========================================
# 2. Expected Candidate Normalization
# ==========================================
def build_equipment_name_to_spec_ids() -> Dict[str, Set[str]]:
    """production agent.candidate_matcher.extract_manufacturer_model()을 sample_specs/
    전체에 그대로 적용해 "제조사 모델" -> {SPEC 파일명, ...} 매핑을 동적으로 만든다.
    이름이 코퍼스 내에서 유일하면 값이 원소 1개인 집합이 되고, 중복되면(현재 corpus에서
    "MultiInspect MI-800" 단 1건, TESTING.md에 문서화됨) 원소가 여러 개인 집합이 된다 —
    이 경우 Ground Truth의 candidate_spec_ids가 항상 명시적으로 어느 파일인지 지정하므로
    (regression_cases.json 확인됨: 이 이름을 참조하는 8개 케이스 전부 override 보유)
    resolve_expected_spec_ids()가 이 모호함을 안전하게 해소한다."""
    from agent.candidate_matcher import extract_manufacturer_model

    mapping: Dict[str, Set[str]] = {}
    for path in discover_sample_spec_files():
        text = path.read_text(encoding="utf-8")
        manufacturer, model = extract_manufacturer_model(text)
        if manufacturer and model:
            name = f"{manufacturer} {model}"
            mapping.setdefault(name, set()).add(path.name)
    return mapping


def resolve_expected_spec_ids(case: Dict[str, Any], name_to_spec_ids: Dict[str, Set[str]]) -> Set[str]:
    """case["expected_pass_candidates"](이름 목록)를 실제 SPEC 파일 집합으로 바꾼다.
    case["candidate_spec_ids"]에 특정 이름의 오버라이드가 있으면 그 파일 하나만 쓰고,
    없으면 코퍼스 전체 동적 매핑을 그대로 쓴다(요청서 7절: Multiple Expected Candidate는
    "OR" 집합으로 취급 — Top-K 안에 하나라도 있으면 HIT)."""
    overrides = case.get("candidate_spec_ids") or {}
    expected: Set[str] = set()
    for name in case.get("expected_pass_candidates") or []:
        if name in overrides:
            expected.add(overrides[name])
        else:
            expected |= name_to_spec_ids.get(name, set())
    return expected


# ==========================================
# 3. Candidate-Level Recall/Rank 계산
# ==========================================
def candidate_level_documents(retrieved_docs: List[Any]) -> Dict[str, Optional[float]]:
    """retrieve_for_requirement()가 반환한 chunk(Document) 목록을 SPEC 파일 단위로
    축약한다 — 동일 SPEC의 여러 chunk는 하나의 candidate로 취급한다(요청서 15절).
    값은 그 SPEC의 chunk 중 metadata['score']가 있는 것의 최댓값(semantic top-k로
    찾아진 경우)이고, 어떤 chunk에도 score가 없으면(agent.spec_retriever의
    range_boost/inspection_item_boost/전체 문서 pull로만 들어온 경우) None이다."""
    best: Dict[str, Optional[float]] = {}
    for doc in retrieved_docs:
        source = doc.metadata.get("filename") or doc.metadata.get("source", "Unknown")
        score = doc.metadata.get("score")
        if source not in best:
            best[source] = score
        elif score is not None and (best[source] is None or score > best[source]):
            best[source] = score
    return best


def rank_candidates_by_score(doc_scores: Dict[str, Optional[float]]) -> List[Tuple[str, Optional[float], Optional[int]]]:
    """score가 있는 문서만 내림차순으로 순위(1부터)를 매긴다. score가 없는 문서(boost/
    전체 문서 pull로만 들어온 경우)는 순위 없이(rank=None) 뒤에 이름 오름차순으로 붙인다
    — production retrieve_for_requirement()는 순수 top-k 검색기가 아니라 여러 단계
    (다중 질의 top-k + range_boost + inspection_item_boost + 후보 확정 후 전체 문서
    pull)로 구성되므로, "순위"는 k_per_query에 실제로 영향받는 부분(semantic top-k)에
    대해서만 의미가 있다 — 이 구분을 흐리지 않기 위해 두 종류를 명확히 나눈다."""
    scored = sorted(((k, v) for k, v in doc_scores.items() if v is not None), key=lambda kv: -kv[1])
    ranked = [(name, score, i + 1) for i, (name, score) in enumerate(scored)]
    unscored = sorted(k for k, v in doc_scores.items() if v is None)
    ranked += [(name, None, None) for name in unscored]
    return ranked


@dataclass
class RecallEvaluation:
    evaluable: bool
    hit: bool = False
    rank: Optional[int] = None
    rank_kind: str = "n/a"  # "scored" | "boost_only" | "miss" | "n/a"(evaluable=False)
    matched_spec: Optional[str] = None


def evaluate_recall_for_case(expected_spec_ids: Set[str], doc_scores: Dict[str, Optional[float]]) -> RecallEvaluation:
    """expected_spec_ids가 비어있으면(이 케이스에 긍정 기대 후보가 아예 없음 — 예:
    Width 2000mm처럼 존재하지 않는 조건을 검증하는 케이스) evaluable=False로 표시해
    Recall@K 분모에서 제외한다(요청서 6-1절 "Total Evaluated Query Count"). 그 외에는
    다음 우선순위로 판정한다.
      1) expected 중 하나라도 scored 순위가 있으면 -> hit, 그 중 가장 높은(작은) 순위.
      2) scored는 없지만 boost로만 존재하면 -> hit이지만 rank=None(rank_kind=boost_only).
      3) 전혀 없으면 -> miss.
    """
    if not expected_spec_ids:
        return RecallEvaluation(evaluable=False)

    ranked = rank_candidates_by_score(doc_scores)
    rank_map: Dict[str, Optional[int]] = {name: rank for name, _score, rank in ranked}

    scored_hits = [(name, rank_map[name]) for name in expected_spec_ids if rank_map.get(name) is not None]
    if scored_hits:
        best_name, best_rank = min(scored_hits, key=lambda x: x[1])
        return RecallEvaluation(evaluable=True, hit=True, rank=best_rank, rank_kind="scored", matched_spec=best_name)

    boost_hits = sorted(name for name in expected_spec_ids if name in doc_scores)
    if boost_hits:
        return RecallEvaluation(evaluable=True, hit=True, rank=None, rank_kind="boost_only", matched_spec=boost_hits[0])

    return RecallEvaluation(evaluable=True, hit=False, rank=None, rank_kind="miss", matched_spec=None)


@dataclass
class RecallAtKSummary:
    k: int
    n_total_cases: int
    n_evaluable: int
    n_excluded_no_expected: int
    n_hit: int
    n_miss: int
    n_boost_only_hit: int
    recall: Optional[float]
    avg_rank: Optional[float]
    median_rank: Optional[float]
    worst_rank: Optional[int]
    mrr: Optional[float]


def compute_recall_at_k(k: int, evaluations: List[Tuple[str, RecallEvaluation]]) -> RecallAtKSummary:
    """evaluations: [(case_id, RecallEvaluation), ...]. Recall/Rank 통계는 evaluable=True인
    케이스만 대상으로 한다. avg_rank/median_rank/worst_rank/mrr은 rank_kind='scored'인
    hit만 대상으로 한다(boost_only hit은 HIT로는 세지만 "몇 등이었나"를 매길 수 없으므로
    순위 통계에서는 별도 카운트로만 보고한다 — 억지로 rank=1 등으로 끼워 맞추지 않는다)."""
    total = len(evaluations)
    evaluable = [(cid, e) for cid, e in evaluations if e.evaluable]
    hits = [(cid, e) for cid, e in evaluable if e.hit]
    boost_only_hits = [e for _cid, e in hits if e.rank_kind == "boost_only"]
    scored_ranks = [e.rank for _cid, e in hits if e.rank_kind == "scored" and e.rank is not None]

    return RecallAtKSummary(
        k=k,
        n_total_cases=total,
        n_evaluable=len(evaluable),
        n_excluded_no_expected=total - len(evaluable),
        n_hit=len(hits),
        n_miss=len(evaluable) - len(hits),
        n_boost_only_hit=len(boost_only_hits),
        recall=(len(hits) / len(evaluable)) if evaluable else None,
        avg_rank=(sum(scored_ranks) / len(scored_ranks)) if scored_ranks else None,
        median_rank=statistics.median(scored_ranks) if scored_ranks else None,
        worst_rank=max(scored_ranks) if scored_ranks else None,
        mrr=(sum(1.0 / r for r in scored_ranks) / len(scored_ranks)) if scored_ranks else None,
    )


# ==========================================
# 4. Pipeline Funnel 요약 — Retrieval 단계를 넘어 Candidate Extraction/Final
# Recommendation까지 단계별로 분리해 집계한다(요청서 7/8/10절). compute_recall_at_k()는
# 그대로 두고(기존 unit test가 이미 그 함수의 정확한 동작을 보증) 별도 함수로 추가한다.
#
# 이 함수가 기대하는 row 형태는 scripts/full_retrieval_recall_benchmark.py가 만드는
# per-case 결과 dict다(evaluable/hit/rank/rank_kind/candidate_extraction_hit/
# retrieved_unique_doc_count/candidate_count/final_status/final_matches_expected).
# ==========================================
@dataclass
class FunnelSummary:
    k: int
    n_total_cases: int
    n_evaluable: int  # Expected Candidate가 존재하는 케이스 수
    n_no_expected: int  # Expected Candidate가 없는(존재하지 않는 조건 등) 케이스 수
    retrieval_recall: Optional[float]  # Expected Candidate가 retrieved_docs에 있었는가
    candidate_extraction_hit_rate: Optional[float]  # 그 중 build_candidates() 결과 candidate로도 존재했는가
    final_pass_rate: Optional[float]  # evaluable 케이스 중 최종 status==PASS 비율
    expected_candidate_top1_rate: Optional[float]  # evaluable 케이스 중 최종 추천이 실제로 Expected와 일치하는 비율
    avg_retrieved_documents: float  # 전체 케이스 기준, retrieval 후 중복제거된 문서(candidate) 평균 개수
    avg_candidate_pool_size: float  # 전체 케이스 기준, build_candidates() 결과 후보 평균 개수
    no_match_safety_rate: Optional[float]  # Expected Candidate 없음 케이스 중 최종 status가 PASS로 잘못 나오지 않은 비율


def compute_funnel_summary(k: int, rows: List[Dict[str, Any]]) -> FunnelSummary:
    """rows: scripts/full_retrieval_recall_benchmark.py::run_benchmark()이 만든 특정
    k값의 per-case 결과 dict 목록. Production 코드(retrieve_for_requirement/
    build_candidates/select_best_candidate)가 이미 계산해 넘겨준 값만 집계하며, 이
    함수 자체는 재검색/재계산을 하지 않는다(순수 집계)."""
    total = len(rows)
    evaluable = [r for r in rows if r["evaluable"]]
    no_expected = [r for r in rows if not r["evaluable"]]

    hits = [r for r in evaluable if r["hit"]]
    retrieval_recall = (len(hits) / len(evaluable)) if evaluable else None

    cand_hits = [r for r in evaluable if r.get("candidate_extraction_hit")]
    candidate_extraction_hit_rate = (len(cand_hits) / len(evaluable)) if evaluable else None

    final_pass = [r for r in evaluable if r["final_status"] == "PASS"]
    final_pass_rate = (len(final_pass) / len(evaluable)) if evaluable else None

    top1 = [r for r in evaluable if r["final_matches_expected"]]
    expected_candidate_top1_rate = (len(top1) / len(evaluable)) if evaluable else None

    avg_retrieved_documents = (sum(r["retrieved_unique_doc_count"] for r in rows) / total) if total else 0.0
    avg_candidate_pool_size = (sum(r["candidate_count"] for r in rows) / total) if total else 0.0

    safety_ok = [r for r in no_expected if r["final_status"] != "PASS"]
    no_match_safety_rate = (len(safety_ok) / len(no_expected)) if no_expected else None

    return FunnelSummary(
        k=k,
        n_total_cases=total,
        n_evaluable=len(evaluable),
        n_no_expected=len(no_expected),
        retrieval_recall=retrieval_recall,
        candidate_extraction_hit_rate=candidate_extraction_hit_rate,
        final_pass_rate=final_pass_rate,
        expected_candidate_top1_rate=expected_candidate_top1_rate,
        avg_retrieved_documents=avg_retrieved_documents,
        avg_candidate_pool_size=avg_candidate_pool_size,
        no_match_safety_rate=no_match_safety_rate,
    )
