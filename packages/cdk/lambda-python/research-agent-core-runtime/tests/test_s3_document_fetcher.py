"""Tests for the S3 document fetcher's allow-list resolution.

This is the boundary that stops a hallucinated or crafted S3 URI from
reaching any bucket/prefix outside the governed document set.
"""

import pytest

from src.mcp_servers.s3_document_fetcher import _resolve_allowed_key

ALLOWED_BUCKET = "genu-agentic-research-docs"


@pytest.fixture(autouse=True)
def bucket_env(monkeypatch):
    monkeypatch.setenv("AGENTIC_RESEARCH_DOCUMENT_BUCKET_NAME", ALLOWED_BUCKET)
    monkeypatch.setenv("AGENTIC_RESEARCH_DOCUMENT_PREFIX", "docs/")


class TestResolveAllowedKey:
    def test_valid_uri_within_prefix_is_resolved(self):
        result = _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs/policy.md")
        assert result == (ALLOWED_BUCKET, "docs/policy.md")

    def test_wrong_bucket_is_rejected(self):
        assert _resolve_allowed_key("s3://some-other-bucket/docs/policy.md") is None

    def test_outside_prefix_is_rejected(self):
        assert _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/other/policy.md") is None

    def test_dot_dot_traversal_is_rejected(self, monkeypatch):
        monkeypatch.setenv("AGENTIC_RESEARCH_DOCUMENT_PREFIX", "")
        assert (
            _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs/../../etc/passwd")
            is None
        )

    def test_traversal_escaping_configured_prefix_is_rejected(self):
        # docs/../secret/file.md normalizes to secret/file.md, which is
        # outside the configured docs/ prefix.
        assert (
            _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs/../secret/file.md")
            is None
        )

    def test_non_s3_scheme_is_rejected(self):
        assert _resolve_allowed_key(f"https://{ALLOWED_BUCKET}/docs/policy.md") is None

    def test_missing_bucket_config_rejects_everything(self, monkeypatch):
        monkeypatch.delenv("AGENTIC_RESEARCH_DOCUMENT_BUCKET_NAME", raising=False)
        assert _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs/policy.md") is None
