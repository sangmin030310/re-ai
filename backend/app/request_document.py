"""Word rendering for a confirmed waste intake request."""
import re
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

WORD_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
INVALID_XML_TEXT = re.compile(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def build_request_document(data, *, title, company):
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.9)
    section.bottom_margin = Inches(0.9)
    section.left_margin = Inches(0.95)
    section.right_margin = Inches(0.95)
    for name, size in (("Normal", 11), ("Title", 25), ("Heading 1", 14)):
        style = doc.styles[name]
        style.font.name = "Malgun Gothic"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        para = style.element.get_or_add_pPr()
        border = para.find(qn("w:pBdr"))
        if border is not None:
            para.remove(border)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.35
    doc.styles["Normal"].paragraph_format.space_after = Pt(9)
    doc.add_paragraph(title, "Title")
    recipient = doc.add_paragraph(f"발신 기업  {INVALID_XML_TEXT.sub('', company)}")
    recipient.paragraph_format.space_after = Pt(18)
    doc.add_paragraph("아래 폐기물의 인수 검토를 요청드립니다. 수거 가능 여부와 검토에 필요한 추가 자료를 회신해 주세요.")
    doc.add_heading("배출 정보", level=1)

    fields = [
        ("재질", data.material),
        ("월간 발생량", f"{data.monthly_ton:g}톤"),
        ("배출 지역", data.region),
        ("오염 상태", data.contamination),
        ("포장 상태", data.packaging),
    ]
    extra = getattr(data, "legal_status", None)
    if extra is not None:
        fields += [
            ("발생 주기", data.frequency),
            ("거래 희망", data.price_preference),
            ("법적 지위", f"{data.legal_status} (배출업체 입력, 검토 전)" if data.legal_status != "확인 전" else "확인 전"),
        ]
        if data.address:
            fields.append(("상차 주소", data.address))
        if data.waste_code:
            fields.append(("폐기물 분류번호", data.waste_code))
        if data.attachment_ids:
            fields.append(("첨부 자료", f"{len(data.attachment_ids)}건 (Re AI 문의 화면에서 확인)"))
    table = doc.add_table(rows=0, cols=2)
    table.autofit = False
    for column, width in zip(table.columns, (1.65, 4.95)):
        column.width = Inches(width)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        line = OxmlElement(f"w:{edge}")
        for attr, value in (("val", "single"), ("sz", "6"), ("color", "D9D9D9")):
            line.set(qn(f"w:{attr}"), value)
        borders.append(line)
    table._tbl.tblPr.append(borders)
    margins = OxmlElement("w:tblCellMar")
    for edge, size in (("top", "130"), ("bottom", "130"), ("left", "180"), ("right", "180")):
        margin = OxmlElement(f"w:{edge}")
        margin.set(qn("w:w"), size)
        margin.set(qn("w:type"), "dxa")
        margins.append(margin)
    table._tbl.tblPr.append(margins)
    for label, value in fields:
        cells = table.add_row().cells
        for index, text in enumerate((label, value)):
            paragraph = cells[index].paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.add_run(INVALID_XML_TEXT.sub("", text)).bold = index == 0
    if data.notes:
        doc.add_heading("추가 전달 사항", level=1)
        doc.add_paragraph(INVALID_XML_TEXT.sub("", data.notes))
    notice = doc.add_paragraph("Re AI 시연 자료 · 발신자가 입력한 정보를 기준으로 작성했습니다.")
    notice.paragraph_format.space_before = Pt(18)
    notice.runs[0].font.size = Pt(9)
    notice.runs[0].font.color.rgb = RGBColor.from_string("555555")
    return doc


def render_request_document(data, *, title, company) -> bytes:
    buffer = BytesIO()
    build_request_document(data, title=title, company=company).save(buffer)
    return buffer.getvalue()
