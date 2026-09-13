"""
Sends the HTML report over Gmail SMTP using an App Password (never your
real Gmail password -- see README.md for how to generate one).

Reads configuration from environment variables (loaded from .env by
python-dotenv in main.py):
  EMAIL_SENDER        -- Gmail address the report is sent FROM
  EMAIL_APP_PASSWORD  -- 16-character Gmail App Password for that account
  EMAIL_RECIPIENT     -- address the report is sent TO
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("nifty_agent.emailer")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_report_email(html_body: str, subject: str) -> bool:
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT")

    missing = [name for name, val in [
        ("EMAIL_SENDER", sender), ("EMAIL_APP_PASSWORD", password), ("EMAIL_RECIPIENT", recipient)
    ] if not val]
    if missing:
        logger.error("Cannot send email -- missing env vars: %s. Check your .env file.", ", ".join(missing))
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info("Report email sent to %s", recipient)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail rejected the login. Make sure EMAIL_APP_PASSWORD is a 16-character "
            "App Password (not your normal Gmail password) and 2-Step Verification is on."
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send report email: %s", exc)
        return False
