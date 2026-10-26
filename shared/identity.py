"""Verify login identities against a configured issuer, never browser role claims."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException

from shared.config import settings


@dataclass(frozen=True)
class Identity:
    user_id: str
    issuer: str
    subject: str


@lru_cache(maxsize=4)
def _jwks(issuer: str):
    return jwt.PyJWKClient(
        issuer.rstrip("/") + "/.well-known/jwks.json", timeout=3, cache_jwk_set=True, lifespan=300
    )


def verify_identity(token: str) -> Identity:
    if not settings.jwt_issuer or not settings.jwt_audience:
        raise HTTPException(503, "User login is not configured")
    if len(token) > 8192:
        raise HTTPException(401, "Invalid login token")
    try:
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or not 1 <= len(header["kid"]) <= 200
        ):
            raise jwt.InvalidTokenError("Unsupported signing header")
        key = _jwks(settings.jwt_issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise jwt.InvalidTokenError("Invalid subject")
        if (
            settings.jwt_authorized_parties
            and claims.get("azp") not in settings.jwt_authorized_parties
        ):
            raise jwt.InvalidTokenError("Unauthorized party")
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Login verification temporarily unavailable") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            401, "Invalid or expired login token", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    user_id = "usr_" + hashlib.sha256(f"{claims['iss']}\x00{subject}".encode()).hexdigest()
    return Identity(user_id, claims["iss"], subject)


def ensure_user(conn, identity: Identity) -> None:
    conn.execute(
        "INSERT INTO app_users(user_id,issuer,subject) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        (identity.user_id, identity.issuer, identity.subject),
    )
