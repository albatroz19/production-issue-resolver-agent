import json
import logging
from typing import Dict, List

from openai import AzureOpenAI, OpenAI

from issue_resolver.config import Settings
from issue_resolver.models import (
    ChangelogAnalyzeRequest,
    ChangelogAnalyzeResponse,
    ChangelogCommitInput,
    ChangelogItem,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You analyze git commits and diffs for a daily engineering changelog.
Rules:
- Describe what changed in plain language for stakeholders.
- For each distinct feature or fix, output module (repo or area path), feature name, changeType (created|changed|fixed|removed|other), and description.
- Base conclusions only on provided commit subjects, diff stats, and patches. Do not invent files or behavior.
- Group related commits when they clearly belong to one feature.
- Return ONLY valid JSON:
{
  "summaryMarkdown": "markdown overview for the day",
  "items": [
    {
      "module": "string",
      "feature": "string",
      "changeType": "created|changed|fixed|removed|other",
      "description": "string",
      "repo": "string",
      "tickets": ["TPSG-123"]
    }
  ]
}
"""


class ChangelogAnalyzer:
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

    def analyze(self, request: ChangelogAnalyzeRequest) -> ChangelogAnalyzeResponse:
        if not self._client:
            raise RuntimeError("LLM not configured")
        if not request.commits:
            return ChangelogAnalyzeResponse(
                summaryMarkdown=f"No commits for {request.date}.",
                items=[],
            )

        cache_key = _cache_key(request)
        if cache_key in _CACHE:
            return _CACHE[cache_key]

        payload = {
            "date": request.date,
            "commits": [c.model_dump() for c in request.commits],
        }
        user_content = json.dumps(payload, indent=2)

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
        items = [
            ChangelogItem(
                module=item.get("module", ""),
                feature=item.get("feature", ""),
                changeType=item.get("changeType", item.get("change_type", "other")),
                description=item.get("description", ""),
                repo=item.get("repo", ""),
                tickets=item.get("tickets", []) or [],
            )
            for item in parsed.get("items", [])
        ]
        summary = parsed.get("summaryMarkdown") or parsed.get("summary_markdown") or ""
        if not summary and not items:
            summary = _fallback_markdown(request.date, request.commits)

        result = ChangelogAnalyzeResponse(summaryMarkdown=summary, items=items)
        _CACHE[cache_key] = result
        return result


def _fallback_markdown(date: str, commits: List[ChangelogCommitInput]) -> str:
    lines = [f"# Daily changelog — {date}", "", "Commits (subjects only; LLM parse empty):", ""]
    for c in commits:
        tickets = ", ".join(c.tickets) if c.tickets else "—"
        lines.append(f"- **{c.repo}**: {c.subject} ({tickets})")
    return "\n".join(lines)


def _cache_key(request: ChangelogAnalyzeRequest) -> str:
    parts = [request.date]
    for c in request.commits:
        parts.append(f"{c.repo}|{c.sha}|{c.subject}")
    return "||".join(parts)


_CACHE: Dict[str, ChangelogAnalyzeResponse] = {}
