"""Citation verification MCP server for agentic-research mode (Phase 2 minimal).

Never trusts LLM-supplied context: claims are checked against the
session-scoped store that the retriever/fetcher MCP servers populate, not
against any "contexts" the caller passes directly.
"""

import logging

from mcp.server.fastmcp import FastMCP

from src.mcp_servers.common import is_active_and_effective, load_retrieved_results, today_iso

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("citation-verifier")


def _index_known_results(results: list[dict]) -> dict:
    known = {}
    for result in results:
        for id_field in ("chunkId", "documentId"):
            value = result.get(id_field)
            if value:
                known[value] = result
    return known


@mcp.tool()
def verify_citations(claims: list[dict]) -> dict:
    """Verify that claims cite content actually present in retrieved results.

    Each item in `claims` is {"text": str, "citationIds": [str]}. Citation
    ids are matched against chunkId/documentId values saved by the
    retriever/fetcher MCP servers earlier in this session.
    """
    known_results = _index_known_results(load_retrieved_results())
    as_of_date = today_iso()
    issues = []

    for claim in claims:
        text = claim.get("text", "")
        citation_ids = claim.get("citationIds", [])

        if not citation_ids:
            issues.append({"claim": text, "reason": "no_citation_provided"})
            continue

        matched_result = next(
            (known_results[cid] for cid in citation_ids if cid in known_results),
            None,
        )

        if matched_result is None:
            issues.append({"claim": text, "reason": "citation_not_found"})
            continue

        if not is_active_and_effective(matched_result.get("metadata", {}), as_of_date):
            issues.append(
                {"claim": text, "reason": "citation_not_currently_effective"}
            )
            continue

        content = matched_result.get("content", "")
        # Minimal Phase 2 check: a short excerpt of the claim should appear
        # in the retrieved content. This is a heuristic, not full NLI-based
        # verification.
        excerpt = text[:20]
        if excerpt and excerpt not in content:
            issues.append(
                {"claim": text, "reason": "claim_text_not_found_in_context"}
            )

    return {"verified": len(issues) == 0, "issues": issues}


if __name__ == "__main__":
    mcp.run(transport="stdio")
