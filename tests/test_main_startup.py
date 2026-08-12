"""
회귀 테스트: template.pptx/template_electrode.pptx가 없어도 `python main.py`
(정확히는 `import main`)가 죽지 않아야 한다.

배경: PPTX 템플릿 파일은 회사 정책상 git에 커밋하지 않으므로, 저장소를 새로
클론한 직후에는 항상 이 파일들이 없는 상태다. main.py가 모듈 로드 시점에
PPTXBuilder(template_path="template.pptx")를 즉시 생성하면 FileNotFoundError로
서버 자체가 뜨지 못한다 — 실제로 템플릿이 필요한 "/api/generate-spec" 호출
시점까지 생성을 미뤄야 한다(agent/routes.py의 ElectrodeSpecPPTXBuilder가
이미 쓰는 지연 생성 패턴과 동일).
"""
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_FILES = ["template.pptx", "template_electrode.pptx"]


def test_main_importable_without_pptx_templates():
    moved = []
    try:
        for name in _TEMPLATE_FILES:
            src = _REPO_ROOT / name
            if src.exists():
                dst = _REPO_ROOT / (name + ".bak_test")
                src.rename(dst)
                moved.append((src, dst))

        result = subprocess.run(
            [sys.executable, "-c", "import main; print('MAIN_IMPORT_OK')"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "MAIN_IMPORT_OK" in result.stdout, (
            f"template.pptx 없이 `import main`이 실패했습니다.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert result.returncode == 0, f"exit code {result.returncode}\nstderr:\n{result.stderr}"
        assert "FileNotFoundError" not in result.stderr
    finally:
        for src, dst in moved:
            dst.rename(src)
