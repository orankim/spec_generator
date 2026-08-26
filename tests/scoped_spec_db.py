"""
일부 회귀 테스트는 특정 실제 사양서(예: SPEC-001.md)가 sample_specs/ 전체
corpus에서 "가장 적합한 후보"로 고유하게 선택되는 것을 전제로 작성되었다.
SPEC-011.md ~ SPEC-050.md(40개)가 추가되면서, 그 전제는 corpus 전체 기준으로는
더 이상 성립하지 않는다 — 오히려 여러 신규 장비가 같은 hard requirement를 동등하게
(혹은 더 잘) 만족하는 것이 이 데이터셋의 설계 의도다(Ground Truth 기반 경쟁
관계, 요청서 11절).

이 헬퍼는 그런 테스트가 검증하려는 대상(필드 전파/판정/재조정 로직 자체)은 그대로
둔 채, "corpus 전체에서 유일하게 이겨야 한다"는 더 이상 성립하지 않는 전제만
제거한다 — 필요한 실제 파일(sample_specs/의 원본, 복사본이며 원본은 건드리지
않음)만 골라 독립된 임시 디렉터리에 격리된 벡터 DB를 만든다.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_SPECS_DIR = _REPO_ROOT / "sample_specs"


def build_scoped_vector_db(tmp_path: Path, spec_filenames: List[str], db_name: str = "scoped_chroma_db") -> str:
    """tmp_path 아래에 spec_filenames만 복사한 sample_specs 폴더를 만들고, 그
    폴더만으로 새 벡터 DB를 빌드해 db_path를 반환한다. sample_specs/ 원본은
    읽기만 하고 전혀 수정하지 않는다."""
    from build_rag_ollama import build_vector_db

    scoped_specs_dir = tmp_path / "scoped_sample_specs"
    scoped_specs_dir.mkdir(exist_ok=True)
    for filename in spec_filenames:
        shutil.copyfile(_SAMPLE_SPECS_DIR / filename, scoped_specs_dir / filename)

    db_path = str(tmp_path / db_name)
    build_vector_db(str(scoped_specs_dir), db_path, rebuild=True)
    return db_path
