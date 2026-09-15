from __future__ import annotations

import math
import re
from typing import List, Optional, Set

from issue_resolver.index.code_index import CodeSearchResult, IndexedFile, SimpleCodeIndexService

JAVA_KEYWORDS: Set[str] = {
    "public",
    "private",
    "protected",
    "class",
    "interface",
    "return",
    "void",
    "new",
    "import",
    "package",
    "static",
    "final",
    "throws",
    "throw",
    "if",
    "else",
    "for",
    "while",
    "try",
    "catch",
    "this",
    "null",
}

CAMEL_CASE_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


class RankedCodeSearchService:
    def __init__(self, code_index: SimpleCodeIndexService) -> None:
        self.code_index = code_index

    def search(self, query: str, repo_filter: str | None = None) -> List[CodeSearchResult]:
        if not query:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, CodeSearchResult]] = []
        total_files = len(self.code_index.all_files())

        for file in self.code_index.all_files():
            if repo_filter and file.repo.lower() != repo_filter.lower():
                continue
            try:
                from pathlib import Path

                lines = Path(file.absolute_path).read_text(encoding="utf-8").splitlines()
            except OSError:
                continue

            score = self._score_file(file, lines, query_tokens, total_files)
            if score <= 0:
                continue
            match_line = self._find_best_line(lines, query_tokens)
            scored.append(
                (
                    score,
                    CodeSearchResult(
                        repo=file.repo,
                        path=file.relative_path,
                        class_name=file.class_name,
                        match_line=match_line,
                        snippet=self.code_index.read_snippet(file.repo, file.relative_path, match_line),
                    ),
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        return [result for _, result in scored[: self.code_index.max_files_per_request * 3]]

    def _score_file(
        self, file: IndexedFile, lines: List[str], query_tokens: List[str], total_files: int
    ) -> float:
        content = "\n".join(lines).lower()
        file_tokens = set(self._tokenize(content))
        score = 0.0

        for token in query_tokens:
            if file.class_name.lower() == token:
                score += 10
            if token in file.class_name.lower():
                score += 4
            if token in content:
                score += 1 + math.log1p(content.count(token))
            if token in file_tokens:
                score += 2
            if "/" in token and token in content:
                score += 3

        if score > 0:
            score += 2.0 / max(1, math.log1p(total_files))
        return score

    def _find_best_line(self, lines: List[str], query_tokens: List[str]) -> int:
        best_line = 1
        best_score = 0
        for index, line in enumerate(lines):
            lower = line.lower()
            line_score = sum(1 for token in query_tokens if token in lower)
            if line_score > best_score:
                best_score = line_score
                best_line = index + 1
        return best_line

    def _tokenize(self, value: str) -> List[str]:
        tokens: list[str] = []
        normalized = re.sub(r"[^a-z0-9/_\-]+", " ", value.lower())
        for part in normalized.split():
            if not part or part in JAVA_KEYWORDS:
                continue
            tokens.append(part)
            for camel_part in CAMEL_CASE_SPLIT.split(part):
                lowered = camel_part.lower()
                if lowered and lowered not in JAVA_KEYWORDS:
                    tokens.append(lowered)
        return list(dict.fromkeys(tokens))
