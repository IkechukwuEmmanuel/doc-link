"""Email delivery selection (AUDIT B6).

The legacy (non-Supabase) flow must actually *send* when a provider is configured,
not silently log. Production uses gotrue for mail; this covers the fallback path.
"""

import pytest

from app.services import email as email_service


async def test_log_stub_when_no_provider(monkeypatch, caplog):
    monkeypatch.setattr(email_service.settings, "email_provider", "", raising=False)
    with caplog.at_level("INFO"):
        await email_service.send_email(to="a@b.com", subject="hi", body="x")
    assert any("email stub" in r.message for r in caplog.records)


async def test_smtp_branch_sends(monkeypatch):
    sent = {}

    def fake_send(*, to, subject, body):
        sent.update(to=to, subject=subject, body=body)

    monkeypatch.setattr(email_service.settings, "email_provider", "smtp", raising=False)
    monkeypatch.setattr(email_service, "_send_smtp_sync", fake_send)
    await email_service.send_email(to="a@b.com", subject="hi", body="link")
    assert sent == {"to": "a@b.com", "subject": "hi", "body": "link"}


async def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_provider", "carrier-pigeon", raising=False)
    with pytest.raises(NotImplementedError):
        await email_service.send_email(to="a@b.com", subject="hi", body="x")
