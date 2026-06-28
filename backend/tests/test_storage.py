"""Unit tests for the Supabase Storage helper quirks.

The full upload/download/delete path is exercised end-to-end elsewhere via the
fake-storage fixture (and was confirmed against live Supabase). These cover the
not-found handling, which Supabase signals inconsistently."""

import httpx

from app.services import storage


def _resp(status_code: int, *, json=None, text=""):
    if json is not None:
        return httpx.Response(status_code, json=json)
    return httpx.Response(status_code, text=text)


def test_is_not_found_true_real_404():
    assert storage._is_not_found(_resp(404, text="Not Found")) is True


def test_is_not_found_true_supabase_400_with_404_body():
    # Supabase single-object DELETE returns HTTP 400 with a 404 in the body.
    assert storage._is_not_found(
        _resp(400, json={"statusCode": "404", "error": "not_found", "message": "Object not found"})
    ) is True


def test_is_not_found_true_error_not_found():
    assert storage._is_not_found(_resp(400, json={"error": "not_found"})) is True


def test_is_not_found_false_on_other_errors():
    assert storage._is_not_found(_resp(403, json={"error": "unauthorized"})) is False
    assert storage._is_not_found(_resp(500, text="boom")) is False
