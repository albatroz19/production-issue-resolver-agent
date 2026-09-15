from pathlib import Path

from issue_resolver.index.code_index import SimpleCodeIndexService
from issue_resolver.tools.api_call_path_tracer import ApiCallPathTracer, CallPathRole
from issue_resolver.tools.investigation_tools import InvestigationTools


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "production-issue-resolver-poc" / "src" / "test" / "resources" / "fixtures"


def _build_index() -> SimpleCodeIndexService:
    return SimpleCodeIndexService(
        repos_root=str(FIXTURE_ROOT),
        repos=[
            ("ad-management-service", "ad-management-service"),
            ("campaign-management-service", "campaign-management-service"),
        ],
        max_snippet_lines=20,
        max_files_per_request=3,
    )


def test_trace_api_call_path_finds_cms_controller():
    if not FIXTURE_ROOT.exists():
        return

    tools = InvestigationTools(
        _build_index(),
        Path(__file__).resolve().parents[1] / "config" / "service-map.yml",
    )
    response = tools.trace_api_call_path(
        "ad-management-service",
        "/api/v1/campaign-ch-100",
        "dev",
    )

    assert "ChHundredCampaignController" in response
    assert "getCampaign" in response


def test_api_call_path_tracer_returns_downstream_controller_role():
    if not FIXTURE_ROOT.exists():
        return

    tracer = ApiCallPathTracer(
        _build_index(),
        {
            "services": {
                "ad-management-service": {
                    "apiMappings": {
                        "/api/v1/campaign-ch-100": {
                            "targetService": "campaign-management-service",
                            "targetPath": "/api/v1/campaign-management/ch-100/get",
                        }
                    }
                }
            }
        },
    )
    steps = tracer.trace(
        "ad-management-service",
        "/api/v1/campaign-ch-100",
        "/campaign-management-service/api/v1/campaign-management/ch-100/get",
    )

    assert steps
    downstream = [step for step in steps if step.role == CallPathRole.DOWNSTREAM_CONTROLLER]
    assert downstream
    assert downstream[0].line > 1
