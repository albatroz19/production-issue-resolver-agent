import json
import logging
from typing import Dict, List

from openai import AzureOpenAI, OpenAI

from issue_resolver.config import Settings
from issue_resolver.models import (
    TaskCommitInput,
    TaskSummarizeRequest,
    TaskSummarizeResponse,
    TaskSummaryEntry,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You convert git commit messages into professional daily timesheet entries.
Rules:
- Write clear, meaningful work descriptions suitable for a timesheet.
- Consolidate related commits into fewer entries when appropriate.
- Never include commit hashes or SHAs.
- Preserve repo names and Jira ticket IDs when provided.
- Return ONLY valid JSON matching this schema:
{
  "entries": [
    {
      "repo": "string",
      "description": "string",
      "tickets": ["TPSG-1234"]
    }
  ]
}
"""


class TaskSummarizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: AzureOpenAI | OpenAI | None = None
        if settings.llm_provider == "openai":
            self._client = OpenAI(api_key=settings.openai_api_key)
        elif settings.llm_provider == "azure":
            self._client = AzureOpenAI(
                api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )

    def summarize(self, request: TaskSummarizeRequest) -> TaskSummarizeResponse:
        if not self._client:
            raise RuntimeError("LLM not configured")
        if not request.commits:
            return TaskSummarizeResponse(entries=[])

        cache_key = _cache_key(request)
        if cache_key in _CACHE:
            return _CACHE[cache_key]

        user_content = json.dumps(
            {
                "user": request.user,
                "date": request.date,
                "commits": [c.model_dump() for c in request.commits],
            },
            indent=2,
        )

        response = self._client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        entries = [
            TaskSummaryEntry(
                repo=item.get("repo", ""),
                description=item.get("description", ""),
                tickets=item.get("tickets", []),
            )
            for item in parsed.get("entries", [])
        ]
        if not entries:
            entries = _fallback_entries(request.commits)

        result = TaskSummarizeResponse(entries=entries)
        _CACHE[cache_key] = result
        return result


def _fallback_entries(commits: List[TaskCommitInput]) -> List[TaskSummaryEntry]:
    return [
        TaskSummaryEntry(repo=c.repo, description=c.subject, tickets=c.tickets)
        for c in commits
    ]


def _cache_key(request: TaskSummarizeRequest) -> str:
    parts = [request.user, request.date]
    for commit in request.commits:
        parts.append(f"{commit.repo}|{commit.subject}|{','.join(commit.tickets)}")
    return "||".join(parts)


_CACHE: Dict[str, TaskSummarizeResponse] = {}
