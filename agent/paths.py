"""
저장소 루트 기준 경로 상수.

문제: `db_path: str = "./chroma_db_specs"` 같은 상대경로 기본값은 "그 프로세스를
실행한 현재 작업 디렉터리(cwd)"를 기준으로 해석된다. `build_rag_ollama.py --rebuild`를
프로젝트 루트에서 실행하고, `python -m uvicorn main:app`은 다른 cwd(예: 상위 폴더,
서비스로 등록된 작업 디렉터리 등)에서 실행하면 — 코드는 똑같이 "./chroma_db_specs"를
가리키지만 실제로는 서로 다른 두 개의 디스크 경로가 되어, 빌드는 A에, 검색은 텅 빈 B에
접근하게 된다. 이 경우 예외 없이 조용히 "검색 결과 0개"만 나오므로 원인을 찾기 매우
어렵다 — 실제로 이번에 재현/수정한 문제의 근본 원인이다.

해결: cwd에 의존하지 않고 이 파일(`agent/paths.py`)의 위치를 기준으로 저장소 루트를
계산한다. 빌드(build_rag_ollama.py)와 검색(agent/spec_retriever.py 등)이 어떤 위치에서
실행되든 항상 같은 절대경로를 가리키게 된다. `CHROMA_DB_PATH` 환경변수로 명시적으로
오버라이드하면 그 값이 우선한다(예: 여러 개의 DB를 병행 운영하고 싶을 때).
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CHROMA_DB_PATH = str(REPO_ROOT / "chroma_db_specs")
DEFAULT_SAMPLE_SPECS_DIR = str(REPO_ROOT / "sample_specs")


def resolve_db_path(db_path: str | None = None) -> str:
    """
    명시적으로 db_path가 주어지면 그것을(상대경로라도 호출자의 의도를 존중해 그대로)
    쓰고, 없으면 CHROMA_DB_PATH 환경변수 -> 저장소 루트 기준 기본값 순으로 정한다.
    """
    if db_path:
        return db_path
    return os.environ.get("CHROMA_DB_PATH", DEFAULT_CHROMA_DB_PATH)
