from fastapi.testclient import TestClient

from issue_resolver.api.main import app
from issue_resolver.config import settings

client = TestClient(app)


def test_changelog_analyze_returns_503_when_llm_disabled(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "azure_openai_api_key", "")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "")
    response = client.post(
        "/api/v1/changelog/analyze",
        json={"date": "2026-09-15", "commits": []},
    )
    assert response.status_code == 503
