from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

from issue_resolver.agent.issue_resolver_agent import IssueResolverAgent
from issue_resolver.config import settings
from issue_resolver.index.code_index import SimpleCodeIndexService
from issue_resolver.models import DiagnosisResponse, IncidentRequest
from issue_resolver.tools.investigation_tools import InvestigationTools

app = FastAPI(title="Production Issue Resolver Agent", version="0.1.0")

code_index = SimpleCodeIndexService(
    repos_root=settings.repos_root,
    repos=[(repo.name, repo.path) for repo in settings.repos],
    max_snippet_lines=settings.max_snippet_lines,
    max_files_per_request=settings.max_files_per_request,
)
tools = InvestigationTools(code_index, settings.service_map_path)
agent = IssueResolverAgent(settings, tools, code_index)


@app.get("/health")
def health() -> dict[str, str | int | bool]:
    return {
        "status": "ok",
        "indexedFiles": code_index.indexed_file_count(),
        "llmEnabled": settings.llm_enabled,
        "llmReady": settings.llm_enabled,
        "llmProvider": settings.llm_provider or "none",
    }


def _validate_api_key(x_poc_api_key: str | None) -> None:
    if settings.poc_api_key and x_poc_api_key != settings.poc_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-POC-API-KEY",
        )


@app.post("/api/v1/incidents/analyze", response_model=DiagnosisResponse)
def analyze_incident(
    request: IncidentRequest,
    x_poc_api_key: str | None = Header(default=None, alias="X-POC-API-KEY"),
) -> DiagnosisResponse:
    _validate_api_key(x_poc_api_key)
    return agent.analyze(request)


@app.post("/api/v1/incidents/analyze/llm", response_model=DiagnosisResponse)
def analyze_incident_llm(
    request: IncidentRequest,
    x_poc_api_key: str | None = Header(default=None, alias="X-POC-API-KEY"),
    x_orchestrator: str | None = Header(default=None, alias="X-ORCHESTRATOR"),
) -> DiagnosisResponse:
    _validate_api_key(x_poc_api_key)
    if not settings.llm_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM not configured",
        )
    try:
        return agent.analyze_llm(request, orchestrator=x_orchestrator)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM diagnosis failed: {exc}",
        ) from exc


@app.exception_handler(ValueError)
def value_error_handler(_: Exception, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
