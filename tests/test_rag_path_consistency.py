"""
회귀 테스트: build_rag_ollama.py(빌드)와 agent/spec_retriever.py(검색)의 기본
Chroma DB 경로가 프로세스의 현재 작업 디렉터리(cwd)와 무관하게 항상 같은 절대경로를
가리켜야 한다.

배경: 두 스크립트 모두 예전에는 `db_path: str = "./chroma_db_specs"`라는 *상대경로*
기본값을 썼다. `python build_rag_ollama.py --rebuild`를 프로젝트 루트에서 실행하고
`python -m uvicorn main:app`을 다른 작업 디렉터리에서 실행하면(흔한 실수 — 서비스로
등록하거나 다른 터미널/IDE 설정에서 실행할 때), 코드는 똑같이 "./chroma_db_specs"를
쓰지만 실제로는 서로 다른 두 디스크 경로가 되어 빌드는 A에, 검색은 텅 빈 B에 접근한다.
예외 없이 조용히 "검색 결과 0개"만 나와 원인을 찾기 매우 어려웠다 — 실제로 재현/확인된
케이스이며, agent/paths.py로 두 기본값을 저장소 루트 기준 절대경로로 통일해 고쳤다.
"""
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_default_db_path_is_absolute_and_repo_rooted():
    from agent.paths import DEFAULT_CHROMA_DB_PATH, DEFAULT_SAMPLE_SPECS_DIR

    assert Path(DEFAULT_CHROMA_DB_PATH).is_absolute()
    assert Path(DEFAULT_SAMPLE_SPECS_DIR).is_absolute()
    assert Path(DEFAULT_CHROMA_DB_PATH) == _REPO_ROOT / "chroma_db_specs"
    assert Path(DEFAULT_SAMPLE_SPECS_DIR) == _REPO_ROOT / "sample_specs"


def test_build_and_retrieval_default_db_path_identical_regardless_of_cwd(tmp_path):
    """
    build_rag_ollama.py를 임의의 cwd(A)에서, agent.spec_retriever를 다른 cwd(B)에서
    "import만" 해도 두 default 경로 문자열이 완전히 같은 값으로 계산되는지 확인한다
    (실제 색인/검색까지는 Ollama가 필요하므로, 여기서는 "어느 경로를 가리키는가"만
    cwd 독립적으로 검증한다 — tests/test_markdown_rag.py가 실제 색인/검색 자체는
    이미 커버한다).
    """
    dir_a = tmp_path / "somewhere_else_A"
    dir_b = tmp_path / "totally_different_B"
    dir_a.mkdir()
    dir_b.mkdir()

    script = (
        "import sys; sys.path.insert(0, {repo!r}); "
        "from agent.paths import DEFAULT_CHROMA_DB_PATH; print(DEFAULT_CHROMA_DB_PATH)"
    ).format(repo=str(_REPO_ROOT))

    out_a = subprocess.run([sys.executable, "-c", script], cwd=str(dir_a), capture_output=True, text=True, timeout=15)
    out_b = subprocess.run([sys.executable, "-c", script], cwd=str(dir_b), capture_output=True, text=True, timeout=15)

    assert out_a.returncode == 0, out_a.stderr
    assert out_b.returncode == 0, out_b.stderr
    path_from_a = out_a.stdout.strip()
    path_from_b = out_b.stdout.strip()

    assert path_from_a == path_from_b, (
        f"cwd={dir_a}에서 계산된 경로({path_from_a})와 cwd={dir_b}에서 계산된 경로"
        f"({path_from_b})가 다릅니다 — 여전히 cwd에 의존하고 있습니다."
    )
    assert path_from_a == str(_REPO_ROOT / "chroma_db_specs")


def test_env_var_override_still_wins_over_repo_root_default(monkeypatch):
    from agent.paths import resolve_db_path

    monkeypatch.setenv("CHROMA_DB_PATH", "/custom/override/path")
    assert resolve_db_path(None) == "/custom/override/path"
    monkeypatch.delenv("CHROMA_DB_PATH", raising=False)


def test_explicit_db_path_argument_still_wins_over_default():
    from agent.paths import resolve_db_path

    assert resolve_db_path("./explicit_relative_path") == "./explicit_relative_path"
