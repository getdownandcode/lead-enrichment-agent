"""Evidence-first multi-step controller; one bad site never ends a run."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from urllib.parse import urlparse

from .cleaner import clean_page
from .config import Settings
from .fetcher import PageFetcher
from .llm import GeminiExtractor
from .models import (
    CompanyEnrichmentResult,
    ContactEmail,
    CostInfo,
    LeadershipProfile,
    LLMExtraction,
    PageEvidence,
)
from .search import TavilySearch
from .utils import email_category, normalize_domain

CUSTOMER_PATH_HINTS = (
    "/customer",
    "/customers",
    "/case-stud",
    "/blog",
    "/news",
    "/press",
    "/stories",
    "/story",
    "/testimonial",
)


def _is_customer_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in CUSTOMER_PATH_HINTS)


def _linkedin_matches_name(url: str, name: str) -> bool:
    slug = urlparse(url).path.split("/in/")[-1].strip("/").lower()
    slug_clean = re.sub(r"[^a-z0-9]", "", slug)
    name_parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in name.split()]
    name_parts = [p for p in name_parts if len(p) >= 3]
    if not name_parts or not slug_clean:
        return False
    return any(part in slug_clean for part in name_parts)


class EnrichmentOrchestrator:
    def __init__(self, settings: Settings, use_search: bool = True) -> None:
        self.settings = settings
        self.use_search = use_search
        self.fetcher = PageFetcher(settings.request_timeout_seconds)

    async def close(self) -> None:
        await self.fetcher.close()

    async def enrich(self, raw_domain: str) -> CompanyEnrichmentResult:
        try:
            domain = normalize_domain(raw_domain)
        except ValueError as exc:
            return CompanyEnrichmentResult(domain=raw_domain, status="failed", warnings=[str(exc)])
        evidence: list[PageEvidence] = []
        warnings: list[str] = []
        queue = [f"https://{domain}"]
        visited: set[str] = set()
        while queue and len(evidence) < self.settings.max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                response = await self.fetcher.fetch(url)
                # A redirect can change the canonical hostname or trailing slash.
                # Remember it so a homepage link cannot consume a second page slot.
                visited.add(response.url)
                page = clean_page(
                    response.url,
                    response.html,
                    response.via,
                    response.status_code,
                    self.settings.max_page_text_chars,
                )
                evidence.append(page)
                # Dynamic navigation: merge new same-site links into a relevance-ranked queue.
                queue = self._merge_queue(queue, page.discovered_links, visited)
            except Exception as exc:
                warnings.append(f"{url}: {type(exc).__name__}: {exc}")
                # Some companies only expose the www host. Try it once only
                # when the canonical hostname itself could not be retrieved.
                if not evidence and url == f"https://{domain}":
                    queue.append(f"https://www.{domain}")
        if not evidence:
            return CompanyEnrichmentResult(domain=domain, status="failed", warnings=warnings)
        emails = self._emails(evidence)
        search_calls = 0
        search_urls: list[str] = []
        extraction, cost = await self._extract(evidence, "", warnings)
        needs_search = not extraction.leadership or not any(
            p.linkedin_url for p in extraction.leadership
        )
        if (
            needs_search
            and self.use_search
            and self.settings.tavily_api_key
        ):
            search_text, search_calls, search_urls = await self._search(domain, evidence, warnings)
            if search_text:
                extra_extraction, extra_cost = await self._extract(evidence, search_text, warnings)
                self._absorb(cost, extra_cost)
                if extra_extraction.leadership:
                    extraction.leadership = self._dedupe_people(
                        [*extra_extraction.leadership, *extraction.leadership]
                    )
                if not extraction.company_overview and extra_extraction.company_overview:
                    extraction.company_overview = extra_extraction.company_overview
                if not extraction.target_audience and extra_extraction.target_audience:
                    extraction.target_audience = extra_extraction.target_audience
        cost.search_calls = search_calls
        leadership = self._consistent_sources(extraction.leadership, evidence, search_urls)
        leadership = self._dedupe_people(leadership)
        overview = self._two_sentences(extraction.company_overview)
        confidence = self._confidence_score(extraction, emails, leadership, warnings)
        return CompanyEnrichmentResult(
            domain=domain,
            final_url=evidence[0].url,
            status="success" if confidence >= 0.5 else "partial",
            company_overview=overview,
            target_audience=extraction.target_audience,
            contact_emails=emails,
            leadership=leadership,
            data_confidence_score=confidence,
            source_pages=[item.url for item in evidence],
            warnings=warnings,
            cost=cost,
        )

    @staticmethod
    def _absorb(target: CostInfo, extra: CostInfo) -> None:
        target.prompt_tokens += extra.prompt_tokens
        target.completion_tokens += extra.completion_tokens
        target.total_tokens += extra.total_tokens
        target.estimated_cost_usd = round(target.estimated_cost_usd + extra.estimated_cost_usd, 6)
        target.llm_calls += extra.llm_calls
        target.search_calls += extra.search_calls
        target.estimated = target.estimated or extra.estimated

    @staticmethod
    def _merge_queue(queue: list[str], links: Iterable[str], visited: set[str]) -> list[str]:
        candidates = list(dict.fromkeys([*queue, *links]))
        result: list[str] = []
        canonical_seen = {item.rstrip("/") for item in visited}
        for item in candidates:
            canonical = item.rstrip("/")
            if canonical not in canonical_seen:
                canonical_seen.add(canonical)
                result.append(item)
        return result

    @staticmethod
    def _emails(evidence: list[PageEvidence]) -> list[ContactEmail]:
        locations: dict[str, str] = {}
        for page in evidence:
            for address in page.emails:
                locations.setdefault(address, page.url)
        return [
            ContactEmail(email=address, category=email_category(address), source_url=url)
            for address, url in locations.items()
        ]

    async def _search(
        self,
        domain: str,
        evidence: list[PageEvidence] | str = "",
        warnings: list[str] | None = None,
    ) -> tuple[str, int, list[str]]:
        """Run one Tavily leadership lookup; returns (text, calls, hit_urls)."""
        if warnings is None:
            warnings = []
        if not self.use_search or not self.settings.tavily_api_key:
            return "", 0, []

        try:
            hits = await TavilySearch(
                self.settings.tavily_api_key, self.settings.request_timeout_seconds
            ).leadership_hits(domain)
            text = "\n".join(
                f"Title: {hit.title}\nURL: {hit.url}\nSnippet: {hit.snippet}" for hit in hits
            )
            return text, 1, [hit.url for hit in hits]
        except Exception as exc:
            warnings.append(f"Tavily search unavailable: {type(exc).__name__}: {exc}")
            return "", 1, []

    async def _extract(self, evidence: list[PageEvidence], search_text: str, warnings: list[str]):
        if not self.settings.gemini_api_key:
            warnings.append(
                "GEMINI_API_KEY is not configured; returned deterministic website evidence only."
            )
            return self._fallback(evidence), CostInfo()
        try:
            return await asyncio.to_thread(
                GeminiExtractor(self.settings.gemini_api_key, self.settings.gemini_model).extract,
                evidence,
                search_text,
            )
        except Exception as exc:
            warnings.append(f"Gemini structured extraction failed: {type(exc).__name__}: {exc}")
            return self._fallback(evidence), CostInfo()

    @staticmethod
    def _fallback(evidence: list[PageEvidence]):
        lead_urls = [(url, page.url) for page in evidence for url in page.linkedin_urls]
        leadership = [
            LeadershipProfile(
                name="Unverified",
                title="Public LinkedIn profile",
                linkedin_url=url,
                source_url=source,
                confidence=0.2,
            )
            for url, source in lead_urls
        ]
        description = next(
            (page.meta_description for page in evidence if page.meta_description), None
        )
        return LLMExtraction(company_overview=description, leadership=leadership, confidence=0.2)

    @staticmethod
    def _dedupe_people(people: list[LeadershipProfile]) -> list[LeadershipProfile]:
        by_name: dict[str, LeadershipProfile] = {}
        unverified: list[LeadershipProfile] = []
        for person in people:
            name_key = person.name.casefold().strip()
            if not name_key:
                continue
            if name_key == "unverified":
                unverified.append(person)
                continue
            if name_key not in by_name:
                by_name[name_key] = person
            else:
                existing = by_name[name_key]
                if (not existing.linkedin_url and person.linkedin_url) or (
                    person.confidence > existing.confidence
                ):
                    by_name[name_key] = person
        return list(by_name.values()) + unverified

    @staticmethod
    def _consistent_sources(
        people: list[LeadershipProfile],
        evidence: list[PageEvidence],
        search_urls: list[str],
    ) -> list[LeadershipProfile]:
        """Enforce provenance: drop untraceable URLs instead of showing them.

        A leader's source must be a fetched page or a Tavily hit, and a
        LinkedIn URL must match the person's name. Anything failing the check
        is nulled and that row's confidence is capped at 0.5.
        """
        allowed = {page.url for page in evidence} | set(search_urls)
        cleaned: list[LeadershipProfile] = []
        for person in people:
            linkedin_url = person.linkedin_url
            if (
                linkedin_url
                and " " in person.name.strip()  # skip the "Unverified" fallback sentinel
                and not _linkedin_matches_name(linkedin_url, person.name)
            ):
                linkedin_url = None
            dropped_linkedin = person.linkedin_url is not None and linkedin_url is None
            source_url = person.source_url if person.source_url in allowed else None
            if source_url and _is_customer_page(source_url):
                source_url = None
            if (
                source_url
                and "/in/" in urlparse(source_url).path
                and " " in person.name.strip()
                and not _linkedin_matches_name(source_url, person.name)
            ):
                # A LinkedIn profile page is about one person: another
                # person's profile can never be this leader's source.
                source_url = None
            if (
                linkedin_url is None
                and source_url
                and "/in/" in urlparse(source_url).path
                and " " in person.name.strip()
                and _linkedin_matches_name(source_url, person.name)
            ):
                # The source IS their own profile: promote it so the required
                # LinkedIn field is filled with a verified URL.
                linkedin_url = source_url
            confidence = person.confidence
            if source_url is None or dropped_linkedin:
                confidence = min(confidence, 0.5)
            cleaned.append(
                person.model_copy(
                    update={
                        "linkedin_url": linkedin_url,
                        "source_url": source_url,
                        "confidence": confidence,
                    }
                )
            )
        return cleaned

    @staticmethod
    def _two_sentences(text: str | None) -> str | None:
        """Enforce the 2-sentence overview contract deterministically."""
        if not text or not text.strip():
            return None
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return " ".join(parts[:2]) or None

    @staticmethod
    def _confidence_score(
        extraction: LLMExtraction,
        emails: list[ContactEmail],
        leadership: list[LeadershipProfile],
        warnings: list[str],
    ) -> float:
        """Deterministic evidence-based confidence; never trusts LLM self-report.

        On-site sourced leaders (a company page, not a LinkedIn URL) outrank
        search-only ones, and the practical ceiling is 0.9: anything higher
        requires manual verification.
        """
        score = 0.0
        if extraction.company_overview:
            score += 0.30
        if extraction.target_audience:
            score += 0.20
        if emails:
            score += 0.10
        onsite = [
            person
            for person in leadership
            if person.source_url and "linkedin.com/" not in person.source_url.lower()
        ]
        if onsite:
            score += 0.30
        elif leadership:
            score += 0.15
        score -= min(0.10, 0.02 * len(warnings))
        return round(max(0.0, min(1.0, score)), 2)
