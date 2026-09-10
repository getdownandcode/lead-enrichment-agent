import csv
import json

from lead_agent.models import CompanyEnrichmentResult, ContactEmail, CostInfo, LeadershipProfile
from lead_agent.writers import write_csv, write_json


def _sample() -> CompanyEnrichmentResult:
    return CompanyEnrichmentResult(
        domain="example.com",
        final_url="https://example.com/",
        status="success",
        company_overview="Example builds widgets.",
        target_audience="Developers building widgets.",
        contact_emails=[
            ContactEmail(email="hello@example.com", category="hello", source_url="https://example.com/")
        ],
        leadership=[
            LeadershipProfile(
                name="Jane Doe",
                title="CEO",
                linkedin_url="https://www.linkedin.com/in/jane-doe",
                source_url="https://example.com/team",
                confidence=0.9,
            )
        ],
        data_confidence_score=0.85,
        source_pages=["https://example.com/", "https://example.com/about"],
        warnings=[],
        cost=CostInfo(
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            estimated_cost_usd=0.00018,
            estimated=True,
            llm_calls=1,
            search_calls=0,
        ),
    )


def test_write_json_roundtrip(tmp_path):
    path = tmp_path / "out.json"
    write_json([_sample()], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["domain"] == "example.com"
    assert payload[0]["cost"]["llm_calls"] == 1


def test_write_csv_headers_and_rows(tmp_path):
    path = tmp_path / "out.csv"
    write_csv([_sample()], path)
    with path.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["domain"] == "example.com"
    assert "hello@example.com" in rows[0]["emails"]
    assert "Jane Doe (CEO)" in rows[0]["leadership"]
    assert rows[0]["estimated_cost_usd"] == "0.00018"
