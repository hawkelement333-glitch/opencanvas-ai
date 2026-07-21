from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import Field, SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.api.dependencies import (
    MutatingPrincipalDep,
    PrincipalDep,
    enforce_auth_rate_limit,
    get_session,
)
from opencanvas_api.api.errors import ApiError
from opencanvas_api.api.schemas import ApiModel
from opencanvas_api.core.config import AppMode, Settings, get_settings
from opencanvas_api.db.models import (
    CanonicalObject,
    CanonicalRelationship,
    Canvas,
    DataExportRequest,
    Document,
    DocumentFile,
    DocumentVersion,
    User,
    UserSession,
    Workspace,
)
from opencanvas_api.services.auth import (
    AuthenticationError,
    IssuedSession,
    PasswordPolicyError,
    authenticate_account,
    create_account,
    create_password_reset,
    issue_session,
    reset_password,
    revoke_session,
    verify_password,
)
from opencanvas_api.services.documents import DocumentServiceError, build_document_storage
from opencanvas_api.services.email import EmailDeliveryError, deliver_password_reset

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class SignUpInput(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=120)


class SignInInput(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool


class AuthSessionOut(ApiModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class PasswordResetRequestInput(ApiModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetRequestOut(ApiModel):
    accepted: bool = True
    development_token: str | None = None


class PasswordResetConfirmInput(ApiModel):
    token: SecretStr
    password: SecretStr


class AccountPatch(ApiModel):
    display_name: str = Field(min_length=1, max_length=120)


class AccountDeleteInput(ApiModel):
    password: SecretStr
    confirmation: str


class DataExportOut(ApiModel):
    id: uuid.UUID
    status: str
    created_at: datetime


@router.post(
    "/auth/signup",
    response_model=AuthSessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def sign_up(
    payload: SignUpInput,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthSessionOut:
    if settings.demo_mode:
        raise ApiError(status.HTTP_403_FORBIDDEN, "demo_read_only", "Demo accounts are disabled.")
    try:
        user, _ = await create_account(
            session,
            email=payload.email,
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
        )
        issued = await issue_session(
            session,
            user=user,
            settings=settings,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except (AuthenticationError, PasswordPolicyError) as exc:
        await session.rollback()
        raise ApiError(status.HTTP_400_BAD_REQUEST, "account_creation_failed", str(exc)) from exc
    _set_session_cookies(response, issued, settings)
    return _session_out(user, issued)


@router.post(
    "/auth/signin",
    response_model=AuthSessionOut,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def sign_in(
    payload: SignInInput,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthSessionOut:
    if settings.demo_mode:
        raise ApiError(status.HTTP_403_FORBIDDEN, "demo_read_only", "Demo sign-in is disabled.")
    try:
        user = await authenticate_account(
            session,
            email=payload.email,
            password=payload.password.get_secret_value(),
        )
        issued = await issue_session(
            session,
            user=user,
            settings=settings,
            user_agent=request.headers.get("User-Agent"),
            ip_address=request.client.host if request.client else None,
        )
        await session.commit()
    except AuthenticationError as exc:
        await session.rollback()
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            "The email address or password is invalid.",
        ) from exc
    _set_session_cookies(response, issued, settings)
    return _session_out(user, issued)


@router.post("/auth/signout", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    response: Response,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    await revoke_session(session, principal.session_id)
    await session.commit()
    _clear_session_cookies(response, settings)


@router.get("/auth/me", response_model=UserOut)
async def current_account(principal: PrincipalDep, session: SessionDep) -> UserOut:
    user = await session.get(User, principal.user_id)
    if user is None:
        return UserOut(
            id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            email_verified=True,
        )
    return _user_out(user)


@router.post(
    "/auth/password-reset/request",
    response_model=PasswordResetRequestOut,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def request_password_reset(
    payload: PasswordResetRequestInput,
    session: SessionDep,
    settings: SettingsDep,
) -> PasswordResetRequestOut:
    token = await create_password_reset(session, email=payload.email, settings=settings)
    if token is not None and settings.password_reset_provider == "smtp":
        try:
            await deliver_password_reset(
                settings=settings,
                recipient=payload.email,
                raw_token=token,
            )
        except EmailDeliveryError as exc:
            await session.rollback()
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "password_reset_delivery_unavailable",
                "Password reset delivery is temporarily unavailable.",
            ) from exc
    await session.commit()
    visible_token = (
        token
        if token is not None and settings.runtime_mode in {AppMode.DEVELOPMENT, AppMode.TEST}
        else None
    )
    return PasswordResetRequestOut(development_token=visible_token)


@router.post(
    "/auth/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def confirm_password_reset(
    payload: PasswordResetConfirmInput,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    try:
        await reset_password(
            session,
            raw_token=payload.token.get_secret_value(),
            password=payload.password.get_secret_value(),
            settings=settings,
        )
        await session.commit()
    except (AuthenticationError, PasswordPolicyError) as exc:
        await session.rollback()
        raise ApiError(status.HTTP_400_BAD_REQUEST, "password_reset_failed", str(exc)) from exc


@router.patch("/account", response_model=UserOut)
async def update_account(
    payload: AccountPatch,
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> UserOut:
    user = await session.get(User, principal.user_id)
    if user is None or principal.synthetic:
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_read_only", "This account is read-only.")
    user.display_name = " ".join(payload.display_name.split())
    await session.commit()
    return _user_out(user)


@router.post("/account/export", response_model=DataExportOut, status_code=status.HTTP_202_ACCEPTED)
async def request_data_export(
    principal: MutatingPrincipalDep,
    session: SessionDep,
) -> DataExportOut:
    if principal.synthetic:
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_read_only", "Demo export is disabled.")
    export = DataExportRequest(user_id=principal.user_id)
    session.add(export)
    await session.commit()
    return DataExportOut(id=export.id, status=export.status, created_at=export.created_at)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: AccountDeleteInput,
    response: Response,
    principal: MutatingPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    user = await session.get(User, principal.user_id)
    if (
        user is None
        or principal.synthetic
        or payload.confirmation != "DELETE MY ACCOUNT"
        or not verify_password(payload.password.get_secret_value(), user.password_hash)
    ):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "account_deletion_failed",
            "The account could not be deleted with those details.",
        )
    workspace_ids = list(
        (await session.scalars(select(Workspace.id).where(Workspace.owner_id == user.id))).all()
    )
    if workspace_ids:
        document_ids = (
            select(Document.id).join(Canvas).where(Canvas.workspace_id.in_(workspace_ids))
        )
        storage_keys = set(
            (
                await session.scalars(
                    select(DocumentFile.storage_key).where(
                        DocumentFile.document_id.in_(document_ids)
                    )
                )
            ).all()
        )
        storage_keys.update(
            (
                await session.scalars(
                    select(DocumentVersion.storage_key).where(
                        DocumentVersion.document_id.in_(document_ids)
                    )
                )
            ).all()
        )
        storage = build_document_storage(settings)
        try:
            for storage_key in storage_keys:
                await storage.delete(storage_key)
        except DocumentServiceError as exc:
            await session.rollback()
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "account_deletion_unavailable",
                "Account deletion is temporarily unavailable. No database data was removed.",
            ) from exc
        await session.execute(
            delete(CanonicalRelationship).where(
                CanonicalRelationship.workspace_id.in_(workspace_ids)
            )
        )
        await session.execute(
            delete(CanonicalObject).where(CanonicalObject.workspace_id.in_(workspace_ids))
        )
        await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id)
        .values(revoked_at=datetime.now(UTC))
    )
    await session.delete(user)
    await session.commit()
    _clear_session_cookies(response, settings)


def _session_out(user: User, issued: IssuedSession) -> AuthSessionOut:
    return AuthSessionOut(
        user=_user_out(user),
        csrf_token=issued.csrf_token,
        expires_at=issued.expires_at,
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified,
    )


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        settings.session_cookie_name,
        issued.session_token,
        max_age=max_age,
        expires=issued.expires_at,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite=settings.session_same_site,
    )
    response.set_cookie(
        f"{settings.session_cookie_name}_csrf",
        issued.csrf_token,
        max_age=max_age,
        expires=issued.expires_at,
        path="/",
        secure=settings.secure_cookies,
        httponly=False,
        samesite=settings.session_same_site,
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(f"{settings.session_cookie_name}_csrf", path="/")
