import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import ContextManager

from app.core.config import settings

logger = logging.getLogger(__name__)


def _smtp_client() -> ContextManager[smtplib.SMTP]:
    host = settings.resolved_smtp_host
    port = settings.resolved_smtp_port

    if settings.smtp_use_ssl:
        return smtplib.SMTP_SSL(host, port, timeout=30)

    server = smtplib.SMTP(host, port, timeout=30)
    if settings.smtp_use_starttls:
        server.starttls()
    return server


def send_temporary_password_email(to_email: str, temp_password: str, user_name: str) -> bool:
    """
    Send staff invitation / password reset email.
    Returns True when sent, False when skipped or failed. Never raises.
    """
    username = settings.resolved_smtp_user
    password = settings.resolved_smtp_pass

    if not username or not password:
        logger.warning(
            "Email not configured (set MAIL_USERNAME + MAIL_PASSWORD or SMTP_USER + SMTP_PASS) — skipped %s",
            to_email,
        )
        return False

    from_addr = settings.smtp_from_address
    from_header = (
        f"{settings.mail_from_name} <{from_addr}>"
        if settings.mail_from_name
        else from_addr
    )

    subject = "Your Mawuli PTA Staff Account"
    body = f"""Hello {user_name},

Your staff account for the PTA Management System has been updated.

Use this temporary password to log in:
{temp_password}

You must change your password after signing in.

Login: {settings.api_base_url}/login

— Mawuli SHS PTA
"""

    msg = MIMEMultipart()
    msg["From"] = from_header
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with _smtp_client() as server:
            server.login(username, password)
            server.send_message(msg)
        logger.info(
            "Staff email sent to %s via %s:%s (ssl=%s)",
            to_email,
            settings.resolved_smtp_host,
            settings.resolved_smtp_port,
            settings.smtp_use_ssl,
        )
        return True
    except Exception as exc:
        logger.exception(
            "Failed to send staff email to %s (%s:%s ssl=%s): %s",
            to_email,
            settings.resolved_smtp_host,
            settings.resolved_smtp_port,
            settings.smtp_use_ssl,
            exc,
        )
        return False
