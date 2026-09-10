"""Gemini structured extraction with explicit evidence-only prompting and usage accounting."""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from .models import CostInfo, LLMExtraction, PageEvidence, VerificationResult

PROMPT = """You are a careful B2B lead-research analyst. Extract only facts supported by the supplied public-site evidence. Do not invent people, titles, emails, or LinkedIn URLs. If a field is unsupported, return null or an empty list. Company overview must be at most two sentences. Confidence represents evidence completeness, not your certainty.

Leadership rules: list ONLY people who are current executives or employees of THIS company (founders, C-suite, VPs, team members). NEVER list customers, partners, investors, advisors, or people quoted in testimonials, case studies, or blog author bylines unless the evidence explicitly states they work at this company. If the evidence only shows customers or no team members, return an empty leadership list. Only include a LinkedIn URL if it appeared explicitly in the evidence for that same person; otherwise use null. Set source_url to the evidence page where you found the person.

EVIDENCE:
"""

VERIFY_PROMPT = """You are a skeptical fact-checking editor for B2B sales intelligence. A junior analyst drafted the DRAFT below from the EVIDENCE (fetched company pages) plus optional SEARCH evidence (external search snippets). Your job: verify every claim, fix or drop anything unsupported, and decide whether an external search is still needed.

PEOPLE — keep ONLY current executives or employees of THIS company (founders, C-suite, VPs, team members). DROP customers, partners, investors, advisors, testimonial subjects, case-study contacts, and blog authors unless the evidence explicitly states they work at this company. An empty leadership list is a correct answer when the evidence shows no team members.
URLS — every linkedin_url must have appeared explicitly in EVIDENCE or SEARCH for that SAME person, otherwise null. Every source_url must be one of EVIDENCE_URLS or SEARCH_URLS, otherwise null. A LinkedIn profile page is about one person only: never cite another person's profile as someone's source.
TEXT — company_overview must be at most two sentences; target_audience one crisp phrase or sentence. Fix them if they violate this.
SEARCH — if leadership is empty or uncertain AND no search has been used yet (ALLOW_SEARCH is true), set needs_search=true with a specific query such as '"<domain>" (founder OR CEO OR leadership) site:linkedin.com/in'. If search was already used (ALLOW_SEARCH is false), never request again: return your best-effort verification with lowered confidence.
CONFIDENCE — your honest 0.0-1.0 assessment of the VERIFIED record: award 0.85+ only when every kept leader traces to a company page or their own profile and overview plus audience are both present; keep search-only or thinly sourced records at 0.7 or below; use notes to explain deductions.
"""

# USD per 1M tokens (input, output). Google has not published pricing for a
# `gemini-3.5-flash-lite` identifier, so it inherits the public Gemini
# Flash-Lite tier until pricing is confirmed; adjust here when announced.
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
}
DEFAULT_PRICING_USD_PER_MTOK: tuple[float, float] = (0.10, 0.40)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost from token usage using the Flash-Lite pricing table."""
    input_price, output_price = MODEL_PRICING_USD_PER_MTOK.get(model, DEFAULT_PRICING_USD_PER_MTOK)
    return round(prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price, 6)


class GeminiExtractor:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def extract(
        self, evidence: list[PageEvidence], external_evidence: str = ""
    ) -> tuple[LLMExtraction, CostInfo]:
        compact = [
            {
                "url": item.url,
                "title": item.title,
                "description": item.meta_description,
                "headings": item.headings,
                "text": item.text,
                "emails": item.emails,
                "linkedin_urls": item.linkedin_urls,
            }
            for item in evidence
        ]
        response = self.client.models.generate_content(
            model=self.model,
            contents=PROMPT
            + json.dumps(compact, ensure_ascii=False)
            + "\nSEARCH EVIDENCE:\n"
            + external_evidence,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=LLMExtraction,
            ),
        )
        parsed = LLMExtraction.model_validate_json(response.text)
        usage = getattr(response, "usage_metadata", None)
        prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion = int(getattr(usage, "candidates_token_count", 0) or 0)
        return parsed, CostInfo(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            estimated_cost_usd=estimate_cost_usd(self.model, prompt, completion),
            estimated=True,
            llm_calls=1,
        )

    def verify(
        self,
        evidence: list[PageEvidence],
        draft: LLMExtraction,
        search_text: str = "",
        search_urls: list[str] | None = None,
        allow_search: bool = True,
    ) -> tuple[VerificationResult, CostInfo]:
        """AI fact-check of a draft extraction; may request a search tool call."""
        compact = [
            {
                "url": item.url,
                "title": item.title,
                "headings": item.headings,
                "emails": item.emails,
                "linkedin_urls": item.linkedin_urls,
            }
            for item in evidence
        ]
        contents = (
            VERIFY_PROMPT
            + "\nEVIDENCE_URLS:\n"
            + json.dumps(compact, ensure_ascii=False)
            + "\nDRAFT:\n"
            + draft.model_dump_json()
            + "\nSEARCH_URLS:\n"
            + json.dumps(search_urls or [], ensure_ascii=False)
            + "\nSEARCH EVIDENCE:\n"
            + search_text
            + f"\nALLOW_SEARCH: {allow_search}\n"
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=VerificationResult,
            ),
        )
        parsed = VerificationResult.model_validate_json(response.text)
        usage = getattr(response, "usage_metadata", None)
        prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion = int(getattr(usage, "candidates_token_count", 0) or 0)
        return parsed, CostInfo(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            estimated_cost_usd=estimate_cost_usd(self.model, prompt, completion),
            estimated=True,
            llm_calls=1,
        )
