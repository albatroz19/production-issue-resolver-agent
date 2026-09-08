# Production Issue Resolver Agent (Python)

Internal LLM engine for the Java orchestrator. Runs Azure OpenAI tool-calling to diagnose production incidents. **In orchestrated mode, clients call Java (8099), not this service directly.**

## Role in orchestration

| Endpoint | Audience | Behavior |
|----------|----------|----------|
| `POST /api/v1/incidents/analyze/llm` | Java POC (internal) | LLM-only; returns 503 if Azure not configured; fail-fast on LLM errors |
| `POST /api/v1/incidents/analyze` | Standalone testing | Full analyze with rule-based fallback |
| `GET /health` | Ops | Includes `llmReady` for readiness checks |

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- Azure OpenAI (`openai` SDK) with function calling
- In-memory Java source index over CMS/AMS repos

## Setup

```bash
cd /Users/amitasharda/Desktop/Segmentation/production-issue-resolver-agent

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with Azure credentials for LLM mode
```

## Run (orchestrated — start this first)

**With OpenAI key (no Azure needed):**

```bash
cd /Users/amitasharda/Desktop/Segmentation/production-issue-resolver-agent
source .venv/bin/activate
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o"
python run.py   # :8098
```

**With Azure OpenAI:**

```bash
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
python run.py
```

Or create `.env` from `.env.example` and restart Python.

Then start Java POC with `PYTHON_AGENT_BASE_URL=http://localhost:8098`.

## Run (standalone testing)

## API

### Health (includes llmReady)

```bash
curl http://localhost:8098/health
```

### Internal LLM endpoint (called by Java)

```bash
curl -s -X POST http://localhost:8098/api/v1/incidents/analyze/llm \
  -H "Content-Type: application/json" \
  -H "X-ORCHESTRATOR: java-poc" \
  -d '{"service":"ad-management-service","stackTrace":"..."}'
```

### Analyze incident (standalone)

```bash
curl -s -X POST http://localhost:8098/api/v1/incidents/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "service": "ad-management-service",
    "environment": "dev",
    "apiPath": "/api/v1/campaign-ch-100/multi-channel/filler-slots",
    "httpStatus": 500,
    "errorMessage": "NullPointerException",
    "relatedServices": ["campaign-management-service"],
    "stackTrace": "java.lang.NullPointerException\n\tat com.tataplay.admanagement.utility.RestTemplateUtility.extractErrorMessage(RestTemplateUtility.java:48)",
    "recentLogs": "CMS returned HTTP 400 with body {\"code\":\"VALIDATION_ERROR\"}"
  }' | python -m json.tool
```

## Agent architecture

```
FastAPI -> IssueResolverAgent -> Azure OpenAI tool loop (max 8 steps)
                              -> InvestigationTools
                                   - parse_stack_trace
                                   - search_codebase
                                   - get_service_dependencies
                                   - find_exception_handlers
                              -> rule-based fallback (no LLM)
```

The agent loop lives in `issue_resolver/agent/issue_resolver_agent.py`. Customize the system prompt, add tools in `issue_resolver/tools/investigation_tools.py`, and extend diagnosis rules in `issue_resolver/agent/rule_based.py`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | For OpenAI | API key from [platform.openai.com](https://platform.openai.com) (preferred if you have one) |
| `OPENAI_MODEL` | No | Model name (default: `gpt-4o`) |
| `AZURE_OPENAI_API_KEY` | For Azure | Azure OpenAI API key (alternative to OpenAI) |
| `AZURE_OPENAI_ENDPOINT` | For LLM | e.g. `https://<resource>.openai.azure.com` |
| `AZURE_OPENAI_DEPLOYMENT` | No | Deployment name (default: `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | No | API version (default: `2024-08-01-preview`) |
| `REPOS_ROOT` | No | Parent folder for CMS/AMS repos |
| `POC_API_KEY` | No | If set, require `X-POC-API-KEY` header |

## Tests

```bash
pytest -q
```

## Security

- Read-only: indexes local Java files only
- Log redaction for tokens/JWTs before LLM prompts
- Optional `POC_API_KEY` / `X-POC-API-KEY` auth
- No secrets committed — use `.env` locally

## Project layout

```
issue_resolver/
  api/main.py                 # FastAPI endpoints
  agent/
    issue_resolver_agent.py   # LLM tool-calling loop
    rule_based.py             # Fallback diagnosis rules
  tools/
    investigation_tools.py    # Tool definitions + execution
    parse_stack_trace.py
  index/code_index.py         # CMS/AMS source index
  models.py
config/service-map.yml
tests/
```

## Next steps for your own agent

1. **Custom tools** — add methods to `InvestigationTools` and register them in `openai_tool_definitions()`.
2. **Custom prompts** — edit `SYSTEM_PROMPT` in `issue_resolver_agent.py`.
3. **More incident patterns** — extend `rule_based.py` for deterministic cases.
4. **Phase 2** — webhook ingest, vector search for similar incidents, Slack notifications.
# production-issue-resolver-agent
