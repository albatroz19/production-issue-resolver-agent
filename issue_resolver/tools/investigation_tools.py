from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from issue_resolver.index.code_index import CodeSearchResult, SimpleCodeIndexService
from issue_resolver.index.ranked_code_search import RankedCodeSearchService
from issue_resolver.tools.api_call_path_tracer import ApiCallPathTracer
from issue_resolver.tools.parse_stack_trace import format_parsed_stack_trace, parse_stack_trace


class InvestigationTools:
    def __init__(self, code_index: SimpleCodeIndexService, service_map_path: Path) -> None:
        self.code_index = code_index
        self.service_map = self._load_service_map(service_map_path)
        self.ranked_search = RankedCodeSearchService(code_index)
        self.call_path_tracer = ApiCallPathTracer(code_index, self.service_map)

    def parse_stack_trace(self, stack_trace: str) -> str:
        return format_parsed_stack_trace(parse_stack_trace(stack_trace))

    def search_codebase(self, query: str, repo_filter: str = "", search_mode: str = "ranked") -> str:
        results = self._search(query, repo_filter or None, search_mode)
        if not results:
            return f"No matches found for query: {query}"
        return "\n---\n".join(self._format_search_result(result) for result in results)

    def get_service_dependencies(self, service_name: str, api_path: str = "") -> str:
        services = self.service_map.get("services", {})
        service = services.get(service_name)
        if not service:
            return f"No service mapping found for: {service_name}"

        lines = [
            f"Service: {service_name}",
            f"Description: {service.get('description', '')}",
            f"Dependencies: {service.get('dependencies', [])}",
        ]

        if api_path:
            mapping = self._find_api_mapping(service.get("apiMappings", {}), api_path)
            if mapping:
                lines.extend(
                    [
                        f"API mapping for {api_path}:",
                        f"  targetService: {mapping.get('targetService')}",
                        f"  targetPath: {mapping.get('targetPath')}",
                        f"  description: {mapping.get('description', '')}",
                    ]
                )
            else:
                lines.append(f"No explicit API mapping found for path: {api_path}")

        return "\n".join(lines).strip()

    def find_exception_handlers(self, service_name: str) -> str:
        results = self.code_index.find_exception_handlers(service_name)
        if not results:
            return f"No exception handlers found for service: {service_name}"
        return "\n---\n".join(self._format_search_result(result) for result in results)

    def trace_api_call_path(self, service: str, api_path: str, environment: str = "dev") -> str:
        steps = self.call_path_tracer.trace(service, api_path)
        if not steps:
            return f"No call path found for service={service} apiPath={api_path} environment={environment}"
        return "\n---\n".join(self._format_call_path_step(step) for step in steps)

    def read_code_snippet(self, repo: str, path: str, line: int, environment: str = "dev") -> str:
        snippet = self.code_index.read_snippet(repo, path, line)
        if not snippet:
            return f"No snippet found for repo={repo} path={path} line={line} environment={environment}"
        return f"repo={repo} path={path} line={line} environment={environment}\n{snippet}"

    def execute(self, name: str, arguments: Dict[str, Any]) -> str:
        if name == "parse_stack_trace":
            return self.parse_stack_trace(arguments.get("stack_trace", ""))
        if name == "search_codebase":
            return self.search_codebase(
                arguments.get("query", ""),
                arguments.get("repo_filter", ""),
                arguments.get("search_mode", "ranked"),
            )
        if name == "get_service_dependencies":
            return self.get_service_dependencies(
                arguments.get("service_name", ""),
                arguments.get("api_path", ""),
            )
        if name == "find_exception_handlers":
            return self.find_exception_handlers(arguments.get("service_name", ""))
        if name == "trace_api_call_path":
            return self.trace_api_call_path(
                arguments.get("service", ""),
                arguments.get("api_path", ""),
                arguments.get("environment", "dev"),
            )
        if name == "read_code_snippet":
            return self.read_code_snippet(
                arguments.get("repo", ""),
                arguments.get("path", ""),
                int(arguments.get("line", 1)),
                arguments.get("environment", "dev"),
            )
        return f"Unknown tool: {name}"

    @staticmethod
    def openai_tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "parse_stack_trace",
                    "description": "Parse a Java stack trace to extract exception type, top frame, and Caused by chain.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "stack_trace": {"type": "string", "description": "Raw Java stack trace"},
                        },
                        "required": ["stack_trace"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_codebase",
                    "description": "Search indexed Java source files for a symbol, method name, or text fragment.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "repo_filter": {
                                "type": "string",
                                "description": "Optional repo name such as ad-management-service",
                            },
                            "search_mode": {
                                "type": "string",
                                "description": "ranked (default) or literal",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_service_dependencies",
                    "description": "Return downstream service dependencies and API path mappings.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service_name": {"type": "string"},
                            "api_path": {"type": "string"},
                        },
                        "required": ["service_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "find_exception_handlers",
                    "description": "Find @RestControllerAdvice or @ControllerAdvice classes in a service repository.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service_name": {"type": "string"},
                        },
                        "required": ["service_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "trace_api_call_path",
                    "description": "Trace API call path from entry controller through proxy to downstream handler.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string"},
                            "api_path": {"type": "string"},
                            "environment": {"type": "string"},
                        },
                        "required": ["service", "api_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_code_snippet",
                    "description": "Read a code snippet centered on a specific line from an indexed repository file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string"},
                            "path": {"type": "string"},
                            "line": {"type": "integer"},
                            "environment": {"type": "string"},
                        },
                        "required": ["repo", "path", "line"],
                    },
                },
            },
        ]

    def _search(self, query: str, repo_filter: str | None, search_mode: str) -> list[CodeSearchResult]:
        if search_mode.lower() == "literal":
            return self.code_index.search_codebase(query, repo_filter)
        results = self.ranked_search.search(query, repo_filter)
        if results:
            return results
        return self.code_index.search_codebase(query, repo_filter)

    def _format_search_result(self, result: CodeSearchResult) -> str:
        return (
            f"repo={result.repo} path={result.path} class={result.class_name} line={result.match_line}\n"
            f"{result.snippet}"
        )

    def _format_call_path_step(self, step) -> str:
        return (
            f"role={step.role.value} repo={step.repo} class={step.class_name} method={step.method_name} "
            f"line={step.line} path={step.path}\n{step.snippet}"
        )

    def _load_service_map(self, service_map_path: Path) -> dict[str, Any]:
        if not service_map_path.exists():
            return {"services": {}}
        with service_map_path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {"services": {}}

    def _find_api_mapping(self, mappings: dict[str, Any], api_path: str) -> Optional[dict[str, Any]]:
        if api_path in mappings:
            return mappings[api_path]
        for key, value in mappings.items():
            if api_path.startswith(key) or key.startswith(api_path):
                return value
        return None
