"""
가장 단순한 어댑터: 환경변수 하나로 템플릿 경로를 지정한다.
renderers/pptx_renderer.render_pptx()가 기본으로 이미 이 동작(PPT_TEMPLATE_PATH)을
내장하고 있으므로, 여러 회사/여러 템플릿을 구분해야 하는 경우가 아니라면 이
어댑터를 굳이 명시적으로 쓸 필요는 없다. 회사별 로직(예: 장비 유형에 따라 다른
템플릿 선택)이 필요해지면 이 파일을 참고해서 새 어댑터를 추가한다.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import TemplateAdapter


class EnvPathAdapter(TemplateAdapter):
    def __init__(self, env_var: str = "PPT_TEMPLATE_PATH"):
        self.env_var = env_var

    def get_template_path(self) -> Optional[str]:
        return os.environ.get(self.env_var) or None
