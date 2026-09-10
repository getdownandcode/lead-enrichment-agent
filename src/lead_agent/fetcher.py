"""Progressive retrieval: Playwright when available, HTTP as a dependable fallback."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


@dataclass
class FetchResponse:
    url: str
    html: str
    status_code: int | None
    via: str


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Retry transient network errors only; HTTP error statuses fail fast.

    A raised HTTP status (404/403/429/5xx) is not retried here — it propagates
    to the orchestrator, which records a per-URL warning and continues.
    """
    return isinstance(
        exc, httpx.TimeoutException | httpx.ConnectError | httpx.RemoteProtocolError
    )


class PageFetcher:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.headers = {"User-Agent": "LeadEnrichmentAgent/1.0 (+public-web-research)"}

    async def fetch(self, url: str) -> FetchResponse:
        browser_error: Exception | None = None
        try:
            return await self._playwright(url)
        except Exception as exc:  # browser is optional and should never stop enrichment
            browser_error = exc
        try:
            return await self._httpx_get(url)
        except httpx.HTTPError as exc:
            suffix = f"; browser: {type(browser_error).__name__}" if browser_error else ""
            raise RuntimeError(f"Could not fetch {url}: {exc}{suffix}") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable_http_error),
        reraise=True,
    )
    async def _httpx_get(self, url: str) -> FetchResponse:
        async with httpx.AsyncClient(
            headers=self.headers, timeout=self.timeout_seconds, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return FetchResponse(str(response.url), response.text, response.status_code, "httpx")

    async def _playwright(self, url: str) -> FetchResponse:
        # Import lazily so a standard install stays usable without browser binaries.
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=self.headers["User-Agent"])
                await page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in {"image", "media", "font"}
                        else route.continue_()
                    ),
                )
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=int(self.timeout_seconds * 1000)
                )
                status = response.status if response else None
                if status is not None and status >= 400:
                    # Treat bot-blocker/404 pages as fetch failures so the
                    # orchestrator records a warning and moves on instead of
                    # extracting "content" from an error page.
                    raise RuntimeError(f"Playwright got HTTP {status} for {url}")
                return FetchResponse(
                    page.url,
                    await page.content(),
                    status,
                    "playwright",
                )
            finally:
                await browser.close()
