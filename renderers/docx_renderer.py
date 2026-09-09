"""
CandidateEquipment -> Microsoft Word(.docx) 렌더러.

renderers.candidate_specification.build_candidate_specification_data()가 만드는
공통 Structured Data(Markdown 렌더러가 쓰는 것과 동일)를 그대로 소비한다 —
Word와 Markdown이 candidate/requirement를 각자 독립적으로 재해석하지 않도록
하기 위함(요청서 4/11절). 값이 원본 사양서에 없으면 "UNKNOWN"으로 정직하게
남기고, Word 생성 과정에서 추측해서 채우지 않는다(요청서 9절).
"""
from __future__ import annotations

import io
from typing import List, Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from agent.quote_schemas import QuoteAnalysis
from agent.schemas import CandidateEquipment, ComplianceRecord, RequirementSchema

from .candidate_specification import CandidateSpecificationData, build_candidate_specification_data
from .quote_document import QuoteDocumentData, build_quote_document_data

# Hard Requirement 결과 배지 색상 — main.py의 RESULT_BADGE 팔레트(design token)와
# 맞춘다. 새 색상을 만들지 않고 이미 프로젝트가 쓰는 값을 그대로 가져왔다.
_RESULT_COLORS = {
    "PASS": RGBColor(0x1C, 0x6E, 0x7D),
    "FAIL": RGBColor(0x82, 0x27, 0x27),
    "UNKNOWN": RGBColor(0x7B, 0x34, 0x1E),
    "N/A": RGBColor(0x55, 0x55, 0x55),
}


# python-docx 기본 템플릿은 East Asian(eastAsia) 폰트를 지정하지 않는다. Word는
# 라틴 폰트(Calibri 등)에 한글 글리프가 없으면 대체 폰트를 찾는데, 이 대체 과정이
# 실패하는 환경에서는 한글이 네모(tofu)로 깨져 보인다("Sources / Notes"의 한글
# 안내문 등). Windows에 기본 내장된 한글 UI 폰트를 모든 run에 명시적으로 지정해
# 이를 방지한다.
_EAST_ASIAN_FONT = "맑은 고딕"


def _set_east_asian_font(run, font_name: str = _EAST_ASIAN_FONT) -> None:
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:eastAsia"), font_name)


def _apply_korean_font(document: Document) -> None:
    normal_rPr = document.styles["Normal"].element.get_or_add_rPr()
    normal_rPr.get_or_add_rFonts().set(qn("w:eastAsia"), _EAST_ASIAN_FONT)

    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for paragraph in paragraphs:
        for run in paragraph.runs:
            _set_east_asian_font(run)


def _style_table(table) -> None:
    table.style = "Light Grid Accent 1"
    for cell in table.rows[0].cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.bold = True


def _add_section_table(document: Document, section) -> None:
    document.add_heading(section.title, level=1)
    table = document.add_table(rows=1, cols=3)
    _style_table(table)
    header = table.rows[0].cells
    header[0].text, header[1].text, header[2].text = "Item", "Specification", "Status"
    for row in section.rows:
        cells = table.add_row().cells
        cells[0].text = row.label
        cells[1].text = row.value
        cells[2].text = row.status
        if row.status == "UNKNOWN":
            for cell in (cells[1], cells[2]):
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.color.rgb = _RESULT_COLORS["UNKNOWN"]
    document.add_paragraph()


def _add_compliance_table(document: Document, compliance) -> None:
    document.add_heading("Requirement Compliance", level=1)
    if not compliance:
        document.add_paragraph("No requirement provided for comparison.")
        return
    table = document.add_table(rows=1, cols=4)
    _style_table(table)
    header = table.rows[0].cells
    header[0].text, header[1].text, header[2].text, header[3].text = "Requirement", "Required", "Equipment", "Result"
    for row in compliance:
        cells = table.add_row().cells
        cells[0].text = row.item
        cells[1].text = row.required_display
        cells[2].text = row.equipment_display
        cells[3].text = row.result
        color = _RESULT_COLORS.get(row.result)
        if color is not None:
            for paragraph in cells[3].paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
                    run.font.color.rgb = color
    document.add_paragraph()


# Word 사양서에서만 제외하는 섹션(요청서: "핵심 전극 검사 비교와 무관하고 항상
# UNKNOWN뿐인 섹션이 여전히 노출된다") — CandidateEquipmentFact가 애초에 이
# 영역을 추출하지 않아(candidate_specification.py 주석 참고) 실제 데이터로 채워질
# 일이 없는 4개 섹션을 Word 출력에서 제외한다. candidate_specification.py의
# 공통 Structured Data(sections) 자체는 건드리지 않는다 — Word 렌더러가 소비하는
# 시점에만 걸러낸다(Markdown 사양서(render_candidate_markdown)도 같은 4개
# 섹션을 _MARKDOWN_EXCLUDED_SECTION_IDS로 각자 소비 시점에 제외한다).
_DOCX_EXCLUDED_SECTION_IDS = {"system_configuration", "interfaces", "environment", "safety"}


def _build_document(data: CandidateSpecificationData) -> Document:
    document = Document()

    title = document.add_heading(data.equipment_name, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # General Specification은 표로 별도 렌더링(다른 섹션과 동일한 형식으로 통일).
    general = next(s for s in data.sections if s.id == "general")
    _add_section_table(document, general)

    for section in data.sections:
        if section.id == "general" or section.id in _DOCX_EXCLUDED_SECTION_IDS:
            continue
        _add_section_table(document, section)

    _add_compliance_table(document, data.compliance)

    document.add_heading("Sources / Notes", level=1)
    if data.sources:
        document.add_paragraph("Reference Documents:")
        for source in data.sources:
            document.add_paragraph(source, style="List Bullet")
    else:
        document.add_paragraph("Reference Documents: UNKNOWN")
    if data.notes:
        document.add_paragraph("Notes:")
        for note in data.notes:
            document.add_paragraph(note, style="List Bullet")

    _apply_korean_font(document)
    return document


def render_candidate_docx(
    candidate: CandidateEquipment,
    requirement: Optional[RequirementSchema] = None,
    hard_requirement_report: Optional[List[ComplianceRecord]] = None,
) -> bytes:
    """CandidateEquipment 하나를 Word(.docx) 바이트로 렌더링한다. render_candidate_
    markdown()과 정확히 같은 build_candidate_specification_data() 결과를 쓰므로
    두 포맷의 핵심 정보(장비명/Manufacturer/Model/Range/Accuracy/Inspection Mode/
    Hard Requirement 결과)가 항상 일치한다."""
    data = build_candidate_specification_data(candidate, requirement=requirement, hard_requirement_report=hard_requirement_report)
    document = _build_document(data)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_quote_line_item_table(document: Document, heading: str, rows) -> None:
    document.add_heading(heading, level=1)
    if not rows:
        document.add_paragraph("None")
        document.add_paragraph()
        return
    table = document.add_table(rows=1, cols=4)
    _style_table(table)
    header = table.rows[0].cells
    header[0].text, header[1].text, header[2].text, header[3].text = "Item", "Quantity", "Unit Price", "Amount"
    for row in rows:
        cells = table.add_row().cells
        cells[0].text, cells[1].text, cells[2].text, cells[3].text = row.item, row.quantity, row.unit_price, row.amount
    document.add_paragraph()


def _build_quote_document(data: QuoteDocumentData) -> Document:
    document = Document()

    title = document.add_heading(data.title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    document.add_heading("General", level=1)
    for label, value in data.general_rows:
        document.add_paragraph(f"{label}: {value}", style="List Bullet")
    document.add_paragraph()

    _add_quote_line_item_table(document, "Equipment", data.equipment_rows)
    _add_quote_line_item_table(document, "Options", data.option_rows)

    document.add_heading("Additional Cost", level=1)
    if not data.additional_cost_rows:
        document.add_paragraph("None")
    else:
        table = document.add_table(rows=1, cols=2)
        _style_table(table)
        header = table.rows[0].cells
        header[0].text, header[1].text = "Item", "Amount"
        for row in data.additional_cost_rows:
            cells = table.add_row().cells
            cells[0].text, cells[1].text = row.item, row.amount
    document.add_paragraph()

    document.add_heading("Excluded Items", level=1)
    if not data.excluded_items:
        document.add_paragraph("None")
    else:
        for item in data.excluded_items:
            document.add_paragraph(item, style="List Bullet")
    document.add_paragraph()

    document.add_heading("Commercial Terms", level=1)
    for label, value in data.commercial_rows:
        document.add_paragraph(f"{label}: {value}", style="List Bullet")
    document.add_paragraph()

    document.add_heading("Total", level=1)
    table = document.add_table(rows=1, cols=2)
    _style_table(table)
    header = table.rows[0].cells
    header[0].text, header[1].text = "Item", "Amount"
    for row in data.total_rows:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = row.label, row.amount
    document.add_paragraph()

    document.add_heading("Calculation Issues", level=1)
    if not data.issue_messages:
        document.add_paragraph("No calculation issues detected — computed values match the amounts stated in the source quotation.")
    else:
        for message in data.issue_messages:
            p = document.add_paragraph(f"⚠ {message}", style="List Bullet")
            for run in p.runs:
                run.font.color.rgb = _RESULT_COLORS["FAIL"]
    document.add_paragraph()

    document.add_heading("Notes", level=1)
    if data.notes:
        for note in data.notes:
            document.add_paragraph(note, style="List Bullet")
    else:
        document.add_paragraph("None")
    document.add_paragraph(f"Source: {data.source_file}")

    _apply_korean_font(document)
    return document


def render_quote_docx(analysis: QuoteAnalysis) -> bytes:
    """QuoteAnalysis 하나를 Word(.docx) 바이트로 렌더링한다. render_quote_markdown()과
    정확히 같은 build_quote_document_data() 결과를 쓰므로 두 포맷의 금액(코드가
    재계산한 computed_* 값)이 항상 일치한다."""
    data = build_quote_document_data(analysis)
    document = _build_quote_document(data)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
