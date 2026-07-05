"""Tests for shared business MCP server helpers (src.mcp_servers.common).

Covers the fail-closed contract (no AUTH_CONTEXT_JSON -> refuse) and the
status/effective-date/org/confidentiality double-check that every business
MCP server applies regardless of what a KB or S3 metadata filter already did.
"""

import json

import pytest

from src.mcp_servers.common import (
    AuthContext,
    AuthContextMissingError,
    append_retrieved_results,
    get_session_store_dir,
    is_active_and_effective,
    is_authorized,
    load_auth_context,
    load_retrieved_results,
    today_iso,
)


class TestLoadAuthContext:
    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("AUTH_CONTEXT_JSON", raising=False)
        with pytest.raises(AuthContextMissingError):
            load_auth_context()

    def test_malformed_json_raises(self, monkeypatch):
        monkeypatch.setenv("AUTH_CONTEXT_JSON", "not-json")
        with pytest.raises(AuthContextMissingError):
            load_auth_context()

    def test_missing_user_id_raises(self, monkeypatch):
        monkeypatch.setenv("AUTH_CONTEXT_JSON", json.dumps({"orgCode": "org-a"}))
        with pytest.raises(AuthContextMissingError):
            load_auth_context()

    def test_valid_context_is_parsed(self, monkeypatch):
        monkeypatch.setenv(
            "AUTH_CONTEXT_JSON",
            json.dumps(
                {
                    "userId": "user-1",
                    "orgCode": "org-a",
                    "deptCodes": ["dept-a"],
                    "groups": ["group-a"],
                    "allowedConfidentialityLevels": ["internal"],
                }
            ),
        )
        auth = load_auth_context()
        assert auth.user_id == "user-1"
        assert auth.org_code == "org-a"
        assert auth.dept_codes == ["dept-a"]
        assert auth.groups == ["group-a"]
        assert auth.allowed_confidentiality_levels == ["internal"]


class TestIsActiveAndEffective:
    def test_inactive_status_is_rejected(self):
        metadata = {"status": "inactive"}
        assert is_active_and_effective(metadata, "2026-07-06") is False

    def test_future_effective_from_is_rejected(self):
        metadata = {"status": "active", "effectiveFrom": "2027-01-01"}
        assert is_active_and_effective(metadata, "2026-07-06") is False

    def test_past_effective_to_is_rejected(self):
        metadata = {"status": "active", "effectiveTo": "2026-01-01"}
        assert is_active_and_effective(metadata, "2026-07-06") is False

    def test_effective_to_equal_to_as_of_date_is_rejected(self):
        # effective_to is exclusive: as_of_date == effective_to means expired.
        metadata = {"status": "active", "effectiveTo": "2026-07-06"}
        assert is_active_and_effective(metadata, "2026-07-06") is False

    def test_currently_valid_document_is_accepted(self):
        metadata = {
            "status": "active",
            "effectiveFrom": "2026-01-01",
            "effectiveTo": "2027-01-01",
        }
        assert is_active_and_effective(metadata, "2026-07-06") is True

    def test_no_effective_dates_defaults_to_accepted(self):
        metadata = {"status": "active"}
        assert is_active_and_effective(metadata, "2026-07-06") is True

    def test_today_iso_uses_configured_business_timezone(self, monkeypatch):
        monkeypatch.setenv("AGENTIC_RESEARCH_BUSINESS_TIMEZONE", "Asia/Tokyo")
        assert len(today_iso()) == len("2026-07-06")


class TestIsAuthorized:
    def test_org_mismatch_is_denied(self):
        auth = AuthContext(user_id="u1", org_code="org-a")
        metadata = {"orgCode": "org-b"}
        assert is_authorized(auth, metadata) is False

    def test_org_match_is_allowed(self):
        auth = AuthContext(user_id="u1", org_code="org-a")
        metadata = {"orgCode": "org-a"}
        assert is_authorized(auth, metadata) is True

    def test_no_org_requirement_is_allowed(self):
        auth = AuthContext(user_id="u1", org_code=None)
        metadata = {}
        assert is_authorized(auth, metadata) is True

    def test_confidentiality_not_in_allowed_levels_is_denied(self):
        auth = AuthContext(user_id="u1", allowed_confidentiality_levels=["internal"])
        metadata = {"confidentiality": "restricted"}
        assert is_authorized(auth, metadata) is False

    def test_confidentiality_in_allowed_levels_is_allowed(self):
        auth = AuthContext(user_id="u1", allowed_confidentiality_levels=["restricted"])
        metadata = {"confidentiality": "restricted"}
        assert is_authorized(auth, metadata) is True


class TestSessionScopedStore:
    def test_results_round_trip_within_a_session(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SESSION_ID", "session-abc")
        monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(tmp_path))

        append_retrieved_results(
            [{"chunkId": "doc-1-chunk-1", "content": "first"}]
        )
        append_retrieved_results(
            [{"chunkId": "doc-1-chunk-2", "content": "second"}]
        )

        results = load_retrieved_results()
        assert [r["chunkId"] for r in results] == [
            "doc-1-chunk-1",
            "doc-1-chunk-2",
        ]

    def test_sessions_are_isolated(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(tmp_path))

        monkeypatch.setenv("SESSION_ID", "session-a")
        append_retrieved_results([{"chunkId": "a-chunk"}])

        monkeypatch.setenv("SESSION_ID", "session-b")
        assert load_retrieved_results() == []

    def test_empty_store_returns_empty_list(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SESSION_ID", "session-empty")
        monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(tmp_path))
        assert load_retrieved_results() == []

    def test_store_dir_is_created(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SESSION_ID", "session-new")
        store_root = tmp_path / "nested" / "does-not-exist-yet"
        monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(store_root))
        store_dir = get_session_store_dir()
        assert store_dir.exists()
