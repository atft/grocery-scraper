"""Polite async HTTP client: limited concurrency, delay between requests,
retries with back-off. Only plain public pages are requested."""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_UA = os.getenv(
    "SCRAPER_USER_AGENT",
    "Mozilla/5.0 (compatible; RiyadhGroceryPriceCompare/0.1; price comparison)",
)


class Fetcher:
    def __init__(
        self,
        base_url: str,
        cookies: Optional[dict] = None,
        concurrency: int = 4,
        delay: float = 0.5,
        timeout: float = 30.0,
    ):
        import httpx  # imported here so parsers can be tested without it

        self._httpx = httpx
        self.sem = asyncio.Semaphore(concurrency)
        self.delay = delay
        self.client = httpx.AsyncClient(
            base_url=base_url,
            cookies=cookies or {},
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "ar,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
            http2=False,
        )
        self.requests = 0
        self.failures = 0

    async def get(self, url: str, retries: int = 3) -> Optional[str]:
        for attempt in range(retries):
            async with self.sem:
                try:
                    r = await self.client.get(url)
                    self.requests += 1
                    await asyncio.sleep(self.delay + random.random() * self.delay)
                    if r.status_code == 200:
                        return r.text
                    if r.status_code == 404:
                        return None
                    if r.status_code in (403, 429):
                        # being rate limited / blocked: back off hard
                        log.warning("HTTP %s on %s, backing off", r.status_code, url)
                        await asyncio.sleep(30 * (attempt + 1))
                    else:
                        log.info("HTTP %s on %s", r.status_code, url)
                except self._httpx.HTTPError as e:
                    log.info("error on %s: %s", url, e)
            await asyncio.sleep(2 ** attempt)
        self.failures += 1
        return None

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
