from collections.abc import Generator
from contextlib import contextmanager

import jwt
import pymysql
from fastapi import Depends, Header, HTTPException, Request, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.organization_isolation import OrganizationContext, get_organization_context_from_request
from app.core.rbac import AccessContext, has_permission
from app.core.security import decode_access_token
from app.core.url_parsers import parse_mysql_url, parse_redis_url
from app.db.session import SessionLocal
from app.models import OrganizationMembership, User


@contextmanager
def get_mysql_connection() -> Generator:
    host, port, user, password, database = parse_mysql_url(settings.database_url)
    connection = pymysql.connect(
        host=host or "mysql",
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=3,
        read_timeout=3,
        write_timeout=3,
        charset="utf8mb4",
    )
    try:
        yield connection
    finally:
        connection.close()


def get_redis_client() -> Redis:
    host, port, db, password = parse_redis_url(settings.redis_url)
    return Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_organization_context(
    request: Request,
    db: Session = Depends(get_db_session),
) -> OrganizationContext:
    return get_organization_context_from_request(request, db)


def get_access_context(
    organization_context: OrganizationContext = Depends(get_organization_context),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> AccessContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_access_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc

    if claims["org"] != organization_context.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token organization scope mismatch.")

    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    membership = db.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_context.organization_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a member of this organization.")

    return AccessContext(
        user_id=user.id,
        organization_id=organization_context.organization_id,
        role=membership.role,
    )


def require_permission(permission: str):
    def _guard(access_context: AccessContext = Depends(get_access_context)) -> AccessContext:
        if not has_permission(access_context.role, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return access_context

    return _guard
