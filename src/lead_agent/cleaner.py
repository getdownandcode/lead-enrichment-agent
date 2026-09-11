"""DOM cleaning and high-signal link discovery; raw HTML is never passed to the LLM."""

from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .models import PageEvidence
from .utils import emails_in, same_domain

LINK_HINTS = (
    "about",
    "team",
    "company",
    "contact",
    "leadership",
    "people",
    "pricing",
    "press",
    "newsroom",
    "careers",
)


def clean_page(
    url: str, html: str, via: str, status_code: int | None, max_chars: int
) -> PageEvidence:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    description = soup.select_one('meta[name="description"]')
    meta = description.get("content", "").strip() if description else None
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    links: list[str] = []
    linkedin: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor["href"].strip()
        absolute, _ = urldefrag(urljoin(url, href))
        if "linkedin.com/" in absolute.lower():
            linkedin.append(absolute)
        elif absolute.startswith("http") and same_domain(absolute, domain):
            links.append(absolute)

    mailtos = []
    for anchor in soup.select('a[href^="mailto:"]'):
        href = anchor["href"].strip()
        target = href.split(":", 1)[1].split("?", 1)[0].strip()
        if "@" in target:
            mailtos.append(target.lower())

    for node in soup(
        ["script", "style", "svg", "noscript", "iframe", "footer", "nav", "header", "aside"]
    ):
        node.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = re.sub(r"\s+", " ", root.get_text(" ", strip=True))[:max_chars]
    headings = [item.get_text(" ", strip=True) for item in root.select("h1,h2,h3")][:30]
    return PageEvidence(
        url=url,
        title=title,
        meta_description=meta,
        headings=headings,
        text=text,
        emails=sorted(set(emails_in(text) + mailtos)),
        linkedin_urls=sorted(set(linkedin)),
        discovered_links=prioritize_links(links),
        fetched_via=via,
        status_code=status_code,
    )


def prioritize_links(links: list[str]) -> list[str]:
    unique = sorted(set(links))
    return sorted(
        unique,
        key=lambda link: (
            -sum(hint in urlparse(link).path.lower() for hint in LINK_HINTS),
            len(link),
        ),
    )
