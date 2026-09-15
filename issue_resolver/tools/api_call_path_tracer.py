from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from issue_resolver.index.code_index import IndexedFile, SimpleCodeIndexService


class CallPathRole(str, Enum):
    ENTRY_CONTROLLER = "ENTRY_CONTROLLER"
    ENTRY_SERVICE = "ENTRY_SERVICE"
    PROXY_CALL = "PROXY_CALL"
    DOWNSTREAM_CONTROLLER = "DOWNSTREAM_CONTROLLER"
    DOWNSTREAM_SERVICE = "DOWNSTREAM_SERVICE"


@dataclass
class CallPathStep:
    repo: str
    class_name: str
    method_name: str
    path: str
    line: int
    role: CallPathRole
    snippet: str = ""


SERVICE_CALL_PATTERN = re.compile(r"([\w]+Service)\.([\w]+)\s*\(")


class ApiCallPathTracer:
    def __init__(self, code_index: SimpleCodeIndexService, service_map: dict[str, Any]) -> None:
        self.code_index = code_index
        self.service_map = service_map

    def trace(self, service: str, api_path: str, downstream_path: str | None = None) -> List[CallPathStep]:
        steps: List[CallPathStep] = []
        if not service or not api_path:
            return steps

        normalized_path = api_path.split("?", 1)[0]
        mapping = self._resolve_api_mapping(service, normalized_path)
        target_service = mapping.get("targetService") if mapping else self._guess_target_service(downstream_path)
        target_path = mapping.get("targetPath") if mapping else self._extract_path_suffix(downstream_path)

        controller = self._find_entry_controller(service, normalized_path)
        if controller:
            steps.append(controller)
            service_step = self._find_entry_service(controller)
            if service_step:
                steps.append(service_step)

        proxy = self._find_proxy_call(service, target_path)
        if proxy:
            steps.append(proxy)

        if target_service and target_path:
            downstream_controller = self._find_downstream_controller(target_service, target_path)
            if downstream_controller:
                steps.append(downstream_controller)
                downstream_service = self._find_downstream_service(downstream_controller)
                if downstream_service:
                    steps.append(downstream_service)

        return steps

    def _resolve_api_mapping(self, service: str, api_path: str) -> Optional[dict[str, Any]]:
        services = self.service_map.get("services", {})
        service_def = services.get(service, {})
        mappings = service_def.get("apiMappings", {})
        if api_path in mappings:
            return mappings[api_path]
        for key, value in mappings.items():
            if api_path.startswith(key) or key.startswith(api_path):
                return value
        return None

    def _find_entry_controller(self, repo: str, api_path: str) -> Optional[CallPathStep]:
        path_segment = self._last_segment(api_path)
        for file in self.code_index.all_files():
            if file.repo != repo or not file.class_name.endswith("Controller"):
                continue
            lines = self._read_lines(file)
            content = "\n".join(lines)
            if api_path not in content and path_segment not in content:
                continue
            mapping_line = self._find_controller_mapping_line(lines, api_path, path_segment)
            method_name = self._extract_method_name_near_line(lines, mapping_line, "get")
            return self._build_step(file, mapping_line, method_name, CallPathRole.ENTRY_CONTROLLER)
        return None

    def _find_entry_service(self, controller_step: CallPathStep) -> Optional[CallPathStep]:
        file = self._find_file(controller_step.repo, controller_step.path)
        if not file:
            return None
        lines = self._read_lines(file)
        match = SERVICE_CALL_PATTERN.search("\n".join(lines))
        if not match:
            return None
        impl_class = self._to_impl_class_name(match.group(1))
        impl_file = self.code_index.find_by_class_name(impl_class)
        if not impl_file:
            return None
        method_line = self._find_method_line(self._read_lines(impl_file), match.group(2))
        return self._build_step(impl_file, method_line, match.group(2), CallPathRole.ENTRY_SERVICE)

    def _find_proxy_call(self, repo: str, target_path: str | None) -> Optional[CallPathStep]:
        if not target_path:
            return None
        suffix = self._last_segment(target_path)
        for file in self.code_index.all_files():
            if file.repo != repo or not file.class_name.endswith("ServiceImpl"):
                continue
            lines = self._read_lines(file)
            for index, line in enumerate(lines):
                if suffix in line and (
                    "getCampaignServiceUrl" in line or "resttemplate" in line.lower()
                ):
                    return self._build_step(file, index + 1, "proxyCall", CallPathRole.PROXY_CALL)
        return None

    def _find_downstream_controller(self, repo: str, target_path: str) -> Optional[CallPathStep]:
        suffix = self._last_segment(target_path)
        for file in self.code_index.all_files():
            if file.repo != repo or not file.class_name.endswith("Controller"):
                continue
            lines = self._read_lines(file)
            for index, line in enumerate(lines):
                if ("@PostMapping" in line or "@GetMapping" in line) and f'"{suffix}"' in line:
                    method_name = self._extract_method_name_near_line(
                        lines, index + 1, "get" if "get" in suffix else ""
                    )
                    return self._build_step(file, index + 1, method_name, CallPathRole.DOWNSTREAM_CONTROLLER)
        return None

    def _find_downstream_service(self, controller_step: CallPathStep) -> Optional[CallPathStep]:
        file = self._find_file(controller_step.repo, controller_step.path)
        if not file:
            return None
        lines = self._read_lines(file)
        match = SERVICE_CALL_PATTERN.search("\n".join(lines))
        if not match:
            return None
        impl_class = self._to_impl_class_name(match.group(1))
        impl_file = self.code_index.find_by_class_name(impl_class)
        if not impl_file:
            return None
        method_line = self._find_method_line(self._read_lines(impl_file), match.group(2))
        return self._build_step(impl_file, method_line, match.group(2), CallPathRole.DOWNSTREAM_SERVICE)

    def _build_step(self, file: IndexedFile, line: int, method_name: str, role: CallPathRole) -> CallPathStep:
        return CallPathStep(
            repo=file.repo,
            class_name=file.class_name,
            method_name=method_name,
            path=file.relative_path,
            line=line,
            role=role,
            snippet=self.code_index.read_snippet(file.repo, file.relative_path, line),
        )

    def _find_file(self, repo: str, relative_path: str) -> Optional[IndexedFile]:
        for file in self.code_index.all_files():
            if file.repo == repo and file.relative_path == relative_path:
                return file
        return None

    def _find_controller_mapping_line(self, lines: List[str], api_path: str, path_segment: str) -> int:
        for index, line in enumerate(lines):
            if "@RequestMapping" in line and (api_path in line or path_segment in line):
                return index + 1
            if line.strip() == "@GetMapping":
                return index + 1
        return 1

    def _extract_method_name_near_line(self, lines: List[str], mapping_line: int, hint: str) -> str:
        for index in range(mapping_line - 1, min(len(lines), mapping_line + 4)):
            line = lines[index].strip()
            if "public " in line and "(" in line:
                match = re.search(r"public\s+[\w<>,\s]+\s+(\w+)\s*\(", line)
                if match:
                    return match.group(1)
        return hint or "handler"

    def _find_method_line(self, lines: List[str], method_name: str) -> int:
        for index, line in enumerate(lines):
            if f"{method_name}(" in line:
                return index + 1
        return 1

    def _to_impl_class_name(self, service_bean: str) -> str:
        if not service_bean:
            return "UnknownServiceImpl"
        class_name = service_bean[0].upper() + service_bean[1:]
        return class_name if class_name.endswith("Impl") else f"{class_name}Impl"

    def _guess_target_service(self, downstream_path: str | None) -> Optional[str]:
        if downstream_path and "campaign-management-service" in downstream_path:
            return "campaign-management-service"
        return None

    def _extract_path_suffix(self, downstream_path: str | None) -> Optional[str]:
        if not downstream_path:
            return None
        api_index = downstream_path.find("/api/")
        return downstream_path[api_index:] if api_index >= 0 else downstream_path

    def _last_segment(self, path: str) -> str:
        trimmed = path[:-1] if path.endswith("/") else path
        slash = trimmed.rfind("/")
        return trimmed[slash:] if slash >= 0 else trimmed

    def _read_lines(self, file: IndexedFile) -> List[str]:
        try:
            from pathlib import Path

            return Path(file.absolute_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
