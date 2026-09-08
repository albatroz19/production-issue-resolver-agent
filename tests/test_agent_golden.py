from issue_resolver.agent.issue_resolver_agent import IssueResolverAgent
from issue_resolver.config import Settings
from issue_resolver.index.code_index import SimpleCodeIndexService
from issue_resolver.models import ConfidenceLevel, IncidentRequest
from issue_resolver.tools.investigation_tools import InvestigationTools
from tests.test_parse_stack_trace import GOLDEN_STACK_TRACE


def test_analyze_golden_rest_template_utility_npe_case_uses_rule_based_fallback(tmp_path):
    settings = Settings(
        repos_root=str(tmp_path),
        azure_openai_api_key="",
        azure_openai_endpoint="",
    )
    code_index = SimpleCodeIndexService(
        repos_root=settings.repos_root,
        repos=[(repo.name, repo.path) for repo in settings.repos],
    )
    tools = InvestigationTools(code_index, settings.service_map_path)
    agent = IssueResolverAgent(settings, tools, code_index)

    request = IncidentRequest(
        service="ad-management-service",
        environment="dev",
        apiPath="/api/v1/campaign-ch-100/multi-channel/filler-slots",
        httpStatus=500,
        errorMessage="NullPointerException",
        relatedServices=["campaign-management-service"],
        stackTrace=GOLDEN_STACK_TRACE,
        recentLogs='CMS responded with HTTP 400 and body {"code":"VALIDATION_ERROR"}',
    )

    response = agent.analyze(request)

    assert response.confidence == ConfidenceLevel.HIGH
    assert "message" in response.root_cause.lower()
    assert "resttemplateutility" in response.suggested_fix.lower()
    assert any("resttemplateutility" in step.lower() for step in response.reasoning_steps)
