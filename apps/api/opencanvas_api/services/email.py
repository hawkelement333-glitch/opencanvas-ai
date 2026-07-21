from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from opencanvas_api.core.config import Settings


class EmailDeliveryError(RuntimeError):
    pass


async def deliver_password_reset(*, settings: Settings, recipient: str, raw_token: str) -> None:
    if settings.password_reset_provider != "smtp":
        return
    if settings.smtp_host is None or settings.smtp_from_address is None:
        raise EmailDeliveryError("Password reset delivery is not configured.")
    reset_url = f"{settings.app_url}/reset-password?token={quote(raw_token, safe='')}"
    message = EmailMessage()
    message["Subject"] = "Reset your SolarPlexus Mobius password"
    message["From"] = settings.smtp_from_address
    message["To"] = recipient
    message.set_content(
        "A password reset was requested for your SolarPlexus Mobius account.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this message."
    )
    try:
        await asyncio.to_thread(_send_smtp, settings, message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError("Password reset delivery failed.") from exc


def _send_smtp(settings: Settings, message: EmailMessage) -> None:
    assert settings.smtp_host is not None
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username is not None:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)
