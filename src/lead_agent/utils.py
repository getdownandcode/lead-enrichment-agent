"""Small deterministic utilities used across the agent."""

from __future__ import annotations

import re
from urllib.parse import urlparse

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.IGNORECASE
)


def normalize_domain(value: str) -> str:
    candidate = value.strip().lower()
    if not candidate:
        raise ValueError("Empty domain")
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").removeprefix("www.")
    if not host or "." not in host or " " in host:
        raise ValueError(f"Invalid domain: {value!r}")
    return host


def same_domain(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def emails_in(text: str) -> list[str]:
    return sorted({match.lower() for match in EMAIL_PATTERN.findall(text)})


def email_category(address: str) -> str:
    local = address.partition("@")[0].lower()
    for category in ("sales", "support", "contact", "hello", "press", "privacy", "security"):
        if category in local:
            return category
    return "other"
