"""converters/pptx_to_markdown.py 테스트.

python-pptx로 PPTX를 즉석에서 만들어 변환기에 넣고, 슬라이드 제목/본문 텍스트/표/
노트가 Markdown으로 올바르게 옮겨지는지 확인한다. 외부 네트워크나 LLM 호출 없이
전부 로컬에서 동작해야 하므로, 이 테스트도 별도 서버/모델 없이 항상 실행 가능해야
한다.
"""
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx")

from pptx.util import Inches  # noqa: E402

from converters.pptx_to_markdown import convert_pptx_file, convert_pptx_to_markdown  # noqa: E402


def _build_sample_pptx(path: Path) -> Path:
    prs = pptx.Presentation()

    # Slide 1: 제목 + 본문 텍스트(불릿)
    layout = prs.slide_layouts[1]  # Title and Content
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = "전극 검사기 사양"
    body = slide.placeholders[1]
    tf = body.text_frame
    tf.text = "폭 800mm 이상"
    p2 = tf.add_paragraph()
    p2.text = "정확도 ±1um"
    p2.level = 1

    notes_slide = slide.notes_slide
    notes_slide.notes_text_frame.text = "이 슬라이드는 초안입니다."

    # Slide 2: 표(사양 데이터)
    blank_layout = prs.slide_layouts[6]
    slide2 = prs.slides.add_slide(blank_layout)
    rows, cols = 2, 2
    table_shape = slide2.shapes.add_table(rows, cols, Inches(1), Inches(1), Inches(4), Inches(1))
    table = table_shape.table
    table.cell(0, 0).text = "항목"
    table.cell(0, 1).text = "값"
    table.cell(1, 0).text = "정확도"
    table.cell(1, 1).text = "±1um"

    prs.save(str(path))
    return path


@pytest.fixture()
def sample_pptx(tmp_path: Path) -> Path:
    return _build_sample_pptx(tmp_path / "sample.pptx")


def test_slide_title_becomes_heading(sample_pptx: Path):
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    assert "## Slide 1: 전극 검사기 사양" in md


def test_body_text_becomes_bullet_list(sample_pptx: Path):
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    assert "- 폭 800mm 이상" in md
    assert "  - 정확도 ±1um" in md  # level=1은 들여쓰기됨


def test_notes_are_included(sample_pptx: Path):
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    assert "**Notes:**" in md
    assert "> 이 슬라이드는 초안입니다." in md


def test_table_becomes_markdown_table(sample_pptx: Path):
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    assert "| 항목 | 값 |" in md
    assert "|---|---|" in md
    assert "| 정확도 | ±1um |" in md


def test_title_is_not_duplicated_in_body(sample_pptx: Path):
    """slide.shapes.title은 호출마다 새 래퍼 객체를 반환하므로, 이전에는 identity(`is`)
    비교가 항상 실패해 제목 도형이 본문에도 한 번 더 불릿으로 찍히는 회귀가 있었다."""
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    assert md.count("전극 검사기 사양") == 1


def test_slide_order_is_preserved(sample_pptx: Path):
    md = convert_pptx_to_markdown(sample_pptx, extract_images=False)
    slide1_idx = md.index("## Slide 1")
    slide2_idx = md.index("## Slide 2")
    assert slide1_idx < slide2_idx


def test_convert_pptx_file_writes_output(tmp_path: Path, sample_pptx: Path):
    out_path = tmp_path / "converted.md"
    result_path = convert_pptx_file(sample_pptx, out_path, extract_images=False)
    assert result_path == out_path
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "전극 검사기 사양" in content


def test_convert_pptx_file_default_output_path(sample_pptx: Path):
    result_path = convert_pptx_file(sample_pptx, extract_images=False)
    assert result_path == sample_pptx.with_suffix(".md")
    assert result_path.exists()


def test_no_network_or_external_api_import():
    """외부 API 클라이언트(openai 등)를 import하지 않는지 소스 레벨로 확인."""
    source = Path("converters/pptx_to_markdown.py").read_text(encoding="utf-8")
    for forbidden in ("openai", "requests", "httpx", "urllib.request", "socket"):
        assert forbidden not in source, f"외부 통신 관련 모듈({forbidden})을 사용하면 안 됨"
