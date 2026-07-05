"""Tests for governed Bedrock Knowledge Base retrieval."""

import json

from src.mcp_servers import knowledge_base_retriever


def _auth_context(org_code=None):
    data = {
        "userId": "user-1",
        "allowedConfidentialityLevels": ["public"],
    }
    if org_code:
        data["orgCode"] = org_code
    return json.dumps(data)


class FakeBedrockAgentRuntimeClient:
    def __init__(self):
        self.retrieve_calls = []

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return {"retrievalResults": []}


class TestSearchKnowledgeBaseFilter:
    def test_orgless_user_uses_single_status_filter_not_and_all(self, monkeypatch):
        client = FakeBedrockAgentRuntimeClient()
        monkeypatch.setenv("AUTH_CONTEXT_JSON", _auth_context())
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "kb-123")
        monkeypatch.setattr(
            knowledge_base_retriever,
            "_bedrock_agent_runtime_client",
            lambda: client,
        )

        result = knowledge_base_retriever.search_knowledge_base("policy", top_k=5)

        assert result == {"results": []}
        vector_config = client.retrieve_calls[0]["retrievalConfiguration"][
            "vectorSearchConfiguration"
        ]
        assert vector_config["filter"] == {
            "equals": {"key": "status", "value": "active"}
        }

    def test_org_user_uses_and_all_with_two_conditions(self, monkeypatch):
        client = FakeBedrockAgentRuntimeClient()
        monkeypatch.setenv("AUTH_CONTEXT_JSON", _auth_context("org-a"))
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "kb-123")
        monkeypatch.setattr(
            knowledge_base_retriever,
            "_bedrock_agent_runtime_client",
            lambda: client,
        )

        knowledge_base_retriever.search_knowledge_base("policy", top_k=5)

        vector_config = client.retrieve_calls[0]["retrievalConfiguration"][
            "vectorSearchConfiguration"
        ]
        assert vector_config["filter"] == {
            "andAll": [
                {"equals": {"key": "status", "value": "active"}},
                {"equals": {"key": "org_code", "value": "org-a"}},
            ]
        }
