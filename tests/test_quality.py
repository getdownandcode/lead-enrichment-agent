import asyncio

from lead_agent.config import Settings
from lead_agent.fetcher import FetchResponse
from lead_agent.models import (
    ContactEmail,
    CostInfo,
    LeadershipProfile,
    LLMExtraction,
    PageEvidence,
)
from lead_agent.orchestrator import (
    EnrichmentOrchestrator,
    _is_customer_page,
    _linkedin_matches_name,
)
from lead_agent.search import SearchHit


def _person(**kwargs):
    defaults = {
        "name": "Jane Doe",
        "title": "CEO",
        "linkedin_url": "https://www.linkedin.com/in/jane-doe",
        "source_url": "https://acme.test/team",
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return LeadershipProfile(**defaults)


def _evidence(url="https://acme.test/team"):
    return [PageEvidence(url=url, text="Acme", fetched_via="httpx")]


def test_customer_pages_do_not_count_as_leadership_evidence():
    assert _is_customer_page("https://acme.test/customers/rally")
    assert _is_customer_page("https://acme.test/blog/launch")
    assert not _is_customer_page("https://acme.test/team")
    assert not _is_customer_page("https://acme.test/about")


def test_linkedin_slug_must_match_name():
    assert _linkedin_matches_name("https://www.linkedin.com/in/ankit-sobti", "Ankit Sobti")
    assert _linkedin_matches_name("https://www.linkedin.com/in/nikhilro", "Nikhil Gupta")
    assert not _linkedin_matches_name(
        "https://www.linkedin.com/in/gerardjamesroy", "Nikhil Gupta"
    )


def test_consistent_sources_keeps_traceable_leaders():
    people = EnrichmentOrchestrator._consistent_sources(
        [_person()], _evidence(), ["https://www.linkedin.com/in/jane-doe"]
    )
    assert people[0].linkedin_url == "https://www.linkedin.com/in/jane-doe"
    assert people[0].source_url == "https://acme.test/team"
    assert people[0].confidence == 0.9


def test_consistent_sources_drops_unknown_sources_and_caps_confidence():
    people = EnrichmentOrchestrator._consistent_sources(
        [_person(source_url="https://en.wikipedia.org/wiki/Acme")], _evidence(), []
    )
    assert people[0].source_url is None
    assert people[0].confidence == 0.5


def test_consistent_sources_rejects_another_persons_profile_as_source():
    people = EnrichmentOrchestrator._consistent_sources(
        [_person(source_url="https://www.linkedin.com/in/gerardjamesroy")],
        _evidence(),
        ["https://www.linkedin.com/in/gerardjamesroy"],
    )
    assert people[0].source_url is None
    assert people[0].confidence == 0.5


def test_consistent_sources_promotes_own_profile_source_to_linkedin():
    people = EnrichmentOrchestrator._consistent_sources(
        [
            _person(
                name="Ant Wilson",
                title="Co-founder",
                linkedin_url=None,
                source_url="https://uk.linkedin.com/in/ant-wilson-46179937",
                confidence=1.0,
            )
        ],
        _evidence(),
        ["https://uk.linkedin.com/in/ant-wilson-46179937"],
    )
    assert people[0].linkedin_url == "https://uk.linkedin.com/in/ant-wilson-46179937"
    assert people[0].confidence == 1.0


def test_consistent_sources_drops_mismatched_linkedin_and_caps():
    people = EnrichmentOrchestrator._consistent_sources(
        [_person(linkedin_url="https://www.linkedin.com/in/someone-else")],
        _evidence(),
        [],
    )
    assert people[0].linkedin_url is None
    assert people[0].confidence == 0.5


def test_consistent_sources_keeps_unverified_fallback_links():
    people = EnrichmentOrchestrator._consistent_sources(
        [_person(name="Unverified", title="Public LinkedIn profile")], _evidence(), []
    )
    assert people[0].linkedin_url == "https://www.linkedin.com/in/jane-doe"


def test_two_sentences_truncates():
    assert (
        EnrichmentOrchestrator._two_sentences("One. Two. Three.")
        == "One. Two."
    )
    assert EnrichmentOrchestrator._two_sentences("Only one.") == "Only one."
    assert EnrichmentOrchestrator._two_sentences(None) is None
    assert EnrichmentOrchestrator._two_sentences("  ") is None


def test_confidence_rewards_evidence_and_caps_at_ceiling():
    extraction = LLMExtraction(company_overview="Acme builds widgets.", target_audience="Devs")
    emails = [ContactEmail(email="hello@acme.test", source_url="https://acme.test/")]
    score = EnrichmentOrchestrator._confidence_score(extraction, emails, [_person()], [])
    assert score == 0.9
    assert EnrichmentOrchestrator._confidence_score(
        LLMExtraction(), [], [], ["a", "b", "c", "d", "e", "f"]
    ) == 0.0


def test_confidence_prefers_onsite_over_search_only_leaders():
    extraction = LLMExtraction(company_overview="Acme.", target_audience="Devs")
    onsite = EnrichmentOrchestrator._confidence_score(extraction, [], [_person()], [])
    search_only = EnrichmentOrchestrator._confidence_score(
        extraction, [], [_person(source_url="https://www.linkedin.com/in/jane-doe")], []
    )
    assert onsite == 0.8
    assert search_only == 0.65


HTML_PLAIN = """<html><head><title>Acme</title>
<meta name="description" content="Acme builds widgets.">
</head><body><main><h1>Acme</h1><p>Contact hello@acme.test</p>
<a href="/about">About</a>
<a href="https://www.linkedin.com/in/random-person">LinkedIn</a></main></body></html>"""


async def _fake_fetch(self, url: str) -> FetchResponse:
    return FetchResponse(url=url, html=HTML_PLAIN, status_code=200, via="httpx")


class _FakeTavily:
    def __init__(self, *args, **kwargs):
        pass

    async def leadership_hits(self, domain: str):
        return [
            SearchHit(
                "Jane Doe CEO Acme",
                "https://www.linkedin.com/in/jane-doe",
                "Jane Doe is the CEO of Acme.",
            )
        ]


class _FakeExtractor:
    def __init__(self, *args, **kwargs):
        pass

    def extract(self, evidence, external_evidence=""):
        if external_evidence:
            leaders = [
                LeadershipProfile(
                    name="Jane Doe",
                    title="CEO",
                    linkedin_url="https://www.linkedin.com/in/jane-doe",
                    source_url="https://www.linkedin.com/in/jane-doe",
                    confidence=0.9,
                )
            ]
            overview = "Acme builds widgets for developers. It was founded in 2020."
        else:
            leaders = []
            overview = "Acme builds widgets."
        return (
            LLMExtraction(company_overview=overview, leadership=leaders, confidence=0.5),
            CostInfo(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                estimated_cost_usd=0.00003,
                estimated=True,
                llm_calls=1,
            ),
        )


def test_two_stage_search_recovers_missing_leadership(monkeypatch):
    monkeypatch.setattr("lead_agent.orchestrator.PageFetcher.fetch", _fake_fetch)
    monkeypatch.setattr("lead_agent.orchestrator.TavilySearch", _FakeTavily)
    monkeypatch.setattr("lead_agent.orchestrator.GeminiExtractor", _FakeExtractor)
    settings = Settings(gemini_api_key="test", tavily_api_key="test", max_pages=2)
    agent = EnrichmentOrchestrator(settings, use_search=True)
    result = asyncio.run(agent.enrich("acme.test"))
    assert [person.name for person in result.leadership] == ["Jane Doe"]
    assert result.cost.llm_calls == 2
    assert result.cost.search_calls == 1
    assert result.status == "success"


def test_search_runs_when_only_customer_pages_have_linkedin(monkeypatch):
    monkeypatch.setattr("lead_agent.orchestrator.TavilySearch", _FakeTavily)
    settings = Settings(gemini_api_key="test", tavily_api_key="test", max_pages=2)
    agent = EnrichmentOrchestrator(settings, use_search=True)
    evidence = [
        PageEvidence(
            url="https://acme.test/customers/rally",
            text="Rally uses Acme.",
            linkedin_urls=["https://www.linkedin.com/in/customer-person"],
            fetched_via="httpx",
        )
    ]
    text, calls, urls = asyncio.run(agent._search("acme.test", evidence, []))
    assert calls == 1
    assert urls == ["https://www.linkedin.com/in/jane-doe"]
    assert "jane-doe" in text
