"""Local browser protections; API mutations use the same CSRF cookie/header."""
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def check_csrf(request: Request, token: str | None) -> None:
    origin = request.headers.get("origin")
    expected = urlsplit(str(request.base_url))
    if origin:
        try:
            actual = urlsplit(origin)
        except ValueError as exc:
            raise HTTPException(403, "Invalid origin") from exc
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(403, "Cross-origin mutation blocked")
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        raise HTTPException(403, "Cross-site mutation blocked")
    cookie = request.cookies.get("csrf_token")
    if not cookie or not token or not secrets.compare_digest(cookie, token):
        raise HTTPException(403, "Valid CSRF cookie and token required; first GET /api/health or the dashboard")


def require_csrf(request: Request) -> None:
    check_csrf(request, request.headers.get("x-csrf-token"))
