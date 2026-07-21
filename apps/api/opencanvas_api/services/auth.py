from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import PasswordResetToken, User, UserSession, Workspace

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DUMMY_PASSWORD_HASH = (
    "scrypt$16384$8$1$4f3d15ead8f5f689a891fcb71b3afbb4$"
    "970022926e7a16ce7a544cd5f1c2cf5a021d0fab7efef5e3206c2b31d2bb8503"
)


class AuthenticationError(RuntimeError):
    pass


class PasswordPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    email: str
    display_name: str
    session_id: uuid.UUID | None
    csrf_token_hash: str | None
    synthetic: bool = False


@dataclass(frozen=True, slots=True)
class IssuedSession:
    principal: Principal
    session_token: str
    csrf_token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not _EMAIL.fullmatch(normalized):
        raise AuthenticationError("The email address or password is invalid.")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise PasswordPolicyError("Password must contain between 12 and 128 characters.")
    classes = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
    )
    if sum(classes) < 2:
        raise PasswordPolicyError(
            "Password must combine at least two of lowercase, uppercase, and numeric characters."
        )


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", maxsplit=5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected)),
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


async def create_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
) -> tuple[User, Workspace]:
    normalized = normalize_email(email)
    existing = await session.scalar(select(User.id).where(User.email_normalized == normalized))
    if existing is not None:
        raise AuthenticationError("An account could not be created with those details.")
    clean_name = " ".join(display_name.split()).strip()
    if not 1 <= len(clean_name) <= 120:
        raise AuthenticationError("A display name between 1 and 120 characters is required.")
    user = User(
        email=email.strip(),
        email_normalized=normalized,
        password_hash=hash_password(password),
        display_name=clean_name,
    )
    session.add(user)
    await session.flush()
    workspace = Workspace(
        owner_id=user.id,
        name=f"{clean_name}'s workspace",
        lifecycle_state="active",
    )
    session.add(workspace)
    await session.flush()
    return user, workspace


async def authenticate_account(session: AsyncSession, *, email: str, password: str) -> User:
    try:
        normalized = normalize_email(email)
    except AuthenticationError:
        normalized = "invalid@invalid.invalid"
    user = await session.scalar(select(User).where(User.email_normalized == normalized))
    encoded = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    valid = verify_password(password, encoded)
    if user is None or not valid or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError("The email address or password is invalid.")
    return user


async def issue_session(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedSession:
    now = datetime.now(UTC)
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=settings.session_ttl_minutes)
    record = UserSession(
        user_id=user.id,
        token_hash=token_hash(session_token, settings.session_secret),
        csrf_token_hash=token_hash(csrf_token, settings.session_secret),
        expires_at=expires_at,
        last_seen_at=now,
        user_agent_hash=_optional_digest(user_agent),
        ip_hash=_optional_digest(ip_address),
    )
    session.add(record)
    await session.flush()
    return IssuedSession(
        principal=Principal(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            session_id=record.id,
            csrf_token_hash=record.csrf_token_hash,
        ),
        session_token=session_token,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


async def resolve_session(
    session: AsyncSession,
    *,
    raw_token: str,
    settings: Settings,
) -> Principal:
    now = datetime.now(UTC)
    record = await session.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash(raw_token, settings.session_secret),
            UserSession.revoked_at.is_(None),
        )
    )
    if record is None or _as_utc(record.expires_at) <= now:
        raise AuthenticationError("Your session is invalid or has expired.")
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError("Your session is invalid or has expired.")
    record.last_seen_at = now
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        session_id=record.id,
        csrf_token_hash=record.csrf_token_hash,
    )


async def revoke_session(session: AsyncSession, session_id: uuid.UUID | None) -> None:
    if session_id is None:
        return
    await session.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def create_password_reset(
    session: AsyncSession, *, email: str, settings: Settings
) -> str | None:
    try:
        normalized = normalize_email(email)
    except AuthenticationError:
        return None
    user = await session.scalar(
        select(User).where(
            User.email_normalized == normalized,
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        return None
    raw_token = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash(raw_token, settings.session_secret),
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    await session.flush()
    return raw_token


async def reset_password(
    session: AsyncSession, *, raw_token: str, password: str, settings: Settings
) -> None:
    now = datetime.now(UTC)
    record = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash(raw_token, settings.session_secret),
            PasswordResetToken.used_at.is_(None),
        )
    )
    if record is None or _as_utc(record.expires_at) <= now:
        raise AuthenticationError("The password-reset link is invalid or has expired.")
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("The password-reset link is invalid or has expired.")
    user.password_hash = hash_password(password)
    record.used_at = now
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def csrf_matches(principal: Principal, raw_token: str | None, settings: Settings) -> bool:
    if principal.synthetic:
        return True
    if raw_token is None or principal.csrf_token_hash is None:
        return False
    return hmac.compare_digest(
        token_hash(raw_token, settings.session_secret), principal.csrf_token_hash
    )


def _optional_digest(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "AuthenticationError",
    "IssuedSession",
    "PasswordPolicyError",
    "Principal",
    "authenticate_account",
    "create_account",
    "create_password_reset",
    "csrf_matches",
    "hash_password",
    "issue_session",
    "normalize_email",
    "reset_password",
    "resolve_session",
    "revoke_session",
    "token_hash",
    "validate_password",
    "verify_password",
]
