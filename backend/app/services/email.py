"""Transactional email delivery. Phase 7.

⚠️ BLOCKER (same pattern as the ClamAV entry in DECISIONS.md): no real email
provider is wired in this environment. When ``settings.email_provider`` is empty
(the default), emails are *logged* rather than sent — the message and any action
link are written to the application log so flows are exercisable end-to-end in
dev. Before launch, set ``EMAIL_PROVIDER`` and credentials and implement the
matching branch in ``send_email``.

The boring provider choice to implement first is SMTP (works with any
transactional sender — Postmark, SES, Mailgun — via their SMTP endpoint), so no
vendor SDK lock-in. Documented in DECISIONS.md.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("spacepad.email")
settings = get_settings()


async def send_email(*, to: str, subject: str, body: str) -> None:
    if not settings.email_provider:
        # Console/log stub. NEVER silently drop — make it visible in dev.
        logger.info(
            "[email stub] to=%s subject=%r\n%s\n(set EMAIL_PROVIDER to send for real)",
            to,
            subject,
            body,
        )
        return
    # pragma: no cover — real provider integration is a launch task.
    raise NotImplementedError(
        f"Email provider {settings.email_provider!r} is configured but not implemented."
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
