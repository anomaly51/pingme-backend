import json
import logging
import os
import smtplib
from email.message import EmailMessage
from urllib import request


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


def send_reminder_notification(email: str, title: str) -> None:
    send_email(
        email,
        f"PingMe reminder: {title}",
        f"Reminder due: {title}\n\nOpen PingMe to complete, skip, or cancel it.",
    )


def send_push_notification(push_token: str, title: str, payload: dict) -> None:
    webhook_url = os.getenv("PUSH_WEBHOOK_URL")
    if not webhook_url:
        logger.info("Push delivery is not configured. Token=%s title=%s", push_token, title)
        return

    body = json.dumps(
        {
            "token": push_token,
            "title": title,
            "payload": payload,
        }
    ).encode("utf-8")
    push_request = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(push_request, timeout=10) as response:
        response.read()
