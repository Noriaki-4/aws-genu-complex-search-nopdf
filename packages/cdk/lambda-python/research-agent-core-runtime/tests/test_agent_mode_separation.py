"""Regression tests for mode-based MCP server / tool separation.

These lock down the exact bug found during Phase 1 review (a server
present in mcp.json but missing from WEB_RESEARCH_MCP_SERVERS silently
disappears from every non-agentic mode) and the Phase 2 requirement that
non-agentic modes can never reach business MCP servers, even via a crafted
`mcp_servers` request.
"""

import json
import os

from src.agent import (
    AGENTIC_RESEARCH_ALLOWED_TOOLS,
    AGENTIC_RESEARCH_MCP_SERVERS,
    WEB_RESEARCH_ALLOWED_TOOLS,
    WEB_RESEARCH_MCP_SERVERS,
    AgentManager,
)

MCP_JSON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "mcp-configs", "mcp.json"
)


def _mcp_json_server_names() -> set[str]:
    with open(MCP_JSON_PATH) as f:
        config = json.load(f)
    return set(config["mcpServers"].keys())


def test_web_research_servers_cover_all_non_business_mcp_json_entries():
    business_servers = set(AGENTIC_RESEARCH_MCP_SERVERS)
    non_business_servers = _mcp_json_server_names() - business_servers
    assert set(WEB_RESEARCH_MCP_SERVERS) == non_business_servers


def test_agentic_research_servers_are_disjoint_from_web_research_servers():
    assert set(AGENTIC_RESEARCH_MCP_SERVERS).isdisjoint(WEB_RESEARCH_MCP_SERVERS)


def test_agentic_research_allowed_tools_exclude_open_web_tools():
    forbidden_substrings = ["brave", "tavily", "WebFetch", "aws-knowledge", "aws-documentation"]
    for tool in AGENTIC_RESEARCH_ALLOWED_TOOLS:
        for forbidden in forbidden_substrings:
            assert forbidden not in tool, f"{tool} should not be allowed in agentic-research"


def test_web_research_allowed_tools_include_web_fetch():
    assert "WebFetch" in WEB_RESEARCH_ALLOWED_TOOLS


class TestGetModeMcpServers:
    def setup_method(self):
        self.manager = AgentManager()

    def test_default_technical_research_uses_web_servers(self):
        result = self.manager.get_mode_mcp_servers("technical-research", None)
        assert result == WEB_RESEARCH_MCP_SERVERS

    def test_agentic_research_always_returns_business_servers(self):
        result = self.manager.get_mode_mcp_servers("agentic-research", None)
        assert result == AGENTIC_RESEARCH_MCP_SERVERS

    def test_agentic_research_ignores_requested_servers(self):
        # A crafted request must not be able to swap in web servers for
        # agentic-research, nor add anything beyond the fixed business set.
        result = self.manager.get_mode_mcp_servers(
            "agentic-research", ["brave-search", "knowledge-base-retriever"]
        )
        assert result == AGENTIC_RESEARCH_MCP_SERVERS

    def test_non_agentic_mode_cannot_reach_business_servers_via_request(self):
        # This is the Phase 2 fix: a crafted mcp_servers list must be
        # intersected with WEB_RESEARCH_MCP_SERVERS, never passed through.
        result = self.manager.get_mode_mcp_servers(
            "technical-research",
            ["brave-search", "knowledge-base-retriever", "s3-document-fetcher"],
        )
        assert result == ["brave-search"]

    def test_non_agentic_mode_with_only_business_servers_requested_returns_empty(self):
        result = self.manager.get_mode_mcp_servers(
            "general-research", ["knowledge-base-retriever", "citation-verifier"]
        )
        assert result == []

    def test_non_agentic_mode_without_request_uses_full_web_set(self):
        result = self.manager.get_mode_mcp_servers("mini-research", None)
        assert result == WEB_RESEARCH_MCP_SERVERS


class TestGetModeAllowedTools:
    def setup_method(self):
        self.manager = AgentManager()

    def test_agentic_research_gets_business_tool_allowlist(self):
        assert (
            self.manager.get_mode_allowed_tools("agentic-research")
            == AGENTIC_RESEARCH_ALLOWED_TOOLS
        )

    def test_other_modes_get_web_tool_allowlist(self):
        for mode in ("technical-research", "mini-research", "general-research"):
            assert self.manager.get_mode_allowed_tools(mode) == WEB_RESEARCH_ALLOWED_TOOLS
