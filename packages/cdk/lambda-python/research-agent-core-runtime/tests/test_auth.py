"""Tests for Cognito id_token verification (src.auth).

These lock in the fail-closed contract: agentic-research must never proceed
without a token that is present, correctly signed, and carries the expected
iss/aud/token_use/sub claims. Client-supplied claims (org, groups,
confidentiality) must never be trusted directly -- only what verify_id_token
extracts from a verified token.
"""

from types import SimpleNamespace

import jwt
import pytest

from src.auth import AuthenticationError, verify_id_token

REGION = "us-east-1"
USER_POOL_ID = "us-east-1_TestPool"
APP_CLIENT_ID = "test-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}"


@pytest.fixture(autouse=True)
def cognito_env(monkeypatch):
    monkeypatch.setenv("AGENTIC_RESEARCH_COGNITO_REGION", REGION)
    monkeypatch.setenv("AGENTIC_RESEARCH_COGNITO_USER_POOL_ID", USER_POOL_ID)
    monkeypatch.setenv("AGENTIC_RESEARCH_COGNITO_APP_CLIENT_ID", APP_CLIENT_ID)


def _patch_jwk_client(monkeypatch):
    """Stub out JWKS fetching; jwt.decode itself is patched per-test."""
    fake_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key="fake-key")
    )
    monkeypatch.setattr("src.auth._get_jwk_client", lambda jwks_url: fake_client)


def _valid_claims(**overrides):
    claims = {
        "sub": "user-123",
        "token_use": "id",
        "iss": ISSUER,
        "aud": APP_CLIENT_ID,
        "cognito:groups": ["dept-a", "dept-b"],
        "custom:org_code": "org-a",
        "custom:dept_codes": "dept-a,dept-b",
        "custom:allowed_confidentiality_levels": "internal,restricted",
    }
    claims.update(overrides)
    return claims


class TestMissingInputOrConfig:
    def test_missing_token_raises(self):
        with pytest.raises(AuthenticationError):
            verify_id_token(None)

    def test_empty_token_raises(self):
        with pytest.raises(AuthenticationError):
            verify_id_token("")

    def test_missing_config_raises(self, monkeypatch):
        monkeypatch.delenv("AGENTIC_RESEARCH_COGNITO_USER_POOL_ID", raising=False)
        with pytest.raises(AuthenticationError):
            verify_id_token("some.jwt.token")


class TestSuccessfulVerification:
    def test_valid_token_produces_expected_auth_context(self, monkeypatch):
        _patch_jwk_client(monkeypatch)
        monkeypatch.setattr("src.auth.jwt.decode", lambda *a, **k: _valid_claims())

        auth_context = verify_id_token("valid.jwt.token")

        assert auth_context.user_id == "user-123"
        assert auth_context.org_code == "org-a"
        assert auth_context.dept_codes == ["dept-a", "dept-b"]
        assert auth_context.groups == ["dept-a", "dept-b"]
        assert auth_context.allowed_confidentiality_levels == [
            "internal",
            "restricted",
        ]

    def test_missing_optional_claims_default_to_empty(self, monkeypatch):
        _patch_jwk_client(monkeypatch)
        monkeypatch.setattr(
            "src.auth.jwt.decode",
            lambda *a, **k: {"sub": "user-456", "token_use": "id"},
        )

        auth_context = verify_id_token("valid.jwt.token")

        assert auth_context.user_id == "user-456"
        assert auth_context.org_code is None
        assert auth_context.dept_codes == []
        assert auth_context.groups == []
        assert auth_context.allowed_confidentiality_levels == []


class TestVerificationParameters:
    def test_decode_is_called_with_issuer_audience_and_rs256(self, monkeypatch):
        _patch_jwk_client(monkeypatch)
        captured = {}

        def fake_decode(token, key, **kwargs):
            captured.update(kwargs)
            return _valid_claims()

        monkeypatch.setattr("src.auth.jwt.decode", fake_decode)

        verify_id_token("valid.jwt.token")

        assert captured["algorithms"] == ["RS256"]
        assert captured["issuer"] == ISSUER
        assert captured["audience"] == APP_CLIENT_ID
        assert set(captured["options"]["require"]) >= {"exp", "iss", "aud", "sub"}


class TestRejectedVerification:
    def test_signature_or_claim_failure_is_wrapped(self, monkeypatch):
        _patch_jwk_client(monkeypatch)

        def raise_invalid(*a, **k):
            raise jwt.InvalidSignatureError("bad signature")

        monkeypatch.setattr("src.auth.jwt.decode", raise_invalid)

        with pytest.raises(AuthenticationError):
            verify_id_token("tampered.jwt.token")

    def test_expired_token_is_rejected(self, monkeypatch):
        _patch_jwk_client(monkeypatch)

        def raise_expired(*a, **k):
            raise jwt.ExpiredSignatureError("expired")

        monkeypatch.setattr("src.auth.jwt.decode", raise_expired)

        with pytest.raises(AuthenticationError):
            verify_id_token("expired.jwt.token")

    def test_wrong_token_use_is_rejected(self, monkeypatch):
        _patch_jwk_client(monkeypatch)
        monkeypatch.setattr(
            "src.auth.jwt.decode",
            lambda *a, **k: _valid_claims(token_use="access"),
        )

        with pytest.raises(AuthenticationError):
            verify_id_token("access.jwt.token")

    def test_missing_sub_is_rejected(self, monkeypatch):
        _patch_jwk_client(monkeypatch)
        claims = _valid_claims()
        del claims["sub"]
        monkeypatch.setattr("src.auth.jwt.decode", lambda *a, **k: claims)

        with pytest.raises(AuthenticationError):
            verify_id_token("no-sub.jwt.token")
