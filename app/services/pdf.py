from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def generate_receipt(receipt_data: dict) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, f"Receipt Number: {receipt_data['receipt_number']}")
    c.drawString(100, 730, f"Student: {receipt_data['student_name']}")
    c.drawString(100, 710, f"Amount: GHS {receipt_data['amount_ghs']}")
    c.drawString(100, 690, f"Date: {receipt_data['date']}")
    c.save()
    buffer.seek(0)
    return buffer