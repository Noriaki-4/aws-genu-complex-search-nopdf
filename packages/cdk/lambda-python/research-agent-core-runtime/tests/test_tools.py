"""Tests for ToolManager, focused on the business context injection channel
that carries verified auth data to MCP servers out-of-band from tool input.
"""

from src.tools import ToolManager


class TestInjectBusinessContext:
    def test_env_vars_are_injected_into_named_servers(self):
        manager = ToolManager()
        servers = {
            "knowledge-base-retriever": {"command": "uv", "args": []},
            "brave-search": {"command": "npx", "args": []},
        }

        manager.inject_business_context(
            servers,
            ["knowledge-base-retriever"],
            {"AUTH_CONTEXT_JSON": '{"userId":"u1"}'},
        )

        assert servers["knowledge-base-retriever"]["env"] == {
            "AUTH_CONTEXT_JSON": '{"userId":"u1"}'
        }
        # Non-business servers must be untouched.
        assert "env" not in servers["brave-search"]

    def test_server_not_present_is_skipped_without_error(self):
        manager = ToolManager()
        servers = {"brave-search": {"command": "npx", "args": []}}

        manager.inject_business_context(
            servers, ["knowledge-base-retriever"], {"AUTH_CONTEXT_JSON": "{}"}
        )

        assert servers == {"brave-search": {"command": "npx", "args": []}}

    def test_existing_env_is_preserved_and_merged(self):
        manager = ToolManager()
        servers = {
            "knowledge-base-retriever": {
                "command": "uv",
                "args": [],
                "env": {"KNOWLEDGE_BASE_ID": "kb-1"},
            }
        }

        manager.inject_business_context(
            servers,
            ["knowledge-base-retriever"],
            {"AUTH_CONTEXT_JSON": "{}", "SESSION_ID": "s1"},
        )

        assert servers["knowledge-base-retriever"]["env"] == {
            "KNOWLEDGE_BASE_ID": "kb-1",
            "AUTH_CONTEXT_JSON": "{}",
            "SESSION_ID": "s1",
        }
