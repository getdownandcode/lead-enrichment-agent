"""Progressive retrieval: Playwright when available, HTTP as a dependable fallback."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

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
        self._playwright_mgr: Any = None
        self._browser: Any = None
        self._playwright_available: bool | None = None

    async def _get_browser(self) -> Any:
        if self._playwright_available is False:
            return None
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright

                self._playwright_mgr = async_playwright()
                playwright = await self._playwright_mgr.start()
                self._browser = await playwright.chromium.launch(headless=True)
                self._playwright_available = True
            except Exception:
                self._playwright_available = False
                return None
        return self._browser

    async def close(self) -> None:
        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright_mgr:
            with contextlib.suppress(Exception):
                await self._playwright_mgr.__aexit__(None, None, None)
            self._playwright_mgr = None

    async def fetch(self, url: str) -> FetchResponse:
        browser_error: Exception | None = None
        browser = await self._get_browser()
        if browser:
            try:
                return await self._fetch_browser(browser, url)
            except Exception as exc:
                browser_error = exc
        try:
            return await self._httpx_get(url)
        except httpx.HTTPError as exc:
            suffix = f"; browser: {type(browser_error).__name__}" if browser_error else ""
            raise RuntimeError(f"Could not fetch {url}: {exc}{suffix}") from exc

    async def _fetch_browser(self, browser: Any, url: str) -> FetchResponse:
        page = await browser.new_page(user_agent=self.headers["User-Agent"])
        try:
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
                raise RuntimeError(f"Playwright got HTTP {status} for {url}")
            return FetchResponse(
                page.url,
                await page.content(),
                status,
                "playwright",
            )
        finally:
            await page.close()

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
