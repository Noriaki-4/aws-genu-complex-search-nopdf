"""Shared helpers for business (agentic-research) MCP servers.

These servers never accept authorization fields (user id, org, groups,
confidentiality) from LLM-controlled tool input. The Runtime verifies the
caller's Cognito id_token once and injects the resulting context into each
business MCP server's process environment out-of-band; this module reads
that injected context back.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


class AuthContextMissingError(Exception):
    """Raised when a business MCP server is invoked without a verified auth context."""


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    org_code: str | None = None
    dept_codes: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    allowed_confidentiality_levels: list[str] = field(default_factory=list)


def load_auth_context() -> AuthContext:
    """Load the Runtime-injected auth context from the AUTH_CONTEXT_JSON env var.

    Raises AuthContextMissingError if unset or malformed, so callers can
    fail closed rather than search without a verified identity.
    """
    raw = os.environ.get("AUTH_CONTEXT_JSON")
    if not raw:
        raise AuthContextMissingError(
            "AUTH_CONTEXT_JSON is not set; refusing to search"
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AuthContextMissingError(f"AUTH_CONTEXT_JSON is not valid JSON: {e}") from e

    user_id = data.get("userId")
    if not user_id:
        raise AuthContextMissingError("AUTH_CONTEXT_JSON is missing userId")

    return AuthContext(
        user_id=user_id,
        org_code=data.get("orgCode"),
        dept_codes=list(data.get("deptCodes") or []),
        groups=list(data.get("groups") or []),
        allowed_confidentiality_levels=list(
            data.get("allowedConfidentialityLevels") or []
        ),
    )


def today_iso() -> str:
    """Return the current UTC date as an ISO 8601 date string (YYYY-MM-DD).

    Phase 2 always uses the Runtime's current date for effective-date
    checks; user-requested as-of dates are not honored (see Phase 2 plan).
    """
    return datetime.now(timezone.utc).date().isoformat()


def is_active_and_effective(metadata: dict, as_of_date: str) -> bool:
    """Enforce status=active and effective_from/effective_to against as_of_date.

    Dates are expected as ISO 8601 (YYYY-MM-DD) strings, which sort
    lexicographically in chronological order.
    """
    if metadata.get("status") != "active":
        return False

    effective_from = metadata.get("effectiveFrom")
    if effective_from and effective_from > as_of_date:
        return False

    effective_to = metadata.get("effectiveTo")
    if effective_to and as_of_date >= effective_to:
        return False

    return True


def is_authorized(auth: AuthContext, metadata: dict) -> bool:
    """Enforce org_code and confidentiality constraints for a single result."""
    required_org = metadata.get("orgCode")
    if required_org and required_org != auth.org_code:
        return False

    confidentiality = metadata.get("confidentiality")
    if confidentiality and confidentiality not in auth.allowed_confidentiality_levels:
        return False

    return True


def get_session_store_dir() -> Path:
    """Return (creating if needed) this session's scoped store directory."""
    session_id = os.environ.get("SESSION_ID", "no-session")
    base_dir = os.environ.get(
        "RESEARCH_SESSION_STORE_DIR", "/tmp/ws/agentic-research-session"
    )
    store_dir = Path(base_dir) / session_id
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


def append_retrieved_results(results: list[dict]) -> None:
    """Persist retriever/fetcher results for later citation verification.

    Citation Verify reads from this store instead of trusting LLM-supplied
    context, so a hallucinated or fabricated citation can never pass.
    """
    if not results:
        return
    store_path = get_session_store_dir() / "retrieved_results.jsonl"
    with store_path.open("a", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")


def load_retrieved_results() -> list[dict]:
    """Load all retriever/fetcher results saved so far in this session."""
    store_path = get_session_store_dir() / "retrieved_results.jsonl"
    if not store_path.exists():
        return []

    results = []
    with store_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results
