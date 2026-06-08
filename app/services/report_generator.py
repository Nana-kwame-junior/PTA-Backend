import io
from datetime import datetime
from sqlalchemy.orm import Session
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows

from app.models.student import Student
from app.models.payment import Payment, PaymentStatus
from app.models.manual_payment import ManualPayment
from app.models.dues_config import DuesConfig


def generate_financial_report_excel(db: Session, academic_year: str, term: str) -> io.BytesIO:
    """
    Generate an Excel report for financial summary.
    Returns BytesIO object ready to be sent as streaming response.
    """
    # Fetch dues config
    dues = db.query(DuesConfig).filter(
        DuesConfig.academic_year == academic_year,
        DuesConfig.term == term
    ).first()
    if not dues:
        raise ValueError(f"No dues configuration found for {academic_year} - {term}")

    # Get all students
    students = db.query(Student).filter(
        Student.academic_year == academic_year,
        Student.is_active == True
    ).all()

    # Prepare payment status per student
    data = []
    for student in students:
        # Check online payment
        online_paid = db.query(Payment).filter(
            Payment.student_id == student.id,
            Payment.dues_config_id == dues.id,
            Payment.status == PaymentStatus.COMPLETED
        ).first()
        # Check manual payment
        manual_paid = db.query(ManualPayment).filter(
            ManualPayment.student_id == student.id,
            ManualPayment.academic_year == academic_year,
            ManualPayment.term == term
        ).first()

        status = "PAID" if (online_paid or manual_paid) else "UNPAID"
        amount_paid = (online_paid.amount_ghs if online_paid else 0) + (manual_paid.amount_ghs if manual_paid else 0)
        payment_date = None
        if online_paid and online_paid.paid_at:
            payment_date = online_paid.paid_at
        elif manual_paid and manual_paid.payment_date:
            payment_date = manual_paid.payment_date

        data.append({
            "Index Number": student.index_number,
            "Student Name": student.full_name,
            "Form": student.form,
            "Stream": student.stream,
            "Status": status,
            "Amount Paid (GHS)": float(amount_paid),
            "Payment Date": payment_date.strftime("%Y-%m-%d") if payment_date else "",
            "Parent Phone": student.parent_phone_1 or ""
        })

    # Create DataFrame
    df = pd.DataFrame(data)

    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Payment Report", index=False)
        worksheet = writer.sheets["Payment Report"]

        # Style header row
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        for cell in worksheet[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # Adjust column widths
        for col in worksheet.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 30)
            worksheet.column_dimensions[col_letter].width = adjusted_width

        # Add summary sheet
        summary_data = {
            "Academic Year": [academic_year],
            "Term": [term],
            "Dues Amount (GHS)": [float(dues.amount_ghs)],
            "Due Date": [dues.due_date.strftime("%Y-%m-%d")],
            "Total Students": [len(students)],
            "Paid Count": [len([s for s in data if s["Status"] == "PAID"])],
            "Unpaid Count": [len([s for s in data if s["Status"] == "UNPAID"])],
            "Total Collected (GHS)": [sum(s["Amount Paid (GHS)"] for s in data)],
            "Expected Total (GHS)": [float(dues.amount_ghs) * len(students)],
            "Report Generated": [datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    output.seek(0)
    return output