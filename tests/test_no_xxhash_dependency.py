"""
회귀 테스트: RAG 핵심 경로(build_rag_ollama.py / agent/spec_retriever.py / main.py)를
import해도 xxhash/langsmith가 로드되면 안 된다.

배경: langchain_chroma를 import하면 langchain_core.outputs.run_info ->
langchain_core.runnables.schema -> langchain_core.tracers.context -> langsmith ->
xxhash 순으로 전부 로드된다. LangSmith는 이 프로젝트가 전혀 쓰지 않는 트레이싱
기능인데도 그렇다. 사내 Windows PC의 애플리케이션 제어 정책이 xxhash의 네이티브
DLL(_xxhash)을 차단하면 `python build_rag_ollama.py`가 아예 뜨지 못했다 —
agent/chroma_store.py(chromadb 직접 사용)로 대체해서 고쳤다. 이 테스트는 각 모듈을
별도 서브프로세스에서 단독 import해서, xxhash/langsmith가 로드되지 않는지 확인한다
(서브프로세스를 쓰는 이유: 이미 이 테스트 세션에서 다른 테스트가 langchain_chroma를
import했다면 sys.modules에 남아있어 오탐이 나므로, 완전히 새 프로세스에서 확인해야
정확하다).
"""
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_CHECK_SCRIPT = """
import sys
{import_line}
blocked = [m for m in ("xxhash", "langsmith") if m in sys.modules]
print("BLOCKED:" + ",".join(blocked) if blocked else "CLEAN")
"""


def _run_isolated_import(import_line: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT.format(import_line=import_line)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"import 자체가 실패했습니다.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return result.stdout.strip()


def test_build_rag_ollama_does_not_import_xxhash():
    output = _run_isolated_import("import build_rag_ollama")
    assert output == "CLEAN", f"build_rag_ollama.py import 시 xxhash/langsmith가 로드됩니다: {output}"


def test_agent_spec_retriever_does_not_import_xxhash():
    output = _run_isolated_import("from agent import spec_retriever")
    assert output == "CLEAN", f"agent/spec_retriever.py import 시 xxhash/langsmith가 로드됩니다: {output}"


def test_agent_chroma_store_does_not_import_xxhash():
    output = _run_isolated_import("from agent.chroma_store import SimpleChromaStore")
    assert output == "CLEAN", f"agent/chroma_store.py import 시 xxhash/langsmith가 로드됩니다: {output}"


def test_main_module_does_not_import_xxhash():
    """python main.py(웹 서버) 자체를 띄우는 경로도 xxhash를 건드리면 안 된다."""
    output = _run_isolated_import("import main")
    assert output == "CLEAN", f"main.py import 시 xxhash/langsmith가 로드됩니다: {output}"
