import asyncio

from lead_agent.config import Settings
from lead_agent.fetcher import FetchResponse
from lead_agent.orchestrator import EnrichmentOrchestrator

HTML = """<html><head><title>Acme</title>
<meta name="description" content="Acme builds widgets for developers.">
</head><body><main><h1>Acme</h1><p>Contact hello@acme.test</p>
<a href="/about">About</a></main></body></html>"""


async def _fake_fetch(self, url: str) -> FetchResponse:
    return FetchResponse(url=url, html=HTML, status_code=200, via="httpx")


def test_enrich_without_keys_returns_deterministic_evidence(monkeypatch):
    monkeypatch.setattr("lead_agent.orchestrator.PageFetcher.fetch", _fake_fetch)
    settings = Settings(gemini_api_key=None, tavily_api_key=None, max_pages=2)
    agent = EnrichmentOrchestrator(settings, use_search=False)
    result = asyncio.run(agent.enrich("acme.test"))
    assert result.status in {"success", "partial"}
    assert any("GEMINI_API_KEY" in warning for warning in result.warnings)
    assert result.source_pages


def test_enrich_invalid_domain_fails_cleanly():
    settings = Settings(gemini_api_key=None, tavily_api_key=None)
    agent = EnrichmentOrchestrator(settings, use_search=False)
    result = asyncio.run(agent.enrich("not a domain"))
    assert result.status == "failed"
    assert result.warnings
