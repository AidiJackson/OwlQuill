"""Email sending service.

In production, configure SMTP_* environment variables.
In development (DEBUG=True), emails are printed to console.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_reset_email(to_email: str, reset_url: str) -> None:
    """Send a password reset email.

    Args:
        to_email: Recipient email address.
        reset_url: Full URL to the reset password page with token.
    """
    subject = "Reset your Ficshon password"
    html_body = f"""\
<html>
<body style="font-family: sans-serif; color: #333;">
  <h2>Reset your Ficshon password</h2>
  <p>You requested a password reset. Click the link below to set a new password:</p>
  <p><a href="{reset_url}" style="display:inline-block;padding:10px 24px;background:#6d28d9;color:#fff;border-radius:6px;text-decoration:none;">Reset Password</a></p>
  <p>Or copy this link into your browser:</p>
  <p style="word-break:break-all;">{reset_url}</p>
  <p>This link expires in {settings.RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>
  <p>If you did not request this reset, you can safely ignore this email.</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="color:#999;font-size:12px;">Ficshon</p>
</body>
</html>"""

    text_body = (
        f"Reset your Ficshon password\n\n"
        f"You requested a password reset. Visit this link to set a new password:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in {settings.RESET_TOKEN_EXPIRE_MINUTES} minutes.\n\n"
        f"If you did not request this reset, you can safely ignore this email."
    )

    # Dev / unconfigured: log to console instead of sending
    if not settings.SMTP_HOST:
        logger.info("=" * 60)
        logger.info("PASSWORD RESET EMAIL (dev mode - not sent)")
        logger.info(f"  To: {to_email}")
        logger.info(f"  Subject: {subject}")
        logger.info(f"  Reset URL: {reset_url}")
        logger.info("=" * 60)
        # Also print so it shows in console even without logging config
        print(f"\n{'='*60}")
        print(f"PASSWORD RESET EMAIL (dev mode)")
        print(f"  To: {to_email}")
        print(f"  Reset URL: {reset_url}")
        print(f"{'='*60}\n")
        return

    # Production: send via SMTP
    from_addr = formataddr(("Ficshon", settings.SMTP_FROM))
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())
        logger.info(f"Password reset email sent to {to_email}")
    except Exception:
        logger.exception(f"Failed to send password reset email to {to_email}")
        raise
