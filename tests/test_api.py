from fastapi.testclient import TestClient

from issue_resolver.api.main import app
from tests.test_parse_stack_trace import GOLDEN_STACK_TRACE


client = TestClient(app)


def test_analyze_endpoint_returns_diagnosis():
    response = client.post(
        "/api/v1/incidents/analyze",
        json={
            "service": "ad-management-service",
            "apiPath": "/api/v1/campaign-ch-100/multi-channel/filler-slots",
            "httpStatus": 500,
            "errorMessage": "NullPointerException",
            "relatedServices": ["campaign-management-service"],
            "stackTrace": GOLDEN_STACK_TRACE,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "rootCause" in payload
    assert "confidence" in payload
