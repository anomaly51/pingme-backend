import logging
import os
import smtplib
from email.message import EmailMessage


logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("SMTP_FROM_EMAIL") or username

    if not host or not from_email:
        logger.info(
            "Email delivery is not configured. To=%s subject=%s body=%s",
            to_email,
            subject,
            body,
        )
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}

    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def send_email_verification_code(email: str, code: str) -> None:
    send_email(
        email,
        "PingMe email verification code",
        f"Your PingMe verification code is: {code}\n\nIt expires in 15 minutes.",
    )


def send_password_reset_code(email: str, code: str) -> None:
    send_email(
        email,
        "PingMe password reset code",
        f"Your PingMe password reset code is: {code}\n\nIt expires in 15 minutes.",
    )
