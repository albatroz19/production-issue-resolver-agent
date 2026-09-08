from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional


PACKAGE_PATTERN = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_PATTERN = re.compile(r"(?:public\s+)?(?:class|interface|enum|record)\s+(\w+)")


@dataclass
class IndexedFile:
    repo: str
    absolute_path: str
    relative_path: str
    class_name: str
    package_name: str


@dataclass
class CodeSearchResult:
    repo: str
    path: str
    class_name: str
    match_line: int
    snippet: str


class SimpleCodeIndexService:
    def __init__(
        self,
        repos_root: str,
        repos: List[tuple[str, str]],
        max_snippet_lines: int = 150,
        max_files_per_request: int = 3,
    ) -> None:
        self.repos_root = Path(repos_root)
        self.repos = repos
        self.max_snippet_lines = max_snippet_lines
        self.max_files_per_request = max_files_per_request
        self._class_name_index: dict[str, IndexedFile] = {}
        self._all_files: List[IndexedFile] = []
        self._build_index()

    def indexed_file_count(self) -> int:
        return len(self._all_files)

    def find_by_class_name(self, class_name: str) -> Optional[IndexedFile]:
        if not class_name:
            return None
        simple_name = class_name.split(".")[-1]
        return self._class_name_index.get(simple_name)

    def search_codebase(self, query: str, repo_filter: str | None = None) -> List[CodeSearchResult]:
        if not query:
            return []

        normalized = query.lower()
        results: List[CodeSearchResult] = []

        for file in self._all_files:
            if repo_filter and file.repo.lower() != repo_filter.lower():
                continue
            try:
                lines = Path(file.absolute_path).read_text(encoding="utf-8").splitlines()
            except OSError:
                continue

            for index, line in enumerate(lines):
                if normalized in line.lower():
                    results.append(
                        CodeSearchResult(
                            repo=file.repo,
                            path=file.relative_path,
                            class_name=file.class_name,
                            match_line=index + 1,
                            snippet=self._extract_snippet(lines, index + 1),
                        )
                    )
                    break

        return results[: self.max_files_per_request * 3]

    def find_exception_handlers(self, service_name: str | None = None) -> List[CodeSearchResult]:
        patterns = ("@restcontrolleradvice", "@controlleradvice", "extends responseentityexceptionhandler")
        results: List[CodeSearchResult] = []

        for file in self._all_files:
            if service_name and file.repo.lower() != service_name.lower():
                continue
            try:
                content = Path(file.absolute_path).read_text(encoding="utf-8").lower()
                if not any(pattern in content for pattern in patterns):
                    continue
                lines = Path(file.absolute_path).read_text(encoding="utf-8").splitlines()
                match_line = self._first_matching_line(lines, patterns)
                results.append(
                    CodeSearchResult(
                        repo=file.repo,
                        path=file.relative_path,
                        class_name=file.class_name,
                        match_line=match_line,
                        snippet=self._extract_snippet(lines, match_line),
                    )
                )
            except OSError:
                continue

        return results[: self.max_files_per_request]

    def read_snippet(self, repo: str, relative_path: str, center_line: int) -> str:
        for file in self._all_files:
            if file.repo == repo and file.relative_path == relative_path:
                try:
                    lines = Path(file.absolute_path).read_text(encoding="utf-8").splitlines()
                    return self._extract_snippet(lines, center_line)
                except OSError:
                    return ""
        return ""

    def _build_index(self) -> None:
        for repo_name, repo_path in self.repos:
            repo_root = self.repos_root / repo_path
            java_root = repo_root / "src" / "main" / "java"
            if not java_root.is_dir():
                continue
            for file_path in java_root.rglob("*.java"):
                self._index_file(repo_name, java_root, file_path)

    def _index_file(self, repo_name: str, java_root: Path, file_path: Path) -> None:
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return

        package_match = PACKAGE_PATTERN.search(content)
        class_match = CLASS_PATTERN.search(content)
        package_name = package_match.group(1) if package_match else ""
        class_name = class_match.group(1) if class_match else file_path.stem

        indexed = IndexedFile(
            repo=repo_name,
            absolute_path=str(file_path),
            relative_path=str(file_path.relative_to(java_root)),
            class_name=class_name,
            package_name=package_name,
        )
        self._all_files.append(indexed)
        self._class_name_index.setdefault(class_name, indexed)

    def _first_matching_line(self, lines: List[str], patterns: tuple[str, ...]) -> int:
        for index, line in enumerate(lines):
            lower = line.lower()
            if any(pattern in lower for pattern in patterns):
                return index + 1
        return 1

    def _extract_snippet(self, lines: List[str], center_line: int) -> str:
        if not lines:
            return ""
        half = self.max_snippet_lines // 2
        start = max(1, center_line - half)
        end = min(len(lines), start + self.max_snippet_lines - 1)
        start = max(1, end - self.max_snippet_lines + 1)

        chunks = []
        for line_number in range(start, end + 1):
            chunks.append(f"{line_number:4d}| {lines[line_number - 1]}")
        return "\n".join(chunks)
