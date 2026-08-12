import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


def _send_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    api_key = (settings.brevo_api_key or "").strip()
    from_addr, from_name = settings.resolved_brevo_sender()

    if not api_key or not from_addr:
        logger.warning("Brevo email not configured — skipped message to %s", to_email)
        return False

    sender: dict[str, str] = {"email": from_addr}
    if from_name:
        sender["name"] = from_name

    payload = {
        "sender": sender,
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                BREVO_SEND_URL,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "api-key": api_key,
                },
                json=payload,
            )
        if response.status_code in (200, 201):
            return True
        logger.error(
            "Brevo email failed for %s: status=%s body=%s",
            to_email,
            response.status_code,
            response.text[:500],
        )
        return False
    except Exception as exc:
        logger.exception("Failed to send email to %s: %s", to_email, exc)
        return False


def send_temporary_password_email(to_email: str, temp_password: str, user_name: str) -> bool:
    portal_url = settings.dashboard_url.rstrip("/") + "/"
    subject = "YourSchoolPulse PTA Staff Portal Access"

    text_body = f"""Hello {user_name},

Your staff account for theSchoolPulse Management System is ready.

Sign in with:
  Email: {to_email}
  Temporary password: {temp_password}

Portal: {portal_url}

Use your email address and the temporary password above to log in. You will be asked to choose a new password immediately after signing in.

—SchoolPulse
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
            <div style="font-size:13px;opacity:0.9;letter-spacing:0.08em;text-transform:uppercase;">SchoolPulse</div>
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
            <a href="{portal_url}" style="display:inline-block;background:#f97316;color:#ffffff;text-decoration:none;padding:14px 24px;border-radius:999px;font-weight:700;">Open Staff Portal</a>
            <p style="margin:24px 0 0;font-size:13px;color:#64748b;">If the button does not work, copy this link:<br><a href="{portal_url}" style="color:#0d9488;">{portal_url}</a></p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;background:#f8fafc;color:#94a3b8;font-size:12px;">
           SchoolPulse PTA School · PTA Management System
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return _send_email(to_email, subject, html_body, text_body)


def send_password_reset_email(to_email: str, user_name: str, reset_token: str) -> bool:
    reset_url = f"{settings.dashboard_url.rstrip('/')}/reset-password?token={reset_token}"
    subject = "Reset yourSchoolPulse PTA staff password"

    text_body = f"""Hello {user_name},

We received a request to reset your staff portal password.

Open this link to choose a new password (valid for 1 hour):
{reset_url}

If you did not request this, you can ignore this email.

—SchoolPulse
"""

    html_body = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table width="100%" style="max-width:520px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 8px 24px rgba(15,23,42,0.08);">
        <tr><td style="background:linear-gradient(135deg,#0d9488,#0f766e);padding:28px 32px;color:#ffffff;">
          <div style="font-size:13px;opacity:0.9;">SchoolPulse</div>
          <div style="font-size:24px;font-weight:700;margin-top:6px;">Password reset</div>
        </td></tr>
        <tr><td style="padding:32px;color:#334155;line-height:1.6;">
          <p style="margin:0 0 16px;">Hello <strong>{user_name}</strong>,</p>
          <p style="margin:0 0 24px;">Use the button below to set a new password for your staff account. This link expires in one hour.</p>
          <a href="{reset_url}" style="display:inline-block;background:#f97316;color:#ffffff;text-decoration:none;padding:14px 24px;border-radius:999px;font-weight:700;">Reset password</a>
          <p style="margin:24px 0 0;font-size:13px;color:#64748b;">If you did not request this, ignore this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return _send_email(to_email, subject, html_body, text_body)
