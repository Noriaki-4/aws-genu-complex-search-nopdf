"""Tests for the citation-verifier MCP server.

The key property under test: verification is driven entirely by what the
retriever/fetcher saved to the session store, never by anything the caller
passes directly as "contexts" -- verify_citations only accepts claims with
citationIds, not raw context text.
"""

import pytest

from src.mcp_servers.citation_verifier import verify_citations


@pytest.fixture(autouse=True)
def session_store(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_ID", "test-session")
    monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(tmp_path))


def _seed_results(monkeypatch, results):
    from src.mcp_servers.common import append_retrieved_results

    append_retrieved_results(results)


class TestVerifyCitations:
    def test_claim_with_no_citation_ids_is_flagged(self, monkeypatch):
        result = verify_citations([{"text": "some claim", "citationIds": []}])
        assert result["verified"] is False
        assert result["issues"][0]["reason"] == "no_citation_provided"

    def test_citation_not_in_session_store_is_flagged(self, monkeypatch):
        result = verify_citations(
            [{"text": "some claim", "citationIds": ["unknown-chunk"]}]
        )
        assert result["verified"] is False
        assert result["issues"][0]["reason"] == "citation_not_found"

    def test_matching_and_currently_effective_citation_is_verified(self, monkeypatch):
        _seed_results(
            monkeypatch,
            [
                {
                    "chunkId": "doc-1-chunk-1",
                    "content": "A手続きでは災害時に承認不要となる例外がある",
                    "metadata": {"status": "active"},
                }
            ],
        )
        result = verify_citations(
            [
                {
                    "text": "A手続きでは災害時に承認不要となる",
                    "citationIds": ["doc-1-chunk-1"],
                }
            ]
        )
        assert result["verified"] is True
        assert result["issues"] == []

    def test_expired_citation_is_flagged_even_if_text_matches(self, monkeypatch):
        _seed_results(
            monkeypatch,
            [
                {
                    "chunkId": "doc-1-chunk-1",
                    "content": "A手続きでは災害時に承認不要となる例外がある",
                    "metadata": {"status": "active", "effectiveTo": "2020-01-01"},
                }
            ],
        )
        result = verify_citations(
            [
                {
                    "text": "A手続きでは災害時に承認不要となる",
                    "citationIds": ["doc-1-chunk-1"],
                }
            ]
        )
        assert result["verified"] is False
        assert result["issues"][0]["reason"] == "citation_not_currently_effective"

    def test_claim_text_absent_from_context_is_flagged(self, monkeypatch):
        _seed_results(
            monkeypatch,
            [
                {
                    "chunkId": "doc-1-chunk-1",
                    "content": "unrelated content that does not match",
                    "metadata": {"status": "active"},
                }
            ],
        )
        result = verify_citations(
            [
                {
                    "text": "a claim that was never actually retrieved anywhere",
                    "citationIds": ["doc-1-chunk-1"],
                }
            ]
        )
        assert result["verified"] is False
        assert result["issues"][0]["reason"] == "claim_text_not_found_in_context"

    def test_caller_supplied_contexts_are_ignored(self, monkeypatch):
        # verify_citations has no "contexts" parameter at all: a caller
        # cannot inject arbitrary content to make a fabricated claim verify.
        import inspect

        params = inspect.signature(verify_citations).parameters
        assert "contexts" not in params

    def test_session_store_survives_workspace_cleanup_between_requests(
        self, monkeypatch, tmp_path
    ):
        from src.mcp_servers.common import append_retrieved_results
        from src.utils import clean_ws_directory

        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        (workspace_dir / "scratch.txt").write_text("temporary", encoding="utf-8")
        monkeypatch.setattr("src.utils.WORKSPACE_DIR", str(workspace_dir))

        store_dir = tmp_path / "agentic-research-session"
        monkeypatch.setenv("RESEARCH_SESSION_STORE_DIR", str(store_dir))
        append_retrieved_results(
            [
                {
                    "chunkId": "doc-1-chunk-1",
                    "content": "A手続きでは災害時に承認不要となる例外がある",
                    "metadata": {"status": "active"},
                }
            ]
        )

        clean_ws_directory()
        result = verify_citations(
            [
                {
                    "text": "A手続きでは災害時に承認不要となる",
                    "citationIds": ["doc-1-chunk-1"],
                }
            ]
        )

        assert not workspace_dir.exists()
        assert result == {"verified": True, "issues": []}
