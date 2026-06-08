import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

async def send_temporary_password_email(to_email: str, temp_password: str, user_name: str):
    subject = "Your Mawuli PTA Staff Account"
    body = f"""
    Hello {user_name},

    Your staff account for PTA Management System has been created.

    Use the following temporary password to log in:
    {temp_password}

    You will be required to change your password after first login.

    Login URL: {settings.api_base_url}/login

    ---
    Mawuli SHS PTA
    """
    msg = MIMEMultipart()
    msg["From"] = settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass)
        server.send_message(msg)