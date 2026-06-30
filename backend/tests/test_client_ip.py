"""Trusted-proxy client-IP resolution (AUDIT H1).

A client must not be able to forge ``X-Forwarded-For`` to obtain a fresh
rate-limit bucket per forged value.
"""

from starlette.requests import Request

from app.services import ratelimit


def _request(*, xff: str | None, peer: str = "203.0.113.7") -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 54321),
    }
    return Request(scope)


def test_default_ignores_forged_xff(monkeypatch):
    # Default topology: 0 trusted hops → header is ignored, peer IP is used.
    monkeypatch.setattr(ratelimit.settings, "trusted_proxy_hops", 0, raising=False)
    forged = _request(xff="1.2.3.4")
    forged2 = _request(xff="9.9.9.9")
    # Both forged values resolve to the SAME (peer) bucket — no fresh bucket.
    assert ratelimit.client_ip(forged) == "203.0.113.7"
    assert ratelimit.client_ip(forged2) == "203.0.113.7"


def test_single_trusted_proxy_uses_proxy_added_entry(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "trusted_proxy_hops", 1, raising=False)
    # Behind one trusted LB, the real client is the rightmost (proxy-added) entry.
    assert ratelimit.client_ip(_request(xff="198.51.100.5")) == "198.51.100.5"


def test_forged_prefix_ignored_behind_one_proxy(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "trusted_proxy_hops", 1, raising=False)
    # Attacker prepends junk; our LB appends the real client on the right. We take
    # the rightmost entry, so the forged prefix can't mint a new bucket.
    a = ratelimit.client_ip(_request(xff="9.9.9.9, 198.51.100.5"))
    b = ratelimit.client_ip(_request(xff="6.6.6.6, 198.51.100.5"))
    assert a == "198.51.100.5"
    assert a == b  # same real client → same bucket regardless of forged prefix


def test_too_short_chain_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "trusted_proxy_hops", 2, raising=False)
    # Claims fewer hops than configured → don't trust it; use the peer.
    assert ratelimit.client_ip(_request(xff="1.2.3.4")) == "203.0.113.7"
