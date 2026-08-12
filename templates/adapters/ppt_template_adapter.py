"""
PPTTemplateAdapter — Specification -> PPTX 렌더링의 최상위 확장 지점.

templates/adapters/base.py의 TemplateAdapter(경로 탐색 + post_process 후킹)보다 상위
레벨의 인터페이스다. TemplateAdapter는 "템플릿 경로를 어떻게 결정할지"와 "생성 후
후처리가 필요한지"만 표현하고, 실제 렌더링은 항상 renderers/pptx_renderer.render_pptx()가
담당했다. 반면 PPTTemplateAdapter는 "Specification + 템플릿 경로 + 출력 경로가 주어지면
PPTX 파일 하나를 통째로 만들어낸다"는 한 개의 메서드(render)로 표현되는, 렌더링 자체를
교체할 수 있는 지점이다.

이 인터페이스가 필요한 경우: 회사 템플릿의 슬라이드 구조가 python-pptx의 일반적인
표/텍스트박스 채우기로는 표현할 수 없는 특수한 형태(예: 지정된 명명된 도형에만 값을
넣어야 함, 매크로가 있는 .pptm, 사내 전용 렌더링 라이브러리 사용)일 때다. 지금 당장은
DefaultPPTTemplateAdapter(기존 renderers/pptx_renderer.render_pptx()를 그대로 호출)만으로
충분하며, 이 인터페이스를 새로 구현하지 않아도 파이프라인은 정상 동작한다.

TemplateAdapter와의 관계: DefaultPPTTemplateAdapter.render()는 내부적으로
render_pptx(template_path=...)를 호출하고, render_pptx()는 여전히 TemplateAdapter/
EnvPathAdapter가 표현하는 "PPT_TEMPLATE_PATH 환경변수" 관례를 그대로 따른다. 즉
PPTTemplateAdapter는 TemplateAdapter를 대체하지 않고 그 위에 얹히는 상위 계층이다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.schemas import SpecificationSchema


class PPTTemplateAdapter:
    """회사별 PPTX 렌더링 구현체가 상속해서 override하는 기본 인터페이스."""

    def render(self, specification: "SpecificationSchema", template_path: str, output_path: str) -> str:
        """
        specification을 template_path의 회사 템플릿에 채워 output_path에 PPTX를 저장하고,
        output_path를 반환한다. template_path가 실제로 존재하지 않을 수도 있다는 전제로
        구현해야 한다(사내 PC 밖에서는 템플릿 파일 자체가 없을 수 있음) — 그 경우 어떻게
        동작할지(예: 기본 PPTX로 폴백)는 구현체의 책임이다.
        """
        raise NotImplementedError


class DefaultPPTTemplateAdapter(PPTTemplateAdapter):
    """
    기본 구현. renderers/pptx_renderer.render_pptx()를 그대로 위임한다 — template_path가
    없거나 존재하지 않으면 render_pptx() 자체의 폴백 규칙(템플릿 없이 기본 PPTX 생성)이
    적용된다.
    """

    def render(self, specification: "SpecificationSchema", template_path: str, output_path: str) -> str:
        from renderers.pptx_renderer import render_pptx

        return render_pptx(specification, output_path=output_path, template_path=template_path)
