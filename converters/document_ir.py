"""
PPTX <-> 텍스트 포맷(Markdown/HTML) 변환을 위한 최소 중간 표현(Intermediate
Representation). PPTX를 Markdown과 HTML에 대해 각각 별도 파서로 만들지 않기
위해, "PPTX -> Document IR -> {Markdown, HTML, ...}" 한 방향으로 통일한다.

주의: 이 IR은 임의 PPTX 문서를 사람이 읽기 좋은 텍스트로 "보존"하기 위한
것이며, 위쪽(agent/, renderers/)의 SpecificationSchema/RenderSection과는
별개의 개념이다. (Specification 렌더링 파이프라인과 섞어 쓰지 않는다 —
"포맷 간 반복 변환으로 데이터를 유지하는 구조를 만들지 않는다"는 원칙에 따라
이 IR은 오직 "문서 보존/열람" 목적으로만 쓰고, 이걸 다시 Specification으로
역변환하려면 반드시 LLM 추출(agent.generator.extract_spec_from_document 류)을
거쳐야 한다.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TableIR:
    headers: List[str]
    rows: List[List[str]]


@dataclass
class ImageRef:
    shape_name: str
    width_emu: Optional[int] = None
    height_emu: Optional[int] = None


@dataclass
class SlideIR:
    slide_number: int
    title: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)
    tables: List[TableIR] = field(default_factory=list)
    notes: Optional[str] = None
    images: List[ImageRef] = field(default_factory=list)


@dataclass
class DocumentIR:
    title: Optional[str]
    source_path: str
    slides: List[SlideIR] = field(default_factory=list)
