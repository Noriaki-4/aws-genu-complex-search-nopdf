"""Bedrock Knowledge Base retriever MCP server for agentic-research mode.

Enforces org_code / status / effective-date / confidentiality constraints
inside the server itself, so the calling agent cannot bypass them regardless
of what it requests in tool input. Authorization comes only from
AUTH_CONTEXT_JSON, which the Runtime injects out-of-band after verifying the
caller's Cognito id_token.
"""

import logging
import os

import boto3
from mcp.server.fastmcp import FastMCP

from src.mcp_servers.common import (
    AuthContextMissingError,
    append_retrieved_results,
    is_active_and_effective,
    is_authorized,
    load_auth_context,
    today_iso,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("knowledge-base-retriever")

_client = None


def _bedrock_agent_runtime_client():
    global _client
    if _client is None:
        region = os.environ.get("MODEL_REGION") or os.environ.get("AWS_REGION", "us-east-1")
        _client = boto3.client("bedrock-agent-runtime", region_name=region)
    return _client


def _normalize_metadata(raw_metadata: dict) -> dict:
    return {
        "orgCode": raw_metadata.get("org_code"),
        "status": raw_metadata.get("status"),
        "effectiveFrom": raw_metadata.get("effective_from"),
        "effectiveTo": raw_metadata.get("effective_to"),
        "confidentiality": raw_metadata.get("confidentiality"),
    }


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 10) -> dict:
    """Search the governed Bedrock Knowledge Base for business documents.

    Only returns documents that are active, currently effective, and
    authorized for the calling user's organization and confidentiality
    level. Authorization is derived from the Runtime-verified caller
    identity, never from this tool's input.
    """
    try:
        auth = load_auth_context()
    except AuthContextMissingError as e:
        logger.warning(f"Refusing search_knowledge_base: {e}")
        return {"results": [], "error": str(e)}

    knowledge_base_id = os.environ.get("KNOWLEDGE_BASE_ID")
    if not knowledge_base_id:
        return {"results": [], "error": "KNOWLEDGE_BASE_ID is not configured"}

    as_of_date = today_iso()
    bounded_top_k = max(1, min(top_k, 50))

    retrieval_filter: dict = {"andAll": [{"equals": {"key": "status", "value": "active"}}]}
    if auth.org_code:
        retrieval_filter["andAll"].append(
            {"equals": {"key": "org_code", "value": auth.org_code}}
        )

    try:
        response = _bedrock_agent_runtime_client().retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": bounded_top_k,
                    "filter": retrieval_filter,
                }
            },
        )
    except Exception as e:
        logger.error(f"Bedrock KB retrieve failed: {e}")
        return {"results": [], "error": "knowledge base search failed"}

    results = []
    for item in response.get("retrievalResults", []):
        raw_metadata = item.get("metadata", {})
        metadata = _normalize_metadata(raw_metadata)

        # Double-check here even though the KB filter above already applies
        # status/org_code: the filter is best-effort, this check is mandatory.
        if not is_active_and_effective(metadata, as_of_date):
            continue
        if not is_authorized(auth, metadata):
            continue

        location = item.get("location", {}).get("s3Location", {})
        source_uri = location.get("uri", "")

        results.append(
            {
                "sourceType": "bedrock-knowledge-base",
                "documentId": source_uri,
                "chunkId": raw_metadata.get("x-amz-bedrock-kb-chunk-id", ""),
                "content": item.get("content", {}).get("text", ""),
                "score": item.get("score"),
                "metadata": metadata,
                "citation": {"sourceS3Uri": source_uri},
            }
        )

    append_retrieved_results(results)

    return {"results": results}


if __name__ == "__main__":
    mcp.run(transport="stdio")
