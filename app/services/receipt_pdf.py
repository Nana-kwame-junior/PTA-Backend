"""PDF receipt generation for manual and online PTA payments."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _draw_line(c, y: float, width: float, margin: float) -> float:
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.line(margin, y, width - margin, y)
    return y - 14


def build_receipt_payload(
    *,
    receipt_number: str,
    student_name: str,
    student_index: str | None,
    amount_ghs: str,
    payment_date: str,
    channel: str,
    payment_mode: str | None = None,
    term: str | None = None,
    academic_year: str | None = None,
    recorded_by: str | None = None,
    reference: str | None = None,
) -> dict:
    return {
        "receipt_number": receipt_number,
        "student_name": student_name,
        "student_index": student_index or "—",
        "amount_ghs": amount_ghs,
        "payment_date": payment_date,
        "channel": channel,
        "payment_mode": payment_mode or "—",
        "term": term or "—",
        "academic_year": academic_year or "—",
        "recorded_by": recorded_by or "—",
        "reference": reference or receipt_number,
    }


def generate_receipt(receipt_data: dict) -> BytesIO:
    buffer = BytesIO()
    width, height = A5
    margin = 18 * mm
    c = canvas.Canvas(buffer, pagesize=A5)

    # Header band
    c.setFillColor(colors.HexColor("#0d9488"))
    c.rect(0, height - 42 * mm, width, 42 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, height - 18 * mm, "SchoolPulse")
    c.setFont("Helvetica", 10)
    c.drawString(margin, height - 26 * mm, "Official PTA Payment Receipt")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(width - margin, height - 18 * mm, receipt_data["receipt_number"])

    y = height - 52 * mm
    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, y, f"GH₵ {receipt_data['amount_ghs']}")
    y -= 10 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(margin, y, receipt_data.get("channel", "Payment"))
    y -= 8 * mm

    rows = [
        ("Student", receipt_data["student_name"]),
        ("Index number", receipt_data.get("student_index", "—")),
        ("Academic year", receipt_data.get("academic_year", "—")),
        ("Term", receipt_data.get("term", "—")),
        ("Payment mode", receipt_data.get("payment_mode", "—")),
        ("Date paid", receipt_data["payment_date"]),
        ("Reference", receipt_data.get("reference", receipt_data["receipt_number"])),
    ]
    if receipt_data.get("recorded_by") and receipt_data["recorded_by"] != "—":
        rows.append(("Recorded by", receipt_data["recorded_by"]))

    for label, value in rows:
        y = _draw_line(c, y, width, margin)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#64748b"))
        c.drawString(margin, y, label.upper())
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor("#0f172a"))
        c.drawString(margin, y - 12, str(value)[:72])

    y -= 22 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#94a3b8"))
    c.drawString(
        margin,
        16 * mm,
        "This receipt confirms PTA dues received by the school finance office.",
    )
    c.drawString(margin, 10 * mm, "Keep this receipt for your records. — SchoolPulse PTA")

    c.save()
    buffer.seek(0)
    return buffer
