import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    hashed = hash_password("StrongPass123!")
    assert hashed != "StrongPass123!"
    assert verify_password("StrongPass123!", hashed) is True
    assert verify_password("WrongPass!", hashed) is False


def test_access_token_create_and_decode() -> None:
    token = create_access_token("user-123", "11111111-1111-1111-1111-111111111111", "admin")
    claims = decode_access_token(token)
    assert claims["sub"] == "user-123"
    assert claims["org"] == "11111111-1111-1111-1111-111111111111"
    assert claims["role"] == "admin"
    assert claims["type"] == "access"


def test_decode_access_token_rejects_wrong_type() -> None:
    invalid_token = jwt.encode(
        {"sub": "user-123", "type": "refresh"},
        settings.app_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    try:
        decode_access_token(invalid_token)
    except jwt.InvalidTokenError:
        return
    raise AssertionError("Expected InvalidTokenError for non-access token")


def test_refresh_token_generation_and_hashing() -> None:
    token = generate_refresh_token()
    assert len(token) >= 32
    hashed = hash_refresh_token(token)
    assert len(hashed) == 64
    assert hashed == hash_refresh_token(token)
