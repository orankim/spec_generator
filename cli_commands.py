"""
전극 검사기 Agent의 렌더러/변환기를 커맨드라인에서 바로 쓰기 위한 CLI.

main.py는 FastAPI 웹 서버 진입점이므로(기존 `python main.py`는 그대로
서버를 띄워야 한다), 이 파일이 서브커맨드 구현을 담당하고 main.py는
`run_cli(sys.argv)`만 호출해 위임한다.

지원 명령:
    python main.py render-md specification.json [-o out.md]
    python main.py render-html specification.json [-o out.html]
    python main.py md-to-spec input.md [-o out.json]
    python main.py pptx-to-md input.pptx [-o out.md] [--no-images] [--tables-only]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

KNOWN_COMMANDS = {"render-md", "render-html", "md-to-spec", "pptx-to-md"}


def _load_specification(json_path: str):
    from agent.schemas import SpecificationSchema

    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return SpecificationSchema(**data)


def _cmd_render_md(args: argparse.Namespace) -> None:
    from renderers.markdown_renderer import render_markdown

    spec = _load_specification(args.input)
    md = render_markdown(spec)
    out_path = args.output or str(Path(args.input).with_suffix(".md"))
    Path(out_path).write_text(md, encoding="utf-8")
    print(f"Markdown 저장 완료: {out_path}")


def _cmd_render_html(args: argparse.Namespace) -> None:
    from renderers.html_renderer import render_html

    spec = _load_specification(args.input)
    html = render_html(spec)
    out_path = args.output or str(Path(args.input).with_suffix(".html"))
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"HTML 저장 완료: {out_path}")


def _cmd_md_to_spec(args: argparse.Namespace) -> None:
    from converters.markdown_to_spec import markdown_to_spec

    md_text = Path(args.input).read_text(encoding="utf-8")
    spec = markdown_to_spec(md_text)
    out_path = args.output or str(Path(args.input).with_suffix(".json"))
    Path(out_path).write_text(json.dumps(spec.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Specification JSON 저장 완료: {out_path}")


def _cmd_pptx_to_md(args: argparse.Namespace) -> None:
    from converters.pptx_to_markdown import convert_pptx_file

    out_path = convert_pptx_file(
        args.input, args.output, extract_images=not args.no_images, tables_only=args.tables_only
    )
    print(f"Markdown 저장 완료: {out_path}")


_DISPATCH = {
    "render-md": _cmd_render_md,
    "render-html": _cmd_render_html,
    "md-to-spec": _cmd_md_to_spec,
    "pptx-to-md": _cmd_pptx_to_md,
}


def run_cli(argv: List[str]) -> bool:
    """
    argv(예: sys.argv)의 두 번째 인자가 알려진 서브커맨드가 아니면 아무 것도
    하지 않고 False를 반환한다 (main.py가 기존처럼 웹 서버를 띄우게 함).
    서브커맨드를 처리했으면 True를 반환한다.
    """
    if len(argv) < 2 or argv[1] not in KNOWN_COMMANDS:
        return False

    command = argv[1]
    parser = argparse.ArgumentParser(prog=f"main.py {command}")
    parser.add_argument("input")
    parser.add_argument("-o", "--output", default=None)
    if command == "pptx-to-md":
        parser.add_argument("--no-images", action="store_true", help="슬라이드 이미지를 추출하지 않음")
        parser.add_argument(
            "--tables-only", action="store_true", help="표(사양 데이터)만 추출하고 도면/설명 텍스트는 건너뜀"
        )

    args = parser.parse_args(argv[2:])
    _DISPATCH[command](args)
    return True
