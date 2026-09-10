"""Tavily search enrichment. Search snippets are evidence, not a licence to scrape LinkedIn."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


class TavilySearch:
    def __init__(self, api_key: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.TimeoutException)
        | retry_if_exception_type(httpx.ConnectError)
        | retry_if_exception_type(httpx.RemoteProtocolError),
        reraise=True,
    )
    async def leadership_hits(self, domain: str, query: str | None = None) -> list[SearchHit]:
        search_query = (
            query if query else f'"{domain}" (founder OR CEO OR leadership) site:linkedin.com/in'
        )
        payload = {
            "api_key": self.api_key,
            "query": search_query,
            "max_results": 5,
            "search_depth": "basic",
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds, headers=headers) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
        return [
            SearchHit(item.get("title", ""), item.get("url", ""), item.get("content", ""))
            for item in response.json().get("results", [])
        ]
