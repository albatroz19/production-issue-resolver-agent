from unittest.mock import patch

from fastapi.testclient import TestClient

from issue_resolver.api.main import app
from issue_resolver.models import (
    TaskCommitInput,
    TaskSummarizeRequest,
    TaskSummarizeResponse,
    TaskSummaryEntry,
)

client = TestClient(app)


def test_summarize_endpoint_requires_llm(monkeypatch):
    monkeypatch.setattr("issue_resolver.api.main.settings.openai_api_key", "")
    monkeypatch.setattr("issue_resolver.api.main.settings.azure_openai_api_key", "")
    monkeypatch.setattr("issue_resolver.api.main.settings.azure_openai_endpoint", "")
    response = client.post(
        "/api/v1/tasks/summarize",
        json={
            "user": "Mohit Bisht",
            "date": "2026-09-01",
            "commits": [
                {"repo": "ad-management-service", "subject": "Asset history changes", "tickets": ["TPSG-6548"]}
            ],
        },
    )
    assert response.status_code == 503


@patch("issue_resolver.api.main.task_summarizer.summarize")
def test_summarize_endpoint_success(mock_summarize):
    mock_summarize.return_value = TaskSummarizeResponse(
        entries=[
            TaskSummaryEntry(
                repo="ad-management-service",
                description="Updated asset history handling.",
                tickets=["TPSG-6548"],
            )
        ]
    )
    response = client.post(
        "/api/v1/tasks/summarize",
        json=TaskSummarizeRequest(
            user="Mohit Bisht",
            date="2026-09-01",
            commits=[
                TaskCommitInput(
                    repo="ad-management-service",
                    subject="Asset history changes",
                    tickets=["TPSG-6548"],
                )
            ],
        ).model_dump(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["entries"][0]["description"] == "Updated asset history handling."
