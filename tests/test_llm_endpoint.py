from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from issue_resolver.agent.issue_resolver_agent import IssueResolverAgent
from issue_resolver.api.main import app
from issue_resolver.config import Settings
from issue_resolver.index.code_index import SimpleCodeIndexService
from issue_resolver.models import ConfidenceLevel, DiagnosisResponse
from issue_resolver.tools.investigation_tools import InvestigationTools
from tests.test_parse_stack_trace import GOLDEN_STACK_TRACE


client = TestClient(app)


def test_health_includes_llm_ready():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert "llmReady" in payload


def test_llm_endpoint_returns_503_when_llm_disabled(monkeypatch):
    disabled_settings = Settings(
        openai_api_key="",
        azure_openai_api_key="",
        azure_openai_endpoint="",
    )
    monkeypatch.setattr("issue_resolver.api.main.settings", disabled_settings)

    response = client.post(
        "/api/v1/incidents/analyze/llm",
        json={
            "service": "ad-management-service",
            "stackTrace": GOLDEN_STACK_TRACE,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "LLM not configured"


def test_llm_endpoint_calls_agent_when_openai_enabled(monkeypatch):
    enabled_settings = Settings(openai_api_key="sk-test", openai_model="gpt-4o")
    code_index = SimpleCodeIndexService(repos_root=enabled_settings.repos_root, repos=[])
    tools = InvestigationTools(code_index, enabled_settings.service_map_path)
    agent = IssueResolverAgent(enabled_settings, tools, code_index)
    agent.analyze_llm = MagicMock(
        return_value=DiagnosisResponse(
            rootCause="Python LLM root cause",
            confidence=ConfidenceLevel.HIGH,
            suggestedFix="Python LLM fix",
            reasoningSteps=["python reasoning"],
        )
    )

    monkeypatch.setattr("issue_resolver.api.main.settings", enabled_settings)
    monkeypatch.setattr("issue_resolver.api.main.agent", agent)

    response = client.post(
        "/api/v1/incidents/analyze/llm",
        headers={"X-ORCHESTRATOR": "java-poc"},
        json={
            "service": "ad-management-service",
            "stackTrace": GOLDEN_STACK_TRACE,
        },
    )

    assert response.status_code == 200
    assert response.json()["rootCause"] == "Python LLM root cause"
    agent.analyze_llm.assert_called_once()
