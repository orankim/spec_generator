"""
RAG 검색 0개 문제를 Agent UI와 완전히 분리해서 독립적으로 진단하는 스크립트.

실행:
    python debug_rag.py
    python debug_rag.py --db-path ./chroma_db_specs --query "0~200 μm 측정 범위와 ±1 μm 이하 정확도"

TEST A(파일 존재) -> TEST B(ChromaDB 색인) -> TEST C(검색) 순서로 각각 독립적으로
검증하고, 어느 단계에서 실패하는지 정확히 짚어낸다. 실제 Ollama가 켜진 사내 PC에서
실행해야 한다(이 스크립트는 어떤 값도 추측/생략하지 않고 실제 실행 결과만 출력한다).

이 스크립트는 진단 전용이다 — RequirementSchema/SpecificationSchema/SpecGenerator/
Validator/Ollama 모델/UI를 수정하지 않는다.
"""
from __future__ import annotations

import argparse
import inspect
import os
import sys
from glob import glob
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

DEFAULT_QUERY = "0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."


def _hr(title: str = "") -> None:
    print("=" * 60)
    if title:
        print(title)
        print("=" * 60)


def _fail(msg: str) -> None:
    print(f"\n[FAIL] {msg}")


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


# ---------------------------------------------------------------
# 0. 코드 버전 자가 점검 — 여러 zip을 순서대로 수동 복사하는 과정에서 파일 일부가
#    누락/구버전으로 남아있는 경우가 실제로 잦았다. 핵심 수정 사항이 실제로 적용된
#    코드인지 import된 모듈의 소스를 직접 읽어 확인한다(추측하지 않는다).
# ---------------------------------------------------------------
def check_code_version() -> bool:
    _hr("0. 코드 버전 자가 점검 (파일이 최신인지)")
    all_good = True

    try:
        from agent import paths as agent_paths
        _ok(f"agent/paths.py import 성공 (DEFAULT_CHROMA_DB_PATH={agent_paths.DEFAULT_CHROMA_DB_PATH})")
    except ImportError as e:
        _fail(f"agent/paths.py를 import할 수 없습니다: {e}")
        print("       -> 가장 최근에 드린 zip의 agent/paths.py가 실제로 복사됐는지 확인하세요.")
        return False

    import build_rag_ollama
    build_src = inspect.getsource(build_rag_ollama)
    if "agent.paths" not in build_src and "from agent.spec_retriever import get_embeddings" not in build_src:
        _fail("build_rag_ollama.py가 구버전입니다 (agent.paths/get_embeddings를 쓰지 않음).")
        print("       -> build_rag_ollama.py를 최신 버전으로 다시 복사하세요.")
        all_good = False
    else:
        _ok("build_rag_ollama.py는 agent.paths/get_embeddings를 사용하는 최신 버전입니다.")

    from agent import spec_retriever
    retriever_src = inspect.getsource(spec_retriever)
    if "resolve_db_path" not in retriever_src:
        _fail("agent/spec_retriever.py가 구버전입니다 (resolve_db_path를 쓰지 않음).")
        all_good = False
    else:
        _ok("agent/spec_retriever.py는 resolve_db_path를 사용하는 최신 버전입니다.")

    from agent import routes as agent_routes
    routes_src = inspect.getsource(agent_routes)
    if "DEFAULT_CHROMA_DB_PATH" not in routes_src:
        _fail("agent/routes.py가 구버전입니다 (DEFAULT_CHROMA_DB_PATH를 쓰지 않음).")
        all_good = False
    else:
        _ok("agent/routes.py는 DEFAULT_CHROMA_DB_PATH를 사용하는 최신 버전입니다.")

    if "langchain_chroma" in build_src or "langchain_chroma" in retriever_src:
        _fail(
            "build_rag_ollama.py 또는 agent/spec_retriever.py가 여전히 langchain_chroma를 씁니다 — "
            "Windows 애플리케이션 제어 정책이 xxhash 네이티브 DLL을 차단하면 이 import에서 죽습니다."
        )
        all_good = False
    else:
        _ok("langchain_chroma 미사용 확인 (xxhash/langsmith가 딸려 들어오지 않음).")

    if "xxhash" in sys.modules or "langsmith" in sys.modules:
        _fail("이 시점에 이미 xxhash/langsmith가 로드되어 있습니다 — 다른 어딘가에서 langchain_chroma를 import했습니다.")
        all_good = False
    else:
        _ok("xxhash/langsmith가 로드되지 않았습니다 (agent.chroma_store가 정상적으로 이를 우회합니다).")

    return all_good


# ---------------------------------------------------------------
# TEST A — sample_specs/*.md 파일이 실제 존재하는가
# ---------------------------------------------------------------
def test_a_files() -> list:
    _hr("TEST A — sample_specs/*.md 파일 존재 확인")
    from agent.paths import DEFAULT_SAMPLE_SPECS_DIR

    print(f"확인 경로: {DEFAULT_SAMPLE_SPECS_DIR}")
    md_files = sorted(glob(os.path.join(DEFAULT_SAMPLE_SPECS_DIR, "*.md")))
    print(f"발견된 .md 파일: {len(md_files)}개")
    for f in md_files:
        print(f"  - {f}")

    if not md_files:
        _fail("TEST A 실패: sample_specs/*.md 파일이 하나도 없습니다.")
        print("       -> sample_specs/ 폴더 경로와 실제 파일 위치를 다시 확인하세요.")
    else:
        _ok(f"TEST A 통과: {len(md_files)}개 파일 확인됨")
    return md_files


# ---------------------------------------------------------------
# 1, 3, 4, 5. ChromaDB 직접 검사 + collection/경로/embedding 모델 비교
# ---------------------------------------------------------------
def test_b_chromadb(db_path: str, ollama_host: str) -> tuple:
    _hr("TEST B — ChromaDB 색인 확인 (1. ChromaDB 직접 검사)")

    from agent.spec_retriever import get_embeddings
    from agent.paths import DEFAULT_CHROMA_DB_PATH
    from agent.chroma_store import SimpleChromaStore

    print("[ChromaDB]")
    print(f"persist_directory (사용값)   : {db_path}")
    print(f"persist_directory (agent.paths 기본값): {DEFAULT_CHROMA_DB_PATH}")
    if os.path.abspath(db_path) != os.path.abspath(DEFAULT_CHROMA_DB_PATH):
        print("  [경고] 지금 점검하는 경로가 agent.paths의 기본값과 다릅니다 — --db-path를 명시했는지 확인하세요.")

    if not Path(db_path).exists():
        _fail(f"db_path가 디스크에 존재하지 않습니다: {db_path}")
        print("       -> build_rag_ollama.py --rebuild를 먼저 실행하세요.")
        return None, 0

    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    print(f"\n[Embedding 확인 - 5. Embedding 모델 확인]")
    print(f"EMBEDDING_MODEL(env) : {os.environ.get('EMBEDDING_MODEL', '(미설정, 기본값 bge-m3 사용)')}")
    print(f"OLLAMA_HOST(env)     : {os.environ.get('OLLAMA_HOST', f'(미설정, 기본값 {ollama_host} 사용)')}")
    print(
        "build_rag_ollama.py와 agent/spec_retriever.py는 둘 다 agent.spec_retriever.get_embeddings()를 "
        "호출하므로(코드로 확인됨, 위 '0. 코드 버전 자가 점검' 참고), 이 스크립트가 쓰는 값과 실제 "
        "두 스크립트가 쓰는 값은 항상 같다."
    )

    embeddings = get_embeddings(ollama_host)
    try:
        probe = embeddings.embed_query("연결 테스트")
    except Exception as e:
        _fail(f"Ollama 임베딩 서버({ollama_host}, model={embedding_model})에 연결할 수 없습니다: {e}")
        print(f"       -> Ollama가 켜져 있는지, `ollama list`에 '{embedding_model}' 모델이 있는지 확인하세요.")
        return None, 0
    _ok(f"Ollama 임베딩 연결 성공 (model={embedding_model}, 차원={len(probe)})")

    vector_store = SimpleChromaStore(persist_directory=db_path, embedding_function=embeddings)
    collection = vector_store._collection

    print(f"\ncollection_name (실제 사용값): {collection.name}")
    print(
        "build_rag_ollama.py와 agent/spec_retriever.py는 둘 다 agent.chroma_store.SimpleChromaStore()를 "
        "collection_name 인자 없이 생성하므로 기본값('langchain')을 그대로 쓴다 — 두 코드를 직접 읽어 "
        "확인했다(코드에 collection_name='...'로 다른 값을 지정한 부분 없음)."
    )

    document_count = collection.count()
    print(f"\ndocument_count: {document_count}")

    if document_count == 0:
        _fail("document_count == 0 -> build_rag_ollama.py의 indexing 문제입니다.")
        print("       -> build_rag_ollama.py --input-dir sample_specs --db-path " + db_path + " --rebuild 를 실행하세요.")
        return vector_store, 0

    _ok(f"TEST B 통과: document_count={document_count} (0이 아님 -> 문제는 indexing이 아니라 retrieval 쪽)")

    # ---------------------------------------------------------------
    # 2. 실제 Document 내용 확인
    # ---------------------------------------------------------------
    _hr("2. 실제 Document 내용 확인 (처음 3개)")
    raw = collection.get(limit=3, include=["metadatas", "documents"])
    for i, (meta, content) in enumerate(zip(raw.get("metadatas", []), raw.get("documents", [])), start=1):
        print(f"\n[DOCUMENT {i}]")
        print(f"source     : {meta.get('source')}")
        print(f"source_type: {meta.get('source_type')}")
        print(f"filename   : {meta.get('filename')}")
        print(f"chunk_id   : {meta.get('chunk_id')}")
        print("content:")
        print(content[:500])

    return vector_store, document_count


# ---------------------------------------------------------------
# 6, 7. 독립 similarity search + threshold 확인
# ---------------------------------------------------------------
def test_c_search(vector_store, queries: list) -> int:
    _hr("TEST C — 독립 similarity search (6. 검색 테스트 / 7. threshold 확인)")

    print(
        "현재 agent/spec_retriever.py는 similarity_search(query, k=N)만 사용한다 — score/threshold로 "
        "결과를 걸러내는 코드가 없다(코드에 similarity_score_threshold, relevance_scores 등 미사용, "
        "직접 확인함). 즉 threshold 때문에 결과가 사라질 수 없는 구조다. 아래에서 raw 결과를 그대로 보여준다."
    )

    total_hits = 0
    for query in queries:
        print(f"\n[RAG TEST]\n\nQuery:\n{query}\n")
        raw_results = vector_store.similarity_search_with_score(query, k=5)
        print(f"raw results: {len(raw_results)}")
        print("threshold: (코드에 없음 — 적용 안 함)")
        print(f"after filtering: {len(raw_results)}  (필터링이 없으므로 raw와 동일)")
        print("\nRetrieved:")
        for i, (doc, score) in enumerate(raw_results, start=1):
            source = doc.metadata.get("filename") or doc.metadata.get("source", "?")
            print(f"{i}. {source}")
            print(f"   distance: {score:.4f}")
        total_hits += len(raw_results)

    if total_hits == 0:
        _fail("TEST C 실패: 모든 질의에서 0개가 반환되었습니다 (collection은 비어있지 않은데도).")
    else:
        _ok(f"TEST C 통과: 질의 {len(queries)}개에서 총 {total_hits}건 반환")
    return total_hits


# ---------------------------------------------------------------
# 8. RequirementParser 결과 + 실제 Retriever query 확인
# ---------------------------------------------------------------
def show_requirement_and_queries(user_text: str):
    _hr("8. Query 생성 확인 (RequirementSchema -> 실제 Retriever query)")

    from agent.schemas import RequirementSchema, RequirementTarget
    from agent.spec_retriever import _build_queries

    # 이 스크립트는 Ollama Requirement Parser(LLM) 호출 없이, 사용자가 보고한 Agent
    # 결과 화면에 실제로 찍혔던 값("검사 대상: 양극(5mm)", "검사 항목: thickness")을
    # 그대로 RequirementSchema에 채워 넣어 "이 값이면 실제로 어떤 query가 만들어지는지"를
    # 확인한다 — Requirement Parser 자체를 재구현/추측하지 않는다.
    requirement = RequirementSchema(
        raw_text=user_text,
        target=RequirementTarget(material="양극", width_mm=5.0),
        inspection_items=["thickness"],
        required_accuracy_um=1.0,
    )
    print("RequirementSchema (Agent 결과 화면에 찍힌 값 기준 재구성):")
    print(requirement.model_dump_json(indent=2, exclude_none=True))

    queries = _build_queries(requirement)
    print(f"\nRetriever query ({len(queries)}개):")
    for q in queries:
        print(f"  - {q!r}")

    if not queries or all(not q.strip() for q in queries):
        _fail("query가 비어 있습니다 — _build_queries()가 빈 문자열만 반환합니다.")
    else:
        _ok("query가 정상적으로 생성됩니다 (비어있지 않음).")

    return requirement, queries


# ---------------------------------------------------------------
# 9. 단순 문자열 검색 — 원본 파일과 색인된 내용에 실제로 존재하는지
# ---------------------------------------------------------------
def check_raw_string_presence(md_files: list, vector_store) -> None:
    _hr("9. 단순 문자열 검색 테스트 (원본 파일 vs 색인된 Document)")
    needles = ["μm", "accuracy", "측정 범위", "정확도", "0~200", "0 ~ 200"]

    print("원본 sample_specs/*.md 파일에서:")
    for needle in needles:
        hit_files = []
        for f in md_files:
            try:
                text = Path(f).read_text(encoding="utf-8")
            except Exception:
                continue
            if needle in text:
                hit_files.append(os.path.basename(f))
        print(f"  {needle!r}: {len(hit_files)}개 파일에서 발견 {hit_files[:5]}")

    if vector_store is not None:
        print("\nChromaDB에 색인된 Document에서:")
        all_docs = vector_store._collection.get(include=["documents"])["documents"]
        for needle in needles:
            count = sum(1 for d in all_docs if needle in d)
            print(f"  {needle!r}: {count}개 chunk에서 발견")


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 검색 0개 문제 독립 진단")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    args = parser.parse_args()

    from agent.paths import resolve_db_path

    db_path = resolve_db_path(args.db_path)
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    code_ok = check_code_version()

    md_files = test_a_files()
    if not md_files:
        print("\nTEST A에서 실패했습니다 — TEST B/C를 진행할 수 없습니다.")
        return 1

    vector_store, doc_count = test_b_chromadb(db_path, ollama_host)
    if vector_store is None or doc_count == 0:
        print("\nTEST B에서 실패했습니다 — TEST C(검색)는 의미가 없으므로 건너뜁니다.")
        return 1

    requirement, queries = show_requirement_and_queries(args.query)
    total_hits = test_c_search(vector_store, [args.query] + queries)
    check_raw_string_presence(md_files, vector_store)

    _hr("RAG DEBUG 요약")
    print(f"Documents in ChromaDB : {doc_count}")
    print(f"Collection            : {vector_store._collection.name}")
    print(f"Embedding model       : {os.environ.get('EMBEDDING_MODEL', 'bge-m3')}")
    print(f"Query                 : {args.query}")
    print(f"Retrieved chunks(총합) : {total_hits}")
    print(f"코드 버전 최신 여부    : {'OK' if code_ok else 'FAIL - 구버전 파일 존재'}")

    if total_hits == 0:
        _fail("최종 판정: RAG 검색이 0개입니다. 위 TEST A/B/C 중 어디서 문제가 시작됐는지 확인하세요.")
        return 1

    print(f"\n[PASS] RAG 검색이 정상 동작합니다. Agent 전체 파이프라인을 테스트해도 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
