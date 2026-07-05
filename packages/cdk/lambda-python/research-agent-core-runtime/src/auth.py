"""Cognito ID token verification for agentic-research mode.

The client is never trusted to state its own identity, org, groups, or
confidentiality clearance: those values are derived exclusively from a
signature- and claim-verified Cognito id_token here, then handed to business
MCP servers out-of-band (never through LLM-controlled tool input).
"""

import json
import logging
import os
from dataclasses import dataclass, field

import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when an id_token is missing, malformed, or fails verification."""


@dataclass(frozen=True)
class AgenticResearchAuthContext:
    """Trusted identity/authorization context derived from a verified id_token."""

    user_id: str
    org_code: str | None = None
    dept_codes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    allowed_confidentiality_levels: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "userId": self.user_id,
                "orgCode": self.org_code,
                "deptCodes": self.dept_codes,
                "groups": self.groups,
                "allowedConfidentialityLevels": self.allowed_confidentiality_levels,
            },
            ensure_ascii=False,
        )


_jwk_client: PyJWKClient | None = None
_jwk_client_jwks_url: str | None = None


def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    """Return a cached PyJWKClient, rebuilding it if the JWKS URL changes."""
    global _jwk_client, _jwk_client_jwks_url
    if _jwk_client is None or _jwk_client_jwks_url != jwks_url:
        _jwk_client = PyJWKClient(jwks_url, cache_keys=True)
        _jwk_client_jwks_url = jwks_url
    return _jwk_client


def _split_csv_claim(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def verify_id_token(id_token: str | None) -> AgenticResearchAuthContext:
    """Verify a Cognito id_token and return a trusted auth context.

    Raises AuthenticationError for any missing configuration, missing
    token, or failed verification. Callers must treat this as fail-closed:
    agentic-research mode must not proceed without a successful result here.
    """
    if not id_token:
        raise AuthenticationError(
            "id_token is required for agentic-research mode"
        )

    region = os.environ.get("AGENTIC_RESEARCH_COGNITO_REGION")
    user_pool_id = os.environ.get("AGENTIC_RESEARCH_COGNITO_USER_POOL_ID")
    app_client_id = os.environ.get("AGENTIC_RESEARCH_COGNITO_APP_CLIENT_ID")

    if not region or not user_pool_id or not app_client_id:
        raise AuthenticationError(
            "agentic-research mode is not configured with Cognito verification settings"
        )

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
    jwks_url = f"{issuer}/.well-known/jwks.json"

    try:
        signing_key = _get_jwk_client(jwks_url).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=app_client_id,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise AuthenticationError(f"id_token verification failed: {e}") from e

    if claims.get("token_use") != "id":
        raise AuthenticationError(
            "id_token has an unexpected token_use claim (expected 'id')"
        )

    user_id = claims.get("sub")
    if not user_id:
        raise AuthenticationError("id_token is missing the sub claim")

    return AgenticResearchAuthContext(
        user_id=user_id,
        org_code=claims.get("custom:org_code"),
        dept_codes=_split_csv_claim(claims.get("custom:dept_codes")),
        groups=_split_csv_claim(claims.get("cognito:groups")),
        allowed_confidentiality_levels=_split_csv_claim(
            claims.get("custom:allowed_confidentiality_levels")
        ),
    )
