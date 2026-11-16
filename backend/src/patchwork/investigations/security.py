import os
import re


def redact(text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        text = text.replace(key, "[REDACTED]")
    text = re.sub(r"(?i)(?:sk-[\w-]{12,}|gh[pousr]_[\w]{12,}|AKIA[A-Z0-9]{16})", "[REDACTED]", text)
    return re.sub(
        r"(?im)((?:api[_-]?key|password|secret|token)\s*[=:]\s*)[^\n,;]+",
        r"\1[REDACTED]",
        text,
    )
