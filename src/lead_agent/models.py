"""Strict data contracts for the pipeline and its public output."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ContactEmail(BaseModel):
    email: str
    category: str = "other"
    source_url: str | None = None


class LeadershipProfile(BaseModel):
    name: str
    title: str
    linkedin_url: str | None = None
    source_url: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class CostInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated: bool = False
    llm_calls: int = 0
    search_calls: int = 0


class PageEvidence(BaseModel):
    url: str
    title: str | None = None
    meta_description: str | None = None
    headings: list[str] = Field(default_factory=list)
    text: str = ""
    emails: list[str] = Field(default_factory=list)
    linkedin_urls: list[str] = Field(default_factory=list)
    discovered_links: list[str] = Field(default_factory=list)
    fetched_via: Literal["playwright", "httpx"]
    status_code: int | None = None


class LLMExtraction(BaseModel):
    company_overview: str | None = None
    target_audience: str | None = None
    leadership: list[LeadershipProfile] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_notes: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """The AI verifier's final word on a draft extraction."""

    needs_search: bool = False
    search_query: str | None = None
    leadership: list[LeadershipProfile] = Field(default_factory=list)
    company_overview: str | None = None
    target_audience: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


class CompanyEnrichmentResult(BaseModel):
    domain: str
    final_url: str | None = None
    status: Literal["success", "partial", "failed"]
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    company_overview: str | None = None
    target_audience: str | None = None
    contact_emails: list[ContactEmail] = Field(default_factory=list)
    leadership: list[LeadershipProfile] = Field(default_factory=list)
    data_confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_pages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cost: CostInfo = Field(default_factory=CostInfo)

    @field_validator("domain")
    @classmethod
    def domain_is_not_url(cls, value: str) -> str:
        return value.lower().removeprefix("www.")
