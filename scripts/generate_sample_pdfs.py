#!/usr/bin/env python3
"""Render the synthetic supplier proposals to PDF, plus two error-case files.

    python scripts/generate_sample_pdfs.py

Writes:
    sample_pdfs/*.pdf                     four readable supplier proposals
    sample_pdfs/error_cases/scanned_no_text.pdf   image-only, no text layer
    sample_pdfs/error_cases/not_a_pdf.pdf         plain text renamed to .pdf

Every price total is computed from the line items in supplier_content.py, so a
table can never disagree with its own sum.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from rfp import config  # noqa: E402
import supplier_content as content  # noqa: E402

INK = colors.HexColor("#1a1a1a")
ACCENT = colors.HexColor("#1f4e79")
RULE = colors.HexColor("#b8c4d0")
BAND = colors.HexColor("#eef2f6")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=27, textColor=ACCENT, spaceAfter=4),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=12, leading=16, textColor=colors.HexColor("#4a5a6a"),
            spaceAfter=18),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=13, leading=17, textColor=ACCENT, spaceBefore=14, spaceAfter=7),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.6,
            leading=14.2, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=8),
        "bullet": ParagraphStyle(
            "bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=9.6,
            leading=14.2, textColor=INK, leftIndent=12, bulletIndent=3, spaceAfter=4),
        "cell": ParagraphStyle(
            "cell", parent=base["BodyText"], fontName="Helvetica", fontSize=8.4,
            leading=11.4, textColor=INK, spaceAfter=0),
        "cellhead": ParagraphStyle(
            "cellhead", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8.4, leading=11.4, textColor=colors.white, spaceAfter=0),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"], fontName="Helvetica", fontSize=9.6,
            leading=14, textColor=INK),
        "notice": ParagraphStyle(
            "notice", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8.2, leading=11.5, textColor=colors.HexColor("#7a2a2a")),
    }


def _footer(canvas, doc, supplier_name: str) -> None:
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.4)
    canvas.setFillColor(colors.HexColor("#6a6a6a"))
    canvas.drawString(20 * mm, 10.5 * mm,
                      f"{supplier_name} | response to {content.BUYER['reference']} "
                      f"| FICTIONAL -- academic exercise")
    canvas.drawRightString(A4[0] - 20 * mm, 10.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _data_table(spec: dict, st: dict) -> Table:
    cols = [Paragraph(c, st["cellhead"]) for c in spec["cols"]]
    rows = [[Paragraph(str(c), st["cell"]) for c in row] for row in spec["rows"]]
    table = Table([cols] + rows, colWidths=spec["widths"], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _money_table(title: str, items, subtotal_label: str, subtotal: int, st: dict) -> Table:
    head = [Paragraph(title, st["cellhead"]), Paragraph("Amount", st["cellhead"])]
    rows = [[Paragraph(label, st["cell"]),
             Paragraph(content.money(amount), st["cell"])] for label, amount in items]
    rows.append([Paragraph(f"<b>{subtotal_label}</b>", st["cell"]),
                 Paragraph(f"<b>{content.money(subtotal)}</b>", st["cell"])])
    table = Table([head] + rows, colWidths=[330, 93], hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dde6ee")),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _pricing_flowables(supplier: dict, st: dict) -> list:
    totals = content.contract_total(supplier["pricing"])
    years = totals["years"]
    out = [
        _money_table("One-off implementation charges", supplier["pricing"]["one_off"],
                     "Total one-off charges", totals["one_off"], st),
        Spacer(1, 7),
        _money_table("Recurring annual charges", supplier["pricing"]["annual"],
                     "Total per year", totals["annual"], st),
        Spacer(1, 7),
    ]
    summary = Table(
        [[Paragraph("<b>Total cost of ownership</b>", st["cell"]),
          Paragraph(f"<b>{content.money(totals['one_off'])} + "
                    f"{years} x {content.money(totals['annual'])} = "
                    f"{content.money(totals['tco'])}</b>", st["cell"])]],
        colWidths=[330, 93], hAlign="LEFT")
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#d5e3ef")),
        ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    out.append(summary)
    out.append(Spacer(1, 4))
    out.append(Paragraph(
        f"Figures are quoted over a {years} year contract term and exclude sales tax.",
        st["notice"]))
    out.append(Spacer(1, 8))
    return out


def _cover(supplier: dict, st: dict) -> list:
    b = content.BUYER
    notice = Table(
        [[Paragraph(b["disclaimer"], st["notice"])]],
        colWidths=[423], hAlign="LEFT")
    notice.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf2f2")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c98b8b")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    meta = Table(
        [[Paragraph("<b>Submitted to</b>", st["cell"]), Paragraph(b["name"], st["cell"])],
         [Paragraph("<b>RFP reference</b>", st["cell"]), Paragraph(b["reference"], st["cell"])],
         [Paragraph("<b>Submission date</b>", st["cell"]),
          Paragraph(supplier["submission_date"], st["cell"])],
         [Paragraph("<b>Proposed duration</b>", st["cell"]),
          Paragraph(f"{supplier['timeline_months']} months", st["cell"])]],
        colWidths=[120, 303], hAlign="LEFT")
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, BAND]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [
        Paragraph(supplier["name"], st["title"]),
        Paragraph(supplier["tagline"], st["subtitle"]),
        Paragraph(f"<b>{b['title']}</b>", st["h1"]),
        Paragraph(b["summary"], st["body"]),
        Spacer(1, 6),
        meta,
        Spacer(1, 12),
        notice,
    ]


def build_proposal(supplier: dict, out_dir: Path) -> Path:
    st = _styles()
    path = out_dir / supplier["filename"]
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=f"{supplier['name']} -- {content.BUYER['title']}",
        author=supplier["name"], subject=content.BUYER["reference"],
    )

    story: list = _cover(supplier, st)
    for section in supplier["sections"]:
        story.append(Paragraph(section["h"], st["h1"]))
        for block in section["body"]:
            if "p" in block:
                story.append(Paragraph(block["p"], st["body"]))
            elif "bullets" in block:
                for item in block["bullets"]:
                    story.append(Paragraph(item, st["bullet"], bulletText="•"))
                story.append(Spacer(1, 6))
            elif "table" in block:
                story.append(Spacer(1, 2))
                story.append(_data_table(block["table"], st))
                story.append(Spacer(1, 10))
            elif "pricing" in block:
                story.extend(_pricing_flowables(supplier, st))

    doc.build(
        story,
        onFirstPage=lambda c, d: _footer(c, d, supplier["name"]),
        onLaterPages=lambda c, d: _footer(c, d, supplier["name"]),
    )
    return path


def build_error_cases(out_dir: Path) -> list[Path]:
    """A PDF with no text layer, and a text file wearing a .pdf extension."""
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []

    # 1. Valid PDF, drawn content only -- simulates a scanned document.
    from reportlab.pdfgen import canvas as pdfcanvas
    scanned = out_dir / "scanned_no_text.pdf"
    c = pdfcanvas.Canvas(str(scanned), pagesize=A4)
    c.setFillColorRGB(0.82, 0.82, 0.82)
    c.rect(25 * mm, 40 * mm, A4[0] - 50 * mm, A4[1] - 80 * mm, stroke=0, fill=1)
    c.setFillColorRGB(0.62, 0.62, 0.62)
    for i in range(14):                      # grey bars that look like text but are not
        c.rect(35 * mm, (A4[1] - 60 * mm) - i * 9 * mm,
               (A4[0] - 70 * mm) * (0.9 if i % 3 else 0.55), 3.4 * mm, stroke=0, fill=1)
    c.showPage()
    c.save()
    made.append(scanned)

    # 2. Not a PDF at all -- no %PDF header.
    fake = out_dir / "not_a_pdf.pdf"
    fake.write_text(
        "This is a plain text file that has been renamed with a .pdf extension.\n"
        "It has no %-P-D-F header, so the document tool must reject it before any\n"
        "LLM call is made. FICTIONAL -- academic exercise.\n",
        encoding="utf-8",
    )
    made.append(fake)
    return made


def main() -> int:
    out_dir = config.SAMPLE_PDF_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    import pymupdf

    print(f"{'File':<34}{'Pages':>6}{'Chars':>8}  Price check")
    print("-" * 74)
    ok = True
    for supplier in content.SUPPLIERS:
        path = build_proposal(supplier, out_dir)
        with pymupdf.open(path) as doc:
            pages = doc.page_count
            text = "".join(p.get_text() for p in doc)
        totals = content.contract_total(supplier["pricing"])
        stated = totals["one_off"] + totals["annual"] * totals["years"]
        price_ok = stated == totals["tco"] and content.money(totals["tco"]) in text.replace("\n", "")
        pages_ok = 2 <= pages <= 4
        ok = ok and price_ok and pages_ok
        flag = "" if pages_ok else "  <-- page count outside 2-4"
        print(f"{path.name:<34}{pages:>6}{len(text):>8}  "
              f"{'totals add up' if price_ok else 'TOTALS MISMATCH'}{flag}")

    for path in build_error_cases(out_dir / "error_cases"):
        print(f"{'error_cases/' + path.name:<34}{'-':>6}{path.stat().st_size:>8}  "
              f"deliberately unreadable")

    print("-" * 74)
    print("OK: all proposals rendered" if ok else "FAIL: see flags above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
