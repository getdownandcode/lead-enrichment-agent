"""Portable JSON and analyst-friendly CSV output writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import CompanyEnrichmentResult


def write_json(results: list[CompanyEnrichmentResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([item.model_dump(mode="json") for item in results], indent=2), encoding="utf-8"
    )


def write_csv(results: list[CompanyEnrichmentResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "domain",
        "status",
        "company_overview",
        "target_audience",
        "emails",
        "leadership",
        "confidence",
        "source_pages",
        "warnings",
        "llm_calls",
        "search_calls",
        "total_tokens",
        "estimated_cost_usd",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in results:
            writer.writerow(
                {
                    "domain": item.domain,
                    "status": item.status,
                    "company_overview": item.company_overview or "",
                    "target_audience": item.target_audience or "",
                    "emails": "; ".join(x.email for x in item.contact_emails),
                    "leadership": "; ".join(f"{x.name} ({x.title})" for x in item.leadership),
                    "confidence": item.data_confidence_score,
                    "source_pages": "; ".join(item.source_pages),
                    "warnings": " | ".join(item.warnings),
                    "llm_calls": item.cost.llm_calls,
                    "search_calls": item.cost.search_calls,
                    "total_tokens": item.cost.total_tokens,
                    "estimated_cost_usd": item.cost.estimated_cost_usd,
                }
            )
