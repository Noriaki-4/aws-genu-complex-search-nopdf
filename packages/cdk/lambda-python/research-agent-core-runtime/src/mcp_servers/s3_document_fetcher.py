"""S3 document fetch MCP server for agentic-research mode.

Only allows reads from a single allow-listed bucket/prefix, and re-checks
status/org/effective-date metadata after fetch, so a hallucinated or
crafted URI can never escape the governed document set.
"""

import logging
import os

import boto3
from mcp.server.fastmcp import FastMCP

from src.mcp_servers.common import (
    AuthContextMissingError,
    is_active_and_effective,
    is_authorized,
    load_auth_context,
    today_iso,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("s3-document-fetcher")

_client = None


def _s3_client():
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def _resolve_allowed_key(source_s3_uri: str) -> tuple[str, str] | None:
    """Validate a s3:// URI against the allow-listed bucket/prefix.

    Returns (bucket, key) if allowed, otherwise None. The key is normalized
    so that `..` segments or an absolute path cannot escape the configured
    prefix.
    """
    allowed_bucket = os.environ.get("AGENTIC_RESEARCH_DOCUMENT_BUCKET_NAME")
    allowed_prefix = os.environ.get("AGENTIC_RESEARCH_DOCUMENT_PREFIX", "")
    if not allowed_bucket:
        return None

    if not source_s3_uri.startswith("s3://"):
        return None

    without_scheme = source_s3_uri[len("s3://") :]
    parts = without_scheme.split("/", 1)
    if len(parts) != 2:
        return None
    bucket, raw_key = parts

    if bucket != allowed_bucket:
        return None

    normalized_key = os.path.normpath(raw_key)
    if normalized_key in (".", "") or normalized_key.startswith("..") or normalized_key.startswith("/"):
        return None
    if allowed_prefix and not normalized_key.startswith(allowed_prefix):
        return None

    return allowed_bucket, normalized_key


@mcp.tool()
def fetch_document(source_s3_uri: str) -> dict:
    """Fetch a governed business document by its S3 URI.

    Only URIs inside the configured allow-listed bucket/prefix are served.
    The fetched document's metadata is re-checked for org/status/effective
    date before content is returned to the caller.
    """
    try:
        auth = load_auth_context()
    except AuthContextMissingError as e:
        logger.warning(f"Refusing fetch_document: {e}")
        return {"error": str(e)}

    resolved = _resolve_allowed_key(source_s3_uri)
    if resolved is None:
        return {"error": "source_s3_uri is not in an allowed bucket/prefix"}
    bucket, key = resolved

    try:
        response = _s3_client().get_object(Bucket=bucket, Key=key)
    except Exception as e:
        logger.error(f"Failed to fetch s3://{bucket}/{key}: {e}")
        return {"error": "document not found or inaccessible"}

    raw_metadata = response.get("Metadata", {})
    metadata = {
        "orgCode": raw_metadata.get("org_code"),
        "status": raw_metadata.get("status"),
        "effectiveFrom": raw_metadata.get("effective_from"),
        "effectiveTo": raw_metadata.get("effective_to"),
        "confidentiality": raw_metadata.get("confidentiality"),
    }

    if not is_active_and_effective(metadata, today_iso()):
        return {"error": "document is not active or not currently effective"}
    if not is_authorized(auth, metadata):
        return {"error": "document is not authorized for this user"}

    content = response["Body"].read().decode("utf-8", errors="replace")

    return {
        "documentId": f"s3://{bucket}/{key}",
        "content": content,
        "metadata": {
            "orgCode": metadata["orgCode"],
            "status": metadata["status"],
        },
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
