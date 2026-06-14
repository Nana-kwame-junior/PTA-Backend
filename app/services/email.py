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


def _send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    username = settings.resolved_smtp_user
    password = settings.resolved_smtp_pass

    if not username or not password:
        logger.warning("Email not configured — skipped message to %s", to_email)
        return False

    from_addr = settings.smtp_from_address
    from_header = (
        f"{settings.mail_from_name} <{from_addr}>"
        if settings.mail_from_name
        else from_addr
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = from_header
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with _smtp_client() as server:
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", to_email, exc)
        return False


def send_temporary_password_email(to_email: str, temp_password: str, user_name: str) -> bool:
    login_url = settings.dashboard_url.rstrip("/") + "/login"
    subject = "Your Mawuli PTA Staff Portal Access"

    text_body = f"""Hello {user_name},

Your staff account for the Mawuli SHS PTA Management System is ready.

Sign in with:
  Email: {to_email}
  Temporary password: {temp_password}

Portal: {login_url}

Use your email address and the temporary password above to log in. You will be asked to choose a new password immediately after signing in.

— Mawuli SHS PTA
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,0.08);">
        <tr>
          <td style="background:linear-gradient(135deg,#0d9488,#0f766e);padding:28px 32px;color:#ffffff;">
            <div style="font-size:13px;opacity:0.9;letter-spacing:0.08em;text-transform:uppercase;">Mawuli SHS PTA</div>
            <h1 style="margin:12px 0 0;font-size:24px;font-weight:700;">Welcome to the Staff Portal</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;color:#334155;line-height:1.6;">
            <p style="margin:0 0 16px;font-size:16px;">Hello <strong>{user_name}</strong>,</p>
            <p style="margin:0 0 20px;">Your staff account has been created. Use the credentials below to sign in:</p>
            <table width="100%" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:24px;">
              <tr><td style="padding:16px 20px;">
                <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;">Login email</div>
                <div style="font-size:16px;font-weight:700;color:#0f172a;margin-top:4px;">{to_email}</div>
              </td></tr>
              <tr><td style="padding:0 20px 16px;">
                <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;">Temporary password</div>
                <div style="font-size:18px;font-weight:700;color:#0d9488;margin-top:4px;font-family:Consolas,monospace;">{temp_password}</div>
              </td></tr>
            </table>
            <p style="margin:0 0 24px;">After signing in, you must set a new personal password before accessing the dashboard.</p>
            <a href="{login_url}" style="display:inline-block;background:#f97316;color:#ffffff;text-decoration:none;padding:14px 24px;border-radius:999px;font-weight:700;">Open Staff Portal</a>
            <p style="margin:24px 0 0;font-size:13px;color:#64748b;">If the button does not work, copy this link:<br><a href="{login_url}" style="color:#0d9488;">{login_url}</a></p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;background:#f8fafc;color:#94a3b8;font-size:12px;">
            Mawuli Senior High School · PTA Management System
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return _send_email(to_email, subject, html_body, text_body)
