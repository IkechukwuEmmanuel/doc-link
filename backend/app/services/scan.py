"""Malware scanning. Phase 3.

⚠️ Fails CLOSED (see DECISIONS.md): if a real scanner is not reachable, content
is marked ``failed`` — never ``clean`` — so nothing unscanned is ever served.
A real ClamAV daemon is used when ``CLAMAV_ENABLED`` is set and reachable.
"""

from __future__ import annotations

import io
import logging

import anyio

from app.core.config import get_settings
from app.models.file import ScanStatus

logger = logging.getLogger(__name__)
settings = get_settings()


def _clamd_verdict(data: bytes) -> ScanStatus:
    import clamd

    client = clamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port)
    client.ping()
    result = client.instream(io.BytesIO(data))
    status = result.get("stream", ("ERROR",))[0]
    if status == "OK":
        return ScanStatus.clean
    logger.warning("ClamAV flagged upload: %s", result)
    return ScanStatus.failed


async def scan(data: bytes) -> ScanStatus:
    """Return the scan verdict for ``data``.

    Returns ``failed`` rather than raising on any error, so the caller can persist
    the verdict and refuse to serve the file.
    """
    if not settings.clamav_enabled:
        logger.warning("Scanning disabled (CLAMAV_ENABLED is false) — failing closed.")
        return ScanStatus.failed
    try:
        # clamd is blocking; run it off the event loop.
        return await anyio.to_thread.run_sync(_clamd_verdict, data)
    except Exception:
        logger.exception("Scanner unreachable/error — failing closed.")
        return ScanStatus.failed
