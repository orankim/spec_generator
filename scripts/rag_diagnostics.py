"""
RAG(빌드 <-> 검색) 독립 진단 스크립트. 사내 PC에서 실제 Ollama가 켜진 상태로 실행한다.

"전극 검사기 AI에서 검색 결과가 0개로 나온다"는 문제를 코드 추측이 아니라 실제 값을
찍어서 확인하기 위한 도구다. 아래를 순서대로 출력/검사한다.

  A. ChromaDB에 실제 document가 들어갔는지 (collection 이름/개수/메타데이터/원문 일부)
  B. build_rag_ollama.py와 agent/spec_retriever.py가 같은 persist directory /
     collection name / embedding model / Ollama host / embedding 차원을 쓰는지
  C. sample_specs/*.md 중 하나를 직접 임베딩 + similarity_search하는 최소 테스트
  D. similarity_search에 별도 score threshold가 걸려있는지 확인 (현재 코드에는 없음 —
     이 스크립트가 실제로 그것을 검증한다)
  E. RequirementSchema 예시로부터 실제 Retriever에 전달되는 query 문자열을 출력
  G. "0~200 μm 측정 범위와 ±1 μm 이하 정확도" 질문으로 최소 1개 이상의 chunk가
     검색되는지 최종 판정

사용법:
    python scripts/rag_diagnostics.py
    python scripts/rag_diagnostics.py --db-path ./chroma_db_specs --query "정확도"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 빌드/검색 독립 진단")
    parser.add_argument("--db-path", default=None, help="점검할 Chroma DB 경로 (기본값: agent.paths.DEFAULT_CHROMA_DB_PATH)")
    parser.add_argument(
        "--query", default="0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘.",
        help="검색 테스트에 쓸 질의 (기본값: 사용자가 보고한 실제 질문)",
    )
    args = parser.parse_args()

    from agent.paths import DEFAULT_CHROMA_DB_PATH, DEFAULT_SAMPLE_SPECS_DIR, resolve_db_path
    from agent.spec_retriever import get_embeddings

    db_path = resolve_db_path(args.db_path)

    # ---------------------------------------------------------------
    # B. 설정 일치 여부
    # ---------------------------------------------------------------
    _section("B. 설정 확인 (빌드 <-> 검색이 동일한 값을 쓰는지)")
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    print(f"OLLAMA_HOST          : {ollama_host}")
    print(f"EMBEDDING_MODEL       : {embedding_model}")
    print(f"CHROMA_DB_PATH(env)   : {os.environ.get('CHROMA_DB_PATH', '(미설정)')}")
    print(f"DEFAULT_CHROMA_DB_PATH: {DEFAULT_CHROMA_DB_PATH}  (agent/paths.py, 저장소 루트 기준)")
    print(f"실제 점검 대상 db_path : {db_path}")
    print(f"DEFAULT_SAMPLE_SPECS_DIR: {DEFAULT_SAMPLE_SPECS_DIR}")
    print(
        "\n주의: build_rag_ollama.py와 agent/spec_retriever.py는 둘 다 "
        "agent.spec_retriever.get_embeddings()/agent.paths.resolve_db_path()만 쓰도록 "
        "통일되어 있으므로(코드 확인됨), 이 스크립트가 계산한 값이 곧 두 스크립트 모두가 "
        "실제로 쓰는 값과 같다."
    )

    if not Path(db_path).exists():
        print(f"\n[FAIL] db_path가 아예 존재하지 않습니다: {db_path}")
        print("       build_rag_ollama.py를 먼저 실행했는지, --db-path를 다른 곳으로 지정하지 않았는지 확인하세요.")
        return 1

    # ---------------------------------------------------------------
    # A. Chroma collection 내용 확인
    # ---------------------------------------------------------------
    _section("A. ChromaDB 내용 확인")
    from langchain_chroma import Chroma

    embeddings = get_embeddings(ollama_host)
    try:
        probe_vec = embeddings.embed_query("연결 테스트")
    except Exception as e:
        print(f"[FAIL] Ollama 임베딩 서버({ollama_host}, model={embedding_model})에 연결할 수 없습니다: {e}")
        print("       Ollama가 켜져 있는지, EMBEDDING_MODEL이 `ollama list`에 실제로 있는지 확인하세요.")
        return 1
    print(f"임베딩 차원(probe)     : {len(probe_vec)}")

    vector_store = Chroma(persist_directory=db_path, embedding_function=embeddings)
    collection = vector_store._collection
    print(f"collection 이름        : {collection.name}")
    count = collection.count()
    print(f"collection document 수 : {count}")

    if count == 0:
        print("\n[FAIL] collection이 비어 있습니다 — 검색이 0개로 나오는 직접적 원인입니다.")
        print("       build_rag_ollama.py --input-dir ... --db-path ... --rebuild 를 다시 실행하고,")
        print(f"       위 'B. 설정 확인'의 db_path({db_path})와 같은 경로에 쓰였는지 확인하세요.")
        return 1

    raw = collection.get(limit=3, include=["metadatas", "documents", "embeddings"])
    print("\n첫 3개 document 메타데이터/원문 일부:")
    for i, (meta, doc_text) in enumerate(zip(raw.get("metadatas", []), raw.get("documents", [])), start=1):
        print(f"  [{i}] metadata: {meta}")
        print(f"      content : {doc_text[:100]!r}")

    stored_embeddings = raw.get("embeddings")
    if stored_embeddings is not None and len(stored_embeddings) > 0:
        stored_dim = len(stored_embeddings[0])
        print(f"\n저장된 embedding 차원   : {stored_dim}")
        if stored_dim != len(probe_vec):
            print(
                f"[FAIL] 저장된 벡터 차원({stored_dim})과 현재 embedding 모델의 차원({len(probe_vec)})이 다릅니다 — "
                "DB를 만들 때와 다른 EMBEDDING_MODEL을 쓰고 있습니다. --rebuild로 다시 만드세요."
            )
            return 1

    all_sources = {m.get("filename") or m.get("source") for m in collection.get(include=["metadatas"])["metadatas"]}
    print(f"\nDB에 포함된 출처 파일 목록 ({len(all_sources)}개): {sorted(s for s in all_sources if s)}")
    if any(".pptx" in (s or "") for s in all_sources):
        print("  (참고: .pptx 출처도 섞여 있습니다 — 의도한 것이 아니면 --rebuild로 .md만 있는 폴더를 다시 색인하세요.)")

    # ---------------------------------------------------------------
    # E. 실제 Retriever에 전달되는 query 확인
    # ---------------------------------------------------------------
    _section("E. RequirementSchema -> 실제 검색 query 변환 확인")
    from agent.schemas import RequirementSchema, RequirementTarget
    from agent.spec_retriever import _build_queries

    sample_requirement = RequirementSchema(
        raw_text=args.query,
        target=RequirementTarget(material="양극"),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    queries = _build_queries(sample_requirement)
    print(f"입력 RequirementSchema(예시): material=양극, inspection_items=[thickness], required_accuracy_um=1.0")
    print(f"생성된 검색 query {len(queries)}개:")
    for q in queries:
        print(f"  - {q!r}")
    print(
        "\n주의: 현재 _build_queries()는 target.material / measurement_principle / "
        "measurement_method / inspection_items만 사용하고, required_accuracy_um이나 "
        "측정 범위(0~200 μm) 같은 구체적 수치는 검색 질의 문자열에 포함되지 않는다. "
        "즉 '0~200 μm ±1 μm' 자체가 아니라 '양극 두께 측정 두께 정확도 두께 분해능' 같은 "
        "의미 기반 질의로 검색된다 — 이것이 의도한 설계인지 확인이 필요하다."
    )

    # ---------------------------------------------------------------
    # C, D, G. 실제 검색 테스트 + threshold 확인 + 최종 판정
    # ---------------------------------------------------------------
    _section("C/D. similarity_search 직접 테스트 (threshold 없음 확인)")
    print(
        "현재 agent/spec_retriever.py는 vector_store.similarity_search(query, k=N)만 쓴다 — "
        "score/threshold로 결과를 걸러내는 코드가 없다(similarity_search_with_relevance_scores나 "
        "search_type='similarity_score_threshold'를 쓰지 않음). 즉 threshold 때문에 결과가 사라지는 "
        "구조가 아니며, 결과가 0개라면 collection 자체가 비어있거나 db_path가 어긋난 것이다."
    )
    print(f"\n질의: {args.query!r}")
    results_with_scores = vector_store.similarity_search_with_score(args.query, k=5)
    if not results_with_scores:
        print("[FAIL] similarity_search가 0개를 반환했습니다 (collection에 문서가 있는데도).")
        return 1
    for i, (doc, score) in enumerate(results_with_scores, start=1):
        source = doc.metadata.get("filename") or doc.metadata.get("source", "?")
        print(f"  [{i}] score(거리, 낮을수록 유사): {score:.4f} | source: {source}")
        print(f"      content: {doc.page_content[:100]!r}")

    _section("G. 최종 판정 — 항목 단위 Retriever(retrieve_for_requirement) 결과")
    from agent.spec_retriever import retrieve_for_requirement

    docs = retrieve_for_requirement(sample_requirement, db_path=db_path, ollama_host=ollama_host, k_per_query=5)
    print(f"retrieve_for_requirement() 결과: {len(docs)}개 chunk")
    for d in docs:
        print(f"  - {d.metadata.get('filename') or d.metadata.get('source')}")

    if len(docs) == 0:
        print("\n[FAIL] 항목 단위 검색도 0개입니다. 위 A/B/C/D/E 결과를 위에서부터 확인하세요.")
        return 1

    print(f"\n[PASS] RAG 검색이 정상 동작합니다 ({len(docs)}개 chunk 검색됨). Agent 전체 파이프라인을 테스트해도 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
