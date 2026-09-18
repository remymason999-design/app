"""Focused unit tests for native Apple identity-token verification."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from core import public_user
from routers import auth


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()


class _SigningKey:
    key = PUBLIC_KEY


class _JwksClient:
    def get_signing_key_from_jwt(self, _token):
        return _SigningKey()


@pytest.fixture(autouse=True)
def fake_apple_jwks(monkeypatch):
    monkeypatch.setattr(auth, "_apple_jwks_client", _JwksClient())


def _token(**overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": auth.APPLE_ISSUER,
        "aud": auth.APPLE_NATIVE_CLIENT_ID,
        "sub": "apple-stable-subject",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "email": "hidden@privaterelay.appleid.com",
        "email_verified": "true",
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": "test"})


def test_accepts_valid_apple_token_and_private_relay_email():
    claims = auth._verify_apple_identity_token(_token())
    assert claims["sub"] == "apple-stable-subject"
    assert auth._apple_claim_email(claims) == "hidden@privaterelay.appleid.com"


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://not-apple.example"),
        ("aud", "wrong.client"),
        ("exp", datetime.now(timezone.utc) - timedelta(minutes=1)),
        ("sub", ""),
    ],
)
def test_rejects_invalid_required_claims(claim, value):
    with pytest.raises(HTTPException) as exc:
        auth._verify_apple_identity_token(_token(**{claim: value}))
    assert exc.value.status_code == 401


def test_rejects_invalid_signature():
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": auth.APPLE_ISSUER,
            "aud": auth.APPLE_NATIVE_CLIENT_ID,
            "sub": "subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        other_key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    with pytest.raises(HTTPException) as exc:
        auth._verify_apple_identity_token(token)
    assert exc.value.status_code == 401


class _Users:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc):
        if any(
            existing.get("email") == doc.get("email")
            or existing.get("apple_sub") == doc.get("apple_sub")
            for existing in self.docs
        ):
            raise auth.DuplicateKeyError("duplicate")
        self.docs.append(dict(doc))

    async def update_one(self, query, update):
        for doc in self.docs:
            if doc.get("user_id") == query.get("user_id"):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


def _request():
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/apple",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )


def _apple_payload():
    return auth.AppleAuthIn(
        identity_token="verified-by-test-double",
        authorization_code="one-time-code",
        apple_user="apple-stable-subject",
        full_name="Relay User",
        email="untrusted@client.example",
    )


def test_new_relay_user_and_returning_user_share_watchsmart_sessions(monkeypatch):
    users = _Users()
    seeded = []
    claims = {
        "sub": "apple-stable-subject",
        "email": "hidden@privaterelay.appleid.com",
        "email_verified": "true",
    }
    monkeypatch.setattr(auth, "db", SimpleNamespace(users=users))
    monkeypatch.setattr(auth, "_verify_apple_identity_token", lambda _token: claims)

    async def exchange(_code, _expected_sub):
        return "server-only-apple-refresh"

    async def seed(user_id):
        seeded.append(user_id)

    monkeypatch.setattr(auth, "_exchange_apple_authorization_code", exchange)
    monkeypatch.setattr(auth, "seed_notifications_for_user", seed)

    create_result = asyncio.run(
        auth.native_apple_login.__wrapped__(_request(), _apple_payload(), Response())
    )
    assert create_result["user"]["email"] == "hidden@privaterelay.appleid.com"
    assert "apple_sub" not in create_result["user"]
    assert "apple_refresh_token" not in create_result["user"]
    assert create_result["access_token"] and create_result["refresh_token"]
    assert len(seeded) == 1

    claims.pop("email")
    claims.pop("email_verified")
    returning_result = asyncio.run(
        auth.native_apple_login.__wrapped__(_request(), _apple_payload(), Response())
    )
    assert returning_result["user"]["user_id"] == create_result["user"]["user_id"]
    assert len(seeded) == 1


def test_existing_email_requires_authenticated_linking(monkeypatch):
    users = _Users(
        [
            {
                "user_id": "existing-user",
                "email": "person@example.com",
                "name": "Existing",
                "password_hash": "not-used",
            }
        ]
    )
    monkeypatch.setattr(auth, "db", SimpleNamespace(users=users))
    monkeypatch.setattr(
        auth,
        "_verify_apple_identity_token",
        lambda _token: {
            "sub": "new-apple-sub",
            "email": "person@example.com",
            "email_verified": True,
        },
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.native_apple_login.__wrapped__(_request(), _apple_payload(), Response())
        )
    assert exc.value.status_code == 409
    assert users.docs[0].get("apple_sub") is None


def test_public_user_never_exposes_apple_credentials():
    result = public_user(
        {
            "user_id": "u1",
            "email": "person@example.com",
            "apple_sub": "stable-subject",
            "apple_refresh_token": "secret-refresh-token",
        }
    )
    assert "apple_sub" not in result
    assert "apple_refresh_token" not in result


def test_exchanged_authorization_must_match_verified_subject(monkeypatch):
    monkeypatch.setattr(
        auth,
        "_verify_apple_identity_token",
        lambda _token: {"sub": "different-apple-subject"},
    )
    with pytest.raises(HTTPException) as exc:
        auth._validated_apple_token_exchange(
            {"id_token": "exchange-id-token", "refresh_token": "refresh"},
            "expected-apple-subject",
        )
    assert exc.value.status_code == 401


def test_apple_client_secret_accepts_flattened_p8(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    flattened = pem.replace("\n", "\\n")
    monkeypatch.setenv("APPLE_TEAM_ID", "TESTTEAM")
    monkeypatch.setenv("APPLE_KEY_ID", "TESTKEY")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", f'"{flattened}"')
    client_secret = auth._apple_client_secret()
    claims = jwt.decode(client_secret, options={"verify_signature": False})
    assert claims["iss"] == "TESTTEAM"
    assert claims["sub"] == "com.watchsmart.app"

    body_only = "".join(
        line for line in pem.splitlines() if not line.startswith("-----")
    )
    monkeypatch.setenv("APPLE_PRIVATE_KEY", body_only)
    body_only_secret = auth._apple_client_secret()
    body_only_claims = jwt.decode(
        body_only_secret,
        options={"verify_signature": False},
    )
    assert body_only_claims["iss"] == "TESTTEAM"