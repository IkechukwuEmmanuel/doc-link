"""Transactional email delivery. Phase 7.

Delivery path is selected by ``settings.email_provider``:

  - ``""`` (default): console/log stub — the message + action link are written to
    the application log so flows are exercisable end-to-end in dev WITHOUT
    silently dropping mail. Only appropriate for dev/test.
  - ``"smtp"``: a real send over SMTP (``EMAIL_SMTP_*`` settings). SMTP is
    vendor-neutral — Postmark / SES / Mailgun all expose an SMTP endpoint — so
    there is no SDK lock-in. See DECISIONS.md (AUDIT B6).

NOTE on reachability: in the Supabase production deployment, gotrue sends all
transactional mail (password recovery, email verification) directly — every auth
route returns via the Supabase branch before reaching ``send_email``. This module
is the delivery path for the *legacy* (non-Supabase) auth flow only: the test
harness and any self-hosted deployment without Supabase configured. It is wired to
send for real (not a stub) whenever ``EMAIL_PROVIDER`` is set, which closes the
"silently never delivers" gap the audit flagged.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("spacepad.email")
settings = get_settings()


def _send_smtp_sync(*, to: str, subject: str, body: str) -> None:
    """Blocking SMTP send. Run via a thread so the event loop isn't blocked."""
    if not settings.email_smtp_host:
        raise RuntimeError("EMAIL_PROVIDER=smtp but EMAIL_SMTP_HOST is not set.")
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as smtp:
        if settings.email_smtp_starttls:
            smtp.starttls()
        if settings.email_smtp_username:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password)
        smtp.send_message(msg)


async def send_email(*, to: str, subject: str, body: str) -> None:
    provider = settings.email_provider
    if not provider:
        # Console/log stub. NEVER silently drop — make it visible in dev.
        logger.info(
            "[email stub] to=%s subject=%r\n%s\n(set EMAIL_PROVIDER to send for real)",
            to,
            subject,
            body,
        )
        return
    if provider == "smtp":
        await asyncio.to_thread(_send_smtp_sync, to=to, subject=subject, body=body)
        logger.info("[email] sent via SMTP to=%s subject=%r", to, subject)
        return
    raise NotImplementedError(
        f"Email provider {provider!r} is configured but not implemented "
        "(supported: '' for log-stub, 'smtp')."
    )


def password_reset_email(link: str) -> tuple[str, str]:
    subject = "Reset your SpacePad password"
    body = (
        "We received a request to reset your SpacePad password.\n\n"
        f"Reset it here (link expires in 1 hour): {link}\n\n"
        "If you didn't request this, you can ignore this email."
    )
    return subject, body


def verify_email_email(link: str) -> tuple[str, str]:
    subject = "Verify your SpacePad email"
    body = (
        "Confirm your email address to unlock private pads.\n\n"
        f"Verify here: {link}\n\n"
        "If you didn't create a SpacePad account, you can ignore this email."
    )
    return subject, body
