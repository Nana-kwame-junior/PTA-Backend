"""PDF receipt generation for manual and online PTA payments."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


TEAL = colors.HexColor("#0F766E")
TEAL_DARK = colors.HexColor("#115E59")
INK = colors.HexColor("#1C1917")
MUTED = colors.HexColor("#78716C")
BORDER = colors.HexColor("#E7E5E4")
PANEL = colors.HexColor("#F8FAFC")
WHITE = colors.white


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


def _format_amount(amount_ghs: str) -> str:
    try:
        value = float(amount_ghs)
        return f"GHS {value:,.2f}"
    except (TypeError, ValueError):
        return f"GHS {amount_ghs}"


def generate_receipt(receipt_data: dict) -> BytesIO:
    buffer = BytesIO()
    page_width, page_height = A5
    margin = 16 * mm

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Receipt {receipt_data['receipt_number']}",
    )

    styles = getSampleStyleSheet()
    brand = ParagraphStyle(
        "Brand",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=WHITE,
    )
    brand_sub = ParagraphStyle(
        "BrandSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#D1FAE5"),
    )
    receipt_no = ParagraphStyle(
        "ReceiptNo",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        alignment=TA_RIGHT,
        textColor=WHITE,
    )
    amount = ParagraphStyle(
        "Amount",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=28,
        leading=32,
        textColor=INK,
    )
    channel = ParagraphStyle(
        "Channel",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=MUTED,
    )
    label = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=MUTED,
        spaceAfter=2,
    )
    value = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=INK,
    )
    footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=12,
        textColor=MUTED,
        alignment=TA_CENTER,
    )

    story = []

    header = Table(
        [
            [
                Paragraph("SchoolPulse", brand),
                Paragraph(receipt_data["receipt_number"], receipt_no),
            ],
            [Paragraph("Official PTA Payment Receipt", brand_sub), ""],
        ],
        colWidths=[(page_width - 2 * margin) * 0.62, (page_width - 2 * margin) * 0.38],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, 0), 14),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("SPAN", (0, 1), (0, 1)),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 10 * mm))

    amount_box = Table(
        [
            [Paragraph(_format_amount(receipt_data["amount_ghs"]), amount)],
            [Paragraph(receipt_data.get("channel", "Payment"), channel)],
        ],
        colWidths=[page_width - 2 * margin],
    )
    amount_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
            ]
        )
    )
    story.append(amount_box)
    story.append(Spacer(1, 8 * mm))

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

    detail_rows = []
    for row_label, row_value in rows:
        detail_rows.append(
            [
                Paragraph(row_label.upper(), label),
                Paragraph(str(row_value), value),
            ]
        )

    details = Table(
        detail_rows,
        colWidths=[(page_width - 2 * margin) * 0.36, (page_width - 2 * margin) * 0.64],
        repeatRows=0,
    )
    detail_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
    ]
    for i in range(len(detail_rows)):
        if i % 2 == 0:
            detail_style.append(("BACKGROUND", (0, i), (-1, i), WHITE))
        else:
            detail_style.append(("BACKGROUND", (0, i), (-1, i), PANEL))
    details.setStyle(TableStyle(detail_style))
    story.append(details)
    story.append(Spacer(1, 10 * mm))

    story.append(
        Paragraph(
            "This receipt confirms PTA dues received by the school finance office.<br/>"
            "Keep this document for your records. &mdash; SchoolPulse PTA",
            footer,
        )
    )

    doc.build(story)
    buffer.seek(0)
    return buffer
