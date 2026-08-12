"""
회사별 PPT 템플릿 연결을 위한 확장 지점.

실제 회사 템플릿 파일(.pptx)은 기밀정보를 포함할 수 있으므로 이 저장소에는
포함하지 않는다(회사 PC에서 PPT_TEMPLATE_PATH 환경변수로 로컬 경로를 지정).
어댑터는 "템플릿 경로를 어떻게 결정할지"와 "생성 후 회사별 후처리가 필요한지"를
표현하는 최소 인터페이스다 — renderers/pptx_renderer.py는 기본적으로
PPT_TEMPLATE_PATH 환경변수만으로도 동작하므로, 지금 당장 어댑터를 구현하지
않아도 된다. 여러 회사/여러 템플릿을 동시에 지원해야 할 때 이 인터페이스를
구현해서 확장한다.
"""
from __future__ import annotations

from typing import Optional


class TemplateAdapter:
    def get_template_path(self) -> Optional[str]:
        """사용할 PPTX 템플릿의 로컬 경로. 없으면 None (템플릿 없이 기본 렌더링)."""
        return None

    def post_process(self, presentation) -> None:
        """PPTX 생성 직후 회사별 후처리(로고 삽입, 워터마크 등)가 필요하면 override."""
        return None
