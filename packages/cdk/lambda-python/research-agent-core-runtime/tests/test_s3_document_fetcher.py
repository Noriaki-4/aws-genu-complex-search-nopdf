"""Tests for the S3 document fetcher's allow-list resolution.

This is the boundary that stops a hallucinated or crafted S3 URI from
reaching any bucket/prefix outside the governed document set.
"""

import io
import json

import pytest

from src.mcp_servers.citation_verifier import verify_citations
from src.mcp_servers.s3_document_fetcher import _resolve_allowed_key, fetch_document

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

    def test_prefix_without_trailing_slash_does_not_match_sibling_prefix(self, monkeypatch):
        monkeypatch.setenv("AGENTIC_RESEARCH_DOCUMENT_PREFIX", "docs")
        assert _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs/policy.md") == (
            ALLOWED_BUCKET,
            "docs/policy.md",
        )
        assert _resolve_allowed_key(f"s3://{ALLOWED_BUCKET}/docs-secret/policy.md") is None


class FakeS3Client:
    def get_object(self, Bucket, Key):
        assert Bucket == ALLOWED_BUCKET
        assert Key == "docs/policy.md"
        return {
            "Metadata": {
                "org_code": "org-a",
                "status": "active",
                "confidentiality": "public",
            },
            "Body": io.BytesIO("A手続きでは災害時に承認不要となる例外がある".encode()),
        }


def test_fetch_document_persists_content_for_citation_verification(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AUTH_CONTEXT_JSON",
        json.dumps(
            {
                "userId": "user-1",
                "orgCode": "org-a",
                "allowedConfidentialityLevels": ["public"],
            }
        ),
    )
    monkeypatch.setenv("SESSION_ID", "session-1")
    monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.mcp_servers.s3_document_fetcher._s3_client", lambda: FakeS3Client()
    )

    document_id = f"s3://{ALLOWED_BUCKET}/docs/policy.md"
    fetch_result = fetch_document(document_id)
    verify_result = verify_citations(
        [
            {
                "text": "A手続きでは災害時に承認不要となる",
                "citationIds": [document_id],
            }
        ]
    )

    assert fetch_result["documentId"] == document_id
    assert verify_result == {"verified": True, "issues": []}
