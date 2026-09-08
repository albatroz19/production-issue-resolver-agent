import json
import logging
from typing import Any

from openai import AzureOpenAI, OpenAI

from issue_resolver.agent.rule_based import build_rule_based_diagnosis
from issue_resolver.config import Settings
from issue_resolver.index.code_index import SimpleCodeIndexService
from issue_resolver.log_redactor import redact_logs
from issue_resolver.models import DiagnosisResponse, IncidentRequest
from issue_resolver.tools.investigation_tools import InvestigationTools
from issue_resolver.tools.parse_stack_trace import parse_stack_trace

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a production issue diagnosis agent for Java Spring Boot microservices.
Use the provided tools to gather evidence from stack traces and the local codebase index.
Rules:
- Prefer evidence from tool results over guessing.
- Identify cross-service failures when a service proxies another (e.g. AMS -> CMS).
- Separate symptom (e.g. NullPointerException) from root cause (e.g. missing JSON field).
- Never suggest destructive production actions (restart, data delete, force push).
- Return ONLY valid JSON matching this schema:
{
  "rootCause": "string",
  "confidence": "HIGH|MEDIUM|LOW",
  "affectedFiles": [{"repo":"string","path":"string","lines":"string"}],
  "suggestedFix": "string",
  "reasoningSteps": ["string"],
  "relatedIncidents": ["string"]
}
"""


class IssueResolverAgent:
    def __init__(self, settings: Settings, tools: InvestigationTools, code_index: SimpleCodeIndexService) -> None:
        self.settings = settings
        self.tools = tools
        self.code_index = code_index
        self._client: AzureOpenAI | OpenAI | None = None
        if settings.llm_provider == "openai":
            self._client = OpenAI(api_key=settings.openai_api_key)
        elif settings.llm_provider == "azure":
            self._client = AzureOpenAI(
                api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )

    def analyze_llm(self, request: IncidentRequest, orchestrator: str | None = None) -> DiagnosisResponse:
        if not self._client:
            raise RuntimeError("LLM not configured")

        reasoning_steps: list[str] = []
        if orchestrator:
            reasoning_steps.append(f"Orchestrated by: {orchestrator}")

        parsed = parse_stack_trace(request.stack_trace)
        reasoning_steps.append(
            "Parsed exception: "
            + (parsed.exception_type or "unknown")
            + (f" - {parsed.exception_message}" if parsed.exception_message else "")
        )
        if parsed.top_frame:
            frame = parsed.top_frame
            location = f"{frame.class_name}.{frame.method_name}({frame.file_name}"
            if frame.line_number is not None:
                location += f":{frame.line_number}"
            location += ")"
            reasoning_steps.append(f"Top frame: {location}")

        service_deps = self.tools.get_service_dependencies(request.service, request.api_path or "")
        reasoning_steps.append("Service dependencies: " + service_deps.splitlines()[0])

        response = self._run_llm_loop(request, reasoning_steps)
        response.reasoning_steps = reasoning_steps + response.reasoning_steps
        return response

    def analyze(self, request: IncidentRequest) -> DiagnosisResponse:
        reasoning_steps: list[str] = []
        parsed = parse_stack_trace(request.stack_trace)

        reasoning_steps.append(
            "Parsed exception: "
            + (parsed.exception_type or "unknown")
            + (f" - {parsed.exception_message}" if parsed.exception_message else "")
        )
        if parsed.top_frame:
            frame = parsed.top_frame
            location = f"{frame.class_name}.{frame.method_name}({frame.file_name}"
            if frame.line_number is not None:
                location += f":{frame.line_number}"
            location += ")"
            reasoning_steps.append(f"Top frame: {location}")

        service_deps = self.tools.get_service_dependencies(request.service, request.api_path or "")
        reasoning_steps.append("Service dependencies: " + service_deps.splitlines()[0])

        if self._client:
            try:
                response = self._run_llm_loop(request, reasoning_steps)
                response.reasoning_steps = reasoning_steps + response.reasoning_steps
                return response
            except Exception as exc:
                logger.warning("LLM diagnosis failed, using rule-based fallback: %s", exc)
                reasoning_steps.append("LLM unavailable or failed; used rule-based fallback.")
        else:
            reasoning_steps.append("Azure OpenAI not configured; used rule-based fallback.")

        return build_rule_based_diagnosis(
            request,
            parsed,
            self.code_index,
            reasoning_steps,
            self.settings.max_files_per_request,
        )

    def _run_llm_loop(self, request: IncidentRequest, reasoning_steps: list[str]) -> DiagnosisResponse:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(request, reasoning_steps)},
        ]
        tools = InvestigationTools.openai_tool_definitions()

        for _ in range(self.settings.agent_max_steps):
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
            message = response.choices[0].message
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            if message.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in message.tool_calls
                ]
            messages.append(assistant_message)

            if not message.tool_calls:
                return self._parse_diagnosis_response(message.content or "{}")

            for tool_call in message.tool_calls:
                arguments = json.loads(tool_call.function.arguments or "{}")
                if tool_call.function.name == "parse_stack_trace" and not arguments.get("stack_trace"):
                    arguments["stack_trace"] = request.stack_trace
                if tool_call.function.name == "get_service_dependencies":
                    arguments.setdefault("service_name", request.service)
                    arguments.setdefault("api_path", request.api_path or "")

                result = self.tools.execute(tool_call.function.name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

        final = self._client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages + [{"role": "user", "content": "Return the final diagnosis JSON only."}],
            temperature=0.2,
        )
        return self._parse_diagnosis_response(final.choices[0].message.content or "{}")

    def _build_user_prompt(self, request: IncidentRequest, reasoning_steps: list[str]) -> str:
        lines = [
            "Incident details:",
            f"service: {request.service}",
            f"environment: {request.environment}",
            f"apiPath: {request.api_path}",
            f"httpStatus: {request.http_status}",
            f"errorMessage: {request.error_message}",
            f"relatedServices: {request.related_services}",
            "stackTrace:",
            request.stack_trace,
        ]
        if request.recent_logs:
            lines.extend(["recentLogs:", redact_logs(request.recent_logs) or ""])
        lines.append("preliminaryReasoning:")
        lines.extend(f"- {step}" for step in reasoning_steps)
        lines.append("")
        lines.append("Use tools to investigate, then return JSON only.")
        return "\n".join(lines)

    def _parse_diagnosis_response(self, content: str) -> DiagnosisResponse:
        json_text = self._extract_json(content)
        payload = json.loads(json_text)
        return DiagnosisResponse.model_validate(payload)

    @staticmethod
    def _extract_json(content: str) -> str:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return content[start : end + 1]
        return content
