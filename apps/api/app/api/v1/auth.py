from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)
from app.models import Organization, OrganizationMembership, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _validate_org_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization_id format.") from exc


def _revoke_active_tokens(db: Session, user_id: str, organization_id: str, reason: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.organization_id == organization_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
    )


def _issue_tokens(
    db: Session,
    user: User,
    organization_id: str,
    role: str,
    revoke_existing_reason: str,
) -> TokenResponse:
    _revoke_active_tokens(db, user.id, organization_id, revoke_existing_reason)
    access_token = create_access_token(user.id, organization_id, role)
    raw_refresh = generate_refresh_token()
    refresh_row = RefreshToken(
        id=str(uuid4()),
        user_id=user.id,
        organization_id=organization_id,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=refresh_token_expires_at(),
    )
    db.add(refresh_row)
    db.commit()
    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db_session)) -> UserResponse:
    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists.")

    user = User(
        id=str(uuid4()),
        email=payload.email.lower(),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    organization_id = _validate_org_id(payload.organization_id)
    organization = db.get(Organization, organization_id)
    if organization is None or not organization.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found or inactive.")

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a member of this organization.")

    return _issue_tokens(
        db=db,
        user=user,
        organization_id=organization_id,
        role=membership.role,
        revoke_existing_reason="rotated_login",
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db_session)) -> TokenResponse:
    organization_id = _validate_org_id(payload.organization_id)
    token_hash = hash_refresh_token(payload.refresh_token)
    token_row = db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if (
        token_row is None
        or token_row.organization_id is None
        or token_row.revoked_at is not None
        or token_row.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    user = db.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        token_row.revoked_at = datetime.now(UTC)
        token_row.revoked_reason = "membership_missing"
        db.add(token_row)
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a member of this organization.")

    token_row.revoked_at = datetime.now(UTC)
    token_row.revoked_reason = "rotated_refresh"
    db.add(token_row)
    db.commit()
    return _issue_tokens(
        db=db,
        user=user,
        organization_id=organization_id,
        role=membership.role,
        revoke_existing_reason="rotated_refresh",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db_session)) -> None:
    organization_id = _validate_org_id(payload.organization_id)
    token_hash = hash_refresh_token(payload.refresh_token)
    token_row = db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = datetime.now(UTC)
        token_row.revoked_reason = "logout"
        db.add(token_row)
        db.commit()


@router.get("/me", response_model=UserResponse)
def me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> UserResponse:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc
    if claims.get("org") is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name)
