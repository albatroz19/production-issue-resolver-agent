import re


TOKEN_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|token|cookie|bearer)\s*[:=]\s*[^\s,;]+"
)
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def redact_logs(logs: str | None) -> str | None:
    if not logs:
        return logs
    redacted = TOKEN_PATTERN.sub(r"\1=[REDACTED]", logs)
    return JWT_PATTERN.sub("[REDACTED_JWT]", redacted)
