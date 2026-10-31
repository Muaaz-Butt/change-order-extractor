"""Generate the PDF samples in samples/ (synthetic data, no real projects).

    uv run python scripts/make_sample_pdfs.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"
W, H = letter


def _rows(c: canvas.Canvas, y: float, rows: list[tuple], xs: list[float], size: int = 9, bold_first=False) -> float:
    for n, row in enumerate(rows):
        c.setFont("Helvetica-Bold" if bold_first and n == 0 else "Helvetica", size)
        for x, cell in zip(xs, row):
            if isinstance(cell, str) and cell.startswith(">"):  # right-aligned
                c.drawRightString(x, y, cell[1:])
            else:
                c.drawString(x, y, str(cell))
        y -= size + 5
    return y


def co_001_formal() -> None:
    c = canvas.Canvas(str(OUT / "co_001_formal.pdf"), pagesize=letter)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, H - 55, "CHANGE ORDER")
    c.setFont("Helvetica", 8)
    c.drawString(50, H - 68, "Form modeled on AIA G701 layout - synthetic sample")
    y = _rows(c, H - 95, [
        ("Change Order No.: 007", "Date: 03/14/2025"),
        ("Project Name: Riverside Medical Office Building", "Project No.: 2024-118"),
        ("Owner: Riverside Health Partners LLC", "Architect: Lumen Design Studio"),
        ("Contractor: Keystone Builders Inc.", ""),
    ], [50, 360], 10)
    y -= 8
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Description of Change:")
    c.setFont("Helvetica", 10)
    c.drawString(50, y - 14, "Add two dedicated 20A circuits and six data drops for imaging room 214 per RFI-031.")
    c.drawString(50, y - 28, "Reason for Change: Owner request - new imaging equipment selected by Owner.")
    y -= 52
    y = _rows(c, y, [
        ("Item", "Description", "Qty", "Unit", ">Unit Price", ">Amount"),
        ("1", "Electrician labor", "24", "HR", ">95.00", ">2,280.00"),
        ("2", "20A breakers, wire and conduit", "1", "LS", ">1,140.00", ">1,140.00"),
        ("3", "Cat6 data drops", "6", "EA", ">185.00", ">1,110.00"),
        ("4", "Drywall patch and paint", "1", "LS", ">620.00", ">620.00"),
    ], [50, 80, 330, 370, 470, 560], 10, bold_first=True)
    c.line(50, y + 8, 560, y + 8)
    y = _rows(c, y - 4, [
        ("Subtotal", ">5,150.00"),
        ("Overhead & Profit (15%)", ">772.50"),
        ("Total Change Order Amount", ">$5,922.50"),
    ], [330, 560], 10)
    y -= 10
    y = _rows(c, y, [
        ("The original Contract Sum was", ">$4,850,000.00"),
        ("Net change by previously authorized Change Orders", ">$126,400.00"),
        ("The Contract Sum prior to this Change Order was", ">$4,976,400.00"),
        ("The Contract Sum will be increased by this Change Order in the amount of", ">$5,922.50"),
        ("The new Contract Sum including this Change Order will be", ">$4,982,322.50"),
    ], [50, 560], 10)
    y -= 6
    c.setFont("Helvetica", 10)
    c.drawString(50, y, "The Contract Time will be increased by three (3) calendar days.")
    c.drawString(50, y - 14, "The date of Substantial Completion as of the date of this Change Order therefore is November 21, 2025.")
    y -= 50
    _rows(c, y, [("OWNER", "CONTRACTOR", "ARCHITECT"),
                 ("Riverside Health Partners LLC", "Keystone Builders Inc.", "Lumen Design Studio"),
                 ("Signed: A. Patel  3/18/2025", "Signed: R. Kim  3/14/2025", "Signed: L. Moreau  3/17/2025")],
          [50, 230, 410], 9, bold_first=True)
    c.setFont("Helvetica-Bold", 22)
    c.setFillColorRGB(0.1, 0.5, 0.2)
    c.drawString(430, H - 60, "APPROVED")
    c.save()


def co_004_credit() -> None:
    c = canvas.Canvas(str(OUT / "co_004_credit.pdf"), pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, H - 55, "BRIGHTLINE INTERIORS - DEDUCTIVE CHANGE ORDER")
    y = _rows(c, H - 85, [
        ("Change Order Number: CO-022", "Date Issued: September 3, 2025"),
        ("Project: Maple Street Senior Living - Phase 2", "Project #: MSL-02"),
        ("Owner: Maple Street Housing Trust", "Contractor: Brightline Interiors LLC"),
    ], [50, 340], 10)
    y -= 6
    c.setFont("Helvetica", 10)
    c.drawString(50, y, "Description: Substitute luxury vinyl tile (LVT) for porcelain tile in corridors 2A-2F.")
    c.drawString(50, y - 14, "Reason: Value engineering proposal VE-04 accepted by Owner.")
    y -= 40
    y = _rows(c, y, [
        ("Item", "Description", "Qty", "Unit", ">Unit Price", ">Amount"),
        ("1", "Delete porcelain tile, installed", "1,200", "SF", ">9.50", ">(11,400.00)"),
        ("2", "Add LVT, installed", "1,200", "SF", ">5.75", ">6,900.00"),
    ], [50, 80, 330, 370, 470, 560], 10, bold_first=True)
    y = _rows(c, y - 4, [
        ("Subtotal", ">(4,500.00)"),
        ("Overhead & Profit 10%", ">(450.00)"),
        ("TOTAL CHANGE ORDER AMOUNT (CREDIT)", ">($4,950.00)"),
    ], [300, 560], 10)
    y -= 10
    y = _rows(c, y, [
        ("Original Contract Sum", ">$2,300,000.00"),
        ("Previous Change Orders", ">$41,250.00"),
        ("Contract Sum Prior to This Change Order", ">$2,341,250.00"),
        ("Revised Contract Sum", ">$2,336,300.00"),
    ], [50, 560], 10)
    c.drawString(50, y - 6, "Contract Time will be decreased by 5 calendar days.")
    c.drawString(50, y - 20, "Revised Completion Date: 01/16/2026")
    c.drawString(50, y - 50, "Status: Approved by Owner 09/05/2025")
    c.save()


def co_006_twocolumn() -> None:
    """Labels on one line, values on the next, in two columns."""
    c = canvas.Canvas(str(OUT / "co_006_twocolumn.pdf"), pagesize=letter)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, H - 50, "IRONWOOD CIVIL CONTRACTORS")
    c.setFont("Helvetica", 9)
    c.drawString(50, H - 63, "Change Order Request")
    pairs = [("CHANGE ORDER NO.", "CO 9", "DATE", "10/02/2025"),
             ("PROJECT", "Westfield Retail Pad Site", "PROJECT NO.", "IW-7740"),
             ("OWNER", "Westfield Commercial Partners", "CONTRACTOR", "Ironwood Civil Contractors")]
    y = H - 95
    for l1, v1, l2, v2 in pairs:
        c.setFont("Helvetica-Bold", 8)
        c.drawString(50, y, l1)
        c.drawString(330, y, l2)
        c.setFont("Helvetica", 10)
        c.drawString(50, y - 12, v1)
        c.drawString(330, y - 12, v2)
        y -= 34
    c.setFont("Helvetica", 10)
    for line in ["SCOPE OF CHANGE: Remove unsuitable soils and import structural fill at building pad.",
                 "Unforeseen subsurface condition: organic clay encountered at 3 ft, not identified",
                 "in the geotechnical report."]:
        c.drawString(50, y, line)
        y -= 14
    y -= 10
    y = _rows(c, y, [
        ("Description", "Qty", "Unit", ">Rate", ">Amount"),
        ("Excavate and haul unsuitable soil", "640", "CY", ">18.50", ">11,840.00"),
        ("Import and compact structural fill", "640", "CY", ">32.00", ">20,480.00"),
        ("Geotechnical testing", "1", "LS", ">2,350.00", ">2,350.00"),
    ], [50, 300, 340, 450, 560], 10, bold_first=True)
    y = _rows(c, y - 4, [("Total", ">$34,670.00")], [300, 560], 10)
    c.drawString(50, y - 6, "Time Extension: 2 weeks")
    c.drawString(50, y - 20, "Awaiting Owner approval.")
    c.save()


def co_008_scanned() -> None:
    """Image-only PDF: no text layer at all. Exercises the scanned-document path."""
    lines = ["CHANGE ORDER", "", "Change Order No.: 3", "Date: 05/12/2025",
             "Project: Pine Hollow Clubhouse Renovation", "Owner: Pine Hollow HOA",
             "Contractor: Oakridge Remodeling Co.", "",
             "Description of Change: Replace rotted rim joist found behind siding.",
             "Reason for Change: Concealed condition", "",
             "1  Framing labor            12 HR    75.00     900.00",
             "2  Lumber and fasteners      1 LS   410.00     410.00", "",
             "Total Change Order Amount                  $1,310.00",
             "Contract time will be increased by 1 calendar day.", "Status: Approved"]
    img = Image.new("L", (1700, 2200), 245)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Courier New.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    y = 150
    for line in lines:
        d.text((140, y), line, fill=30, font=font)
        y += 52
    img = img.rotate(0.8, fillcolor=245).filter(ImageFilter.GaussianBlur(0.8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c = canvas.Canvas(str(OUT / "co_008_scanned.pdf"), pagesize=letter)
    c.drawImage(ImageReader(buf), 0, 0, W, H)
    c.save()


if __name__ == "__main__":
    for fn in (co_001_formal, co_004_credit, co_006_twocolumn, co_008_scanned):
        fn()
        print("wrote", fn.__name__)
