import time

import jwt
import pytest
from fastapi import HTTPException

from shared.config import settings
from shared.identity import verify_identity


def test_signed_identity_is_stable_and_roles_are_not_identity(jwt_signer):
    a = verify_identity(jwt_signer(role="admin"))
    b = verify_identity(jwt_signer(role="member"))
    assert a == b
    assert a.user_id.startswith("usr_") and len(a.user_id) == 68


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-api"},
        {"iss": "https://attacker.test"},
        {"exp": 1},
        {"iat": int(time.time()) + 100000},
        {"sub": ""},
        {"sub": "x" * 256},
        {"exp": None},
    ],
)
def test_invalid_login_tokens_are_rejected(jwt_signer, overrides):
    with pytest.raises(HTTPException) as exc:
        verify_identity(jwt_signer(**overrides))
    assert exc.value.status_code == 401


def test_unsigned_and_symmetric_tokens_cannot_bypass_rs256(jwt_signer):
    valid = jwt.decode(jwt_signer(), options={"verify_signature": False})
    for algorithm, key in [("none", ""), ("HS256", "x" * 40)]:
        with pytest.raises(HTTPException) as exc:
            verify_identity(jwt.encode(valid, key, algorithm=algorithm))
        assert exc.value.status_code == 401


def test_authorized_party_is_checked_when_configured(jwt_signer, monkeypatch):
    monkeypatch.setattr(settings, "jwt_authorized_parties", ["https://site.test"])
    with pytest.raises(HTTPException):
        verify_identity(jwt_signer(azp="https://another.test"))
    assert verify_identity(jwt_signer(azp="https://site.test"))


def test_modified_signed_claims_fail_signature_verification(jwt_signer):
    import base64
    import json

    token = jwt_signer()
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "somebody-else"
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    with pytest.raises(HTTPException) as exc:
        verify_identity(f"{header}.{forged_payload}.{signature}")
    assert exc.value.status_code == 401
