"""
Phase 8 — RAG 구조 결정(docs/RAG_STRUCTURE_DECISION.md) 회귀 가드.

QUOTE 데이터가 실수로 SPEC RAG 인덱싱 대상에 섞여 들어가지 않는지 확인한다.
build_rag_ollama.build_vector_db()는 --input-dir 안의 *.md를 전부 인덱싱하므로,
sample_quotes/를 절대 그 인자로 넘기면 안 된다 — 이 테스트는 "실수로 넘겼을 때"가
아니라 "기본 설정이 안전한가"를 확인한다.
"""
from __future__ import annotations

from pathlib import Path

from agent.paths import DEFAULT_SAMPLE_SPECS_DIR

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_default_sample_specs_dir_does_not_point_at_quotes():
    assert Path(DEFAULT_SAMPLE_SPECS_DIR).resolve() == (_REPO_ROOT / "sample_specs").resolve()
    assert "quote" not in str(DEFAULT_SAMPLE_SPECS_DIR).lower()


def test_sample_quotes_and_sample_specs_are_disjoint_directories():
    specs_dir = (_REPO_ROOT / "sample_specs").resolve()
    quotes_dir = (_REPO_ROOT / "sample_quotes").resolve()
    assert specs_dir != quotes_dir
    assert not str(quotes_dir).startswith(str(specs_dir))
    assert not str(specs_dir).startswith(str(quotes_dir))


def test_quote_parser_never_touches_chroma():
    """agent/quote_parser.py가 chromadb/langchain 등 벡터 검색 관련 모듈을 전혀
    import하지 않는지 확인한다 — QUOTE 조회가 파일명 기반 직접 조회임을 코드
    수준에서도 보장한다."""
    import ast

    source = (_REPO_ROOT / "agent" / "quote_parser.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = ("chromadb", "chroma_store", "langchain")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for n in names:
            assert not any(f in n for f in forbidden), f"quote_parser.py가 {n}을 import합니다 — QUOTE 조회는 벡터 검색이 아니어야 합니다."
