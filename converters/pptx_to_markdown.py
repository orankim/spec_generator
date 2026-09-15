"""
PPTX(PowerPoint) 사양서 -> 범용 Markdown 변환기.

microsoft/markitdown의 PptxConverter가 하는 일(슬라이드 텍스트/표/이미지/노트를
순서대로 Markdown으로 직렬화)을 참고해서 만들었지만, markitdown 패키지 자체를
의존성으로 추가하지 않는다. markitdown은 이미지 설명(캡셔닝)에 OpenAI 등 외부
LLM API를 선택적으로 쓸 수 있게 설계돼 있는데, 이 프로젝트는 회사 폐쇄망(외부
API 호출 불가) 환경에서 동작해야 하므로 그 경로 자체를 아예 갖지 않는 것이
안전하다. 대신 이미 requirements.txt에 있는 python-pptx만으로, 네트워크 호출
없이 전부 로컬에서 변환한다.

이 변환기가 만드는 Markdown은 표준 Specification 포맷(docs/
SPECIFICATION_MARKDOWN_FORMAT.md, converters/markdown_to_spec.py가 파싱하는
포맷)이 아니다 — PPTX 원본 슬라이드 구조를 최대한 그대로 옮겨 적은 "1차 변환"
결과물이다. 이렇게 나온 .md를 사람이 검토/정리해서 sample_specs/ 표준 포맷으로
옮기거나, build_rag_ollama.py의 --input-dir에 그대로 넣어 RAG 색인 원본으로
쓰는 용도다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Union

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

_CELL_NEWLINE_RE = re.compile(r"\r?\n")


def _escape_cell(text: str) -> str:
    """Markdown 표 셀 안에서 파이프(|)와 줄바꿈이 표를 깨뜨리지 않도록 이스케이프."""
    text = _CELL_NEWLINE_RE.sub("<br>", text.strip())
    return text.replace("|", "\\|")


def _resolve_merged_grid(table) -> List[List[str]]:
    """병합된 셀(예: '구분' 열이 여러 행에 걸쳐 세로 병합)을 실제 값으로 채운
    2차원 그리드를 만든다.

    python-pptx는 병합 영역에서 원본(origin) 셀 외의 칸은 항상 빈 텍스트를
    반환한다(is_spanned=True). 그대로 표로 옮기면 "구분" 같은 병합 열이 첫
    행에서만 값이 보이고 나머지 행은 빈 칸이 되어, 각 행이 어떤 구분/항목에
    속하는지 알 수 없는 표가 된다 — 사양서 표에서는 각 행이 독립적인 사양
    항목이어야 하므로 원본 셀 값을 병합 범위 전체에 채워 넣는다.
    """
    n_rows = len(table.rows)
    n_cols = len(table.columns)
    grid: List[List[str]] = [["" for _ in range(n_cols)] for _ in range(n_rows)]

    for r in range(n_rows):
        for c in range(n_cols):
            cell = table.cell(r, c)
            if cell.is_spanned:
                continue  # origin 셀 처리 시 함께 채워짐
            text = cell.text.strip()
            if cell.is_merge_origin and (cell.span_height > 1 or cell.span_width > 1):
                # PowerPoint에서 이미 값이 들어간 셀들을 나중에 병합하면(예: "H/W"를
                # 5개 행에 각각 타이핑한 뒤 세로 병합), 병합된 셀의 텍스트는 그 값들이
                # 줄바꿈으로 이어붙은 "H/W\nH/W\nH/W..."가 된다. 병합 전 각 줄이
                # 같은 라벨의 반복이었을 뿐이므로, 완전히 동일한 줄이 반복되면 한
                # 번만 남긴다(순서는 유지, 서로 다른 줄은 그대로 보존).
                text = "\n".join(dict.fromkeys(text.split("\n")))
                for i in range(r, r + cell.span_height):
                    for j in range(c, c + cell.span_width):
                        grid[i][j] = text
            else:
                grid[r][c] = text

    return grid


def _table_to_markdown(table) -> str:
    grid = _resolve_merged_grid(table)
    if not grid:
        return ""

    lines: List[str] = []
    header_cells = [_escape_cell(v) for v in grid[0]]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")
    for row in grid[1:]:
        cells = [_escape_cell(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _chart_to_markdown(chart) -> str:
    """차트를 데이터 표로 변환 (막대/꺾은선 등 categories+series 구조만 지원)."""
    try:
        plot = chart.plots[0]
        categories = [str(c) if c is not None else "" for c in plot.categories]
    except (IndexError, AttributeError, ValueError):
        return "[차트: 데이터 추출 불가]"

    if not categories:
        return "[차트: 데이터 추출 불가]"

    series_list = list(chart.series)
    if not series_list:
        return "[차트: 데이터 추출 불가]"

    header = ["구분"] + [s.name or f"Series {i+1}" for i, s in enumerate(series_list)]
    lines = ["| " + " | ".join(_escape_cell(h) for h in header) + " |"]
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for idx, category in enumerate(categories):
        row = [category]
        for series in series_list:
            values = list(series.values)
            value = values[idx] if idx < len(values) else None
            row.append("" if value is None else str(value))
        lines.append("| " + " | ".join(_escape_cell(c) for c in row) + " |")
    return "\n".join(lines)


def _text_frame_to_markdown(text_frame) -> str:
    lines: List[str] = []
    for paragraph in text_frame.paragraphs:
        text = "".join(run.text for run in paragraph.runs).strip()
        if not text:
            continue
        indent = "  " * max(paragraph.level, 0)
        lines.append(f"{indent}- {text}")
    return "\n".join(lines)


def _extract_picture(shape, slide_idx: int, image_counter: List[int], images_dir: Optional[Path]) -> str:
    alt = (shape.name or "image").strip() or "image"
    if images_dir is None:
        return f"![{alt}](embedded image not extracted — slide {slide_idx})"

    try:
        image = shape.image
    except (ValueError, AttributeError):
        return f"![{alt}](image could not be read — slide {slide_idx})"

    image_counter[0] += 1
    images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"slide{slide_idx}_img{image_counter[0]}.{image.ext}"
    (images_dir / filename).write_bytes(image.blob)
    return f"![{alt}]({images_dir.name}/{filename})"


def _infer_title_shape(shapes):
    """정식 Title placeholder가 없는 슬라이드에서 제목으로 보이는 도형을 추정한다.

    사내 PPT는 레이아웃의 Title placeholder 대신 자유 배치한 텍스트 상자로
    제목을 넣는 경우가 많다(이 경우 slide.shapes.title은 None이거나 비어
    있다). 완벽하게 판별할 방법은 없지만, 실제 문서에서 제목은 거의 항상
    슬라이드에서 가장 위쪽에 배치되므로 "텍스트가 있는 도형 중 top 좌표가
    가장 작은 것"을 제목으로 간주하는 실용적인 근사치를 쓴다. 표/차트/사진은
    제목일 수 없으므로 후보에서 제외한다.
    """
    candidates = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            continue
        if getattr(shape, "has_chart", False) and shape.has_chart:
            continue
        if not (getattr(shape, "has_text_frame", False) and shape.has_text_frame):
            continue
        text = shape.text_frame.text.strip()
        if not text:
            continue
        top = shape.top if shape.top is not None else 0
        candidates.append((top, shape, text))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    _, shape, text = candidates[0]
    return shape, text.splitlines()[0].strip()


def _process_shapes(
    shapes,
    slide_idx: int,
    image_counter: List[int],
    images_dir: Optional[Path],
    tables_only: bool = False,
) -> List[str]:
    blocks: List[str] = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            blocks.extend(_process_shapes(shape.shapes, slide_idx, image_counter, images_dir, tables_only))
            continue

        if getattr(shape, "has_table", False) and shape.has_table:
            md_table = _table_to_markdown(shape.table)
            if md_table:
                blocks.append(md_table)
            continue

        if getattr(shape, "has_chart", False) and shape.has_chart:
            blocks.append(_chart_to_markdown(shape.chart))
            continue

        if tables_only:
            # 설치 위치 도면/장비 사진 같은 placeholder 도형, 목적 설명 같은
            # 서술형 텍스트는 사양서(표)와 무관하므로 건너뛴다.
            continue

        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            blocks.append(_extract_picture(shape, slide_idx, image_counter, images_dir))
            continue

        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text_md = _text_frame_to_markdown(shape.text_frame)
            if text_md:
                blocks.append(text_md)
            continue

    return blocks


def convert_pptx_to_markdown(
    pptx_path: Union[str, Path],
    *,
    extract_images: bool = True,
    images_dir: Optional[Union[str, Path]] = None,
    tables_only: bool = False,
) -> str:
    """PPTX 파일 하나를 읽어 슬라이드 순서를 보존한 Markdown 문자열로 변환한다.

    extract_images=True면 슬라이드에 포함된 그림을 images_dir(기본값: 출력 파일과
    같은 위치의 `<파일명>_images/`) 아래에 실제 파일로 저장하고 상대 경로로
    링크한다. LLM 기반 이미지 캡셔닝은 하지 않는다(외부 API 호출 없음) — alt
    text는 PPTX 도형 이름을 그대로 사용한다.

    tables_only=True면 표(및 차트 데이터)만 남기고 일반 텍스트 상자/도형/사진은
    건너뛴다. 사내 사양서 슬라이드가 "설치 위치 도면", "설치 목적" 같은 서술
    섹션과 실제 사양 표를 함께 담고 있을 때, 사양서로 쓸 값은 표뿐이므로 이
    옵션으로 표만 뽑아낼 수 있다. 표가 하나도 없는 슬라이드는 통째로 생략된다.

    슬라이드 제목은 정식 Title placeholder(slide.shapes.title)가 있으면 그
    값을 쓰고, 없거나 비어 있으면 _infer_title_shape()로 추정한다 — 사내 PPT는
    레이아웃의 Title placeholder 대신 자유 배치한 텍스트 상자로 제목을 넣는
    경우가 많기 때문이다(가장 위쪽 텍스트 도형을 제목으로 간주하는 휴리스틱).
    """
    pptx_path = Path(pptx_path)
    prs = Presentation(str(pptx_path))

    resolved_images_dir: Optional[Path] = None
    if extract_images and not tables_only:
        resolved_images_dir = Path(images_dir) if images_dir is not None else pptx_path.with_suffix("").parent / f"{pptx_path.stem}_images"

    doc_lines: List[str] = [f"# {pptx_path.stem}", ""]
    image_counter = [0]

    for slide_idx, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title_text = ""
        if title_shape is not None and title_shape.has_text_frame:
            title_text = title_shape.text_frame.text.strip()

        # slide.shapes.title은 호출할 때마다 새 래퍼 객체를 반환하므로(`is`
        # 비교가 항상 False) shape_id로 비교해야 제목 도형이 본문에서 중복
        # 렌더링되지 않는다.
        title_shape_id = title_shape.shape_id if title_shape is not None else None

        if not title_text:
            # 정식 Title placeholder가 없거나 비어 있는 슬라이드(자유 배치 PPT에서
            # 흔함) — 가장 위쪽 텍스트 도형을 제목으로 추정한다.
            inferred = _infer_title_shape(slide.shapes)
            if inferred is not None:
                inferred_shape, inferred_text = inferred
                title_text = inferred_text
                title_shape_id = inferred_shape.shape_id

        body_shapes = [s for s in slide.shapes if s.shape_id != title_shape_id]
        blocks = _process_shapes(body_shapes, slide_idx, image_counter, resolved_images_dir, tables_only)

        if tables_only and not blocks:
            continue  # 표가 없는 슬라이드(도면/목적 설명 등)는 사양서에 불필요하므로 생략

        heading = f"## Slide {slide_idx}: {title_text}" if title_text else f"## Slide {slide_idx}"
        doc_lines.append(heading)
        doc_lines.append("")

        for block in blocks:
            doc_lines.append(block)
            doc_lines.append("")

        if slide.has_notes_slide:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
            if notes_text:
                quoted = "\n".join(f"> {line}" for line in notes_text.splitlines())
                doc_lines.append("**Notes:**")
                doc_lines.append(quoted)
                doc_lines.append("")

        doc_lines.append("---")
        doc_lines.append("")

    # 마지막 슬라이드 구분선은 불필요하므로 제거
    while doc_lines and doc_lines[-1] in ("", "---"):
        doc_lines.pop()

    return "\n".join(doc_lines) + "\n"


def convert_pptx_file(
    pptx_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    *,
    extract_images: bool = True,
    tables_only: bool = False,
) -> Path:
    """PPTX -> Markdown 변환 후 파일로 저장하고 저장된 경로를 반환한다."""
    pptx_path = Path(pptx_path)
    out_path = Path(output_path) if output_path is not None else pptx_path.with_suffix(".md")

    images_dir = out_path.with_suffix("").parent / f"{out_path.stem}_images"
    markdown = convert_pptx_to_markdown(
        pptx_path, extract_images=extract_images, images_dir=images_dir, tables_only=tables_only
    )

    out_path.write_text(markdown, encoding="utf-8")
    return out_path


def _main(argv: Optional[List[str]] = None) -> None:
    """이 파일을 `python converters/pptx_to_markdown.py ...`로 직접 실행하기
    위한 진입점. `python main.py pptx-to-md ...`(cli_commands.py)와 동일한
    옵션을 지원하지만, main.py가 끌어오는 FastAPI/dotenv 등 웹 서버 의존성
    없이 python-pptx만으로 동작한다 — 변환만 하고 싶을 때 더 가볍다.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="pptx_to_markdown.py", description="PPTX 사양서를 Markdown으로 변환 (오프라인, 외부 API 호출 없음)"
    )
    parser.add_argument("input", help="변환할 .pptx 파일 경로")
    parser.add_argument("-o", "--output", default=None, help="출력 .md 경로 (기본값: 입력 파일과 같은 이름)")
    parser.add_argument("--no-images", action="store_true", help="슬라이드 이미지를 추출하지 않음")
    parser.add_argument("--tables-only", action="store_true", help="표(사양 데이터)만 추출하고 도면/설명 텍스트는 건너뜀")

    args = parser.parse_args(argv)
    out_path = convert_pptx_file(
        args.input, args.output, extract_images=not args.no_images, tables_only=args.tables_only
    )
    print(f"Markdown 저장 완료: {out_path}")


if __name__ == "__main__":
    _main()
