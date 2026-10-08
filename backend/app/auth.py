"""Identity, session rotation, and authorization helpers."""
from datetime import timedelta
from functools import wraps
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlparse

from flask import current_app, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from .database import db, utcnow
from .errors import ApiError
from .models import RefreshSession, User


def normalize_email(value):
    if not isinstance(value, str):
        raise ApiError("INVALID_FIELD", "A valid email is required", 422, {"email": "invalid"})
    value = value.strip().casefold()
    if not value or len(value) > 254 or "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ApiError("INVALID_FIELD", "A valid email is required", 422, {"email": "invalid"})
    return value


def hash_password(value):
    if not isinstance(value, str) or len(value) < 12 or len(value) > 256:
        raise ApiError("INVALID_FIELD", "Password must be between 12 and 256 characters", 422,
                       {"password": "invalid_length"})
    return generate_password_hash(value, method="scrypt")


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def encode_claims(claims):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = hmac.new(current_app.config["JWT_SECRET"].encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


def decode_access(raw):
    try:
        header, payload, signature = raw.split(".")
        expected = _b64(hmac.new(current_app.config["JWT_SECRET"].encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if claims.get("iss") != current_app.config["JWT_ISSUER"] or int(claims.get("exp", 0)) <= int(time.time()):
            raise ValueError
        return claims
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ApiError("INVALID_ACCESS_TOKEN", "Access token is invalid or expired", 401) from None


def access_token(user):
    now = utcnow()
    expires = now + timedelta(seconds=current_app.config["ACCESS_TOKEN_SECONDS"])
    token = encode_claims({"sub": user.id, "role": user.role.code, "iat": int(now.timestamp()),
                           "exp": int(expires.timestamp()), "iss": current_app.config["JWT_ISSUER"]})
    return token, expires

def token_hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh(user, replacement_for=None):
    raw = secrets.token_urlsafe(48)
    session = RefreshSession(user_id=user.id, token_hash=token_hash(raw),
                             expires_at=utcnow() + timedelta(seconds=current_app.config["REFRESH_TOKEN_SECONDS"]))
    db.session.add(session)
    db.session.flush()
    if replacement_for is not None:
        replacement_for.revoked_at = utcnow()
        replacement_for.replacement_id = session.id
    return raw, session


def revoke_descendants(session):
    now = utcnow()
    current = session
    while current is not None:
        if current.revoked_at is None:
            current.revoked_at = now
        current = current.replacement


def set_session_cookies(response, raw=None):
    settings = dict(secure=current_app.config["COOKIE_SECURE"], samesite="Strict", path="/api/v1/auth")
    if raw is None:
        response.delete_cookie("refresh_token", httponly=True, **settings)
        response.delete_cookie("csrf_token", **settings)  # Clear legacy narrow cookie.
        response.delete_cookie("csrf_token", secure=settings["secure"], samesite="Strict", path="/")
        return
    csrf = secrets.token_urlsafe(32)
    response.set_cookie("refresh_token", raw, httponly=True, max_age=current_app.config["REFRESH_TOKEN_SECONDS"], **settings)
    response.delete_cookie("csrf_token", **settings)  # Remove a pre-Phase-8 cookie.
    response.set_cookie("csrf_token", csrf, httponly=False, max_age=current_app.config["REFRESH_TOKEN_SECONDS"],
                        secure=settings["secure"], samesite="Strict", path="/")


def require_refresh_proof():
    origin = request.headers.get("Origin")
    allowed = current_app.config["ALLOWED_ORIGINS"]
    if not origin or origin not in allowed or urlparse(origin).scheme not in {"http", "https"}:
        raise ApiError("ORIGIN_DENIED", "Request origin is not allowed", 403)
    cookie = request.cookies.get("csrf_token")
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise ApiError("CSRF_FAILED", "CSRF proof is missing or invalid", 403)


def require_auth(*roles):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise ApiError("AUTH_REQUIRED", "Authentication is required", 401)
            claims = decode_access(header[7:])
            user = db.session.get(User, claims.get("sub"))
            if user is None or not user.active:
                raise ApiError("ACCOUNT_INACTIVE", "Account is unavailable", 401)
            if claims.get("role") != user.role.code:
                raise ApiError("INVALID_ACCESS_TOKEN", "Access token is invalid or expired", 401)
            if roles and user.role.code not in roles:
                raise ApiError("FORBIDDEN", "Operation is not permitted", 403)
            g.current_user = user
            return fn(*args, **kwargs)
        return wrapped
    return decorate
