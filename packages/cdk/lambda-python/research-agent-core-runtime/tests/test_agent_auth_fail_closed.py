"""Tests that AgentManager refuses to run agentic-research without a
verified auth_context, even if a caller invoked it directly (defense in
depth behind app.py's own fail-fast check).
"""

import json
import os

import pytest

from src.agent import AGENTIC_RESEARCH_MCP_SERVERS, AgentManager
from src.auth import AgenticResearchAuthContext

MCP_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "mcp-configs", "mcp.json"
)


@pytest.mark.asyncio
async def test_agentic_research_without_auth_context_yields_error_event():
    manager = AgentManager()

    events = []
    async for chunk in manager.process_request_streaming(
        messages=[],
        system_prompt=None,
        mode="agentic-research",
        prompt="hello",
        model_info={"modelId": "test-model", "region": "us-east-1"},
        auth_context=None,
    ):
        events.append(json.loads(chunk))

    assert len(events) == 1
    assert "internalServerException" in events[0]["event"]
    assert "auth_context" in events[0]["event"]["internalServerException"]["message"]


@pytest.mark.asyncio
async def test_agentic_research_injects_auth_context_into_business_servers(
    monkeypatch,
):
    monkeypatch.setenv("MCP_CONFIG_PATH", MCP_CONFIG_PATH)

    manager = AgentManager()
    auth_context = AgenticResearchAuthContext(user_id="user-1", org_code="org-a")

    captured_options = {}

    async def fake_query(prompt, options):
        captured_options["options"] = options
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("claude_agent_sdk.ClaudeAgentOptions", lambda **kwargs: kwargs)

    async for _ in manager.process_request_streaming(
        messages=[],
        system_prompt=None,
        mode="agentic-research",
        prompt="hello",
        model_info={"modelId": "test-model", "region": "us-east-1"},
        session_id="session-xyz",
        auth_context=auth_context,
    ):
        pass

    options = captured_options["options"]
    mcp_servers = options["mcp_servers"]

    # Only the fixed business server set is present for agentic-research.
    assert set(mcp_servers.keys()) == set(AGENTIC_RESEARCH_MCP_SERVERS)

    for server_name in AGENTIC_RESEARCH_MCP_SERVERS:
        env = mcp_servers[server_name]["env"]
        assert json.loads(env["AUTH_CONTEXT_JSON"]) == {
            "userId": "user-1",
            "orgCode": "org-a",
            "deptCodes": [],
            "groups": [],
            "allowedConfidentialityLevels": [],
        }
        assert env["SESSION_ID"] == "session-xyz"
        assert env["AGENTIC_RESEARCH_BUSINESS_TIMEZONE"] == "Asia/Tokyo"
