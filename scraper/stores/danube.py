"""Danube (danube.sa)

How the data is reached (checked 2026-11-24):
- There is no sitemap, and department pages fill their product grid in the
  browser after the visitor picks a city/branch. So this store is read with a
  headless browser (Playwright), page by page, the same way a visitor sees it.
- Branch is held in the `danube_district_id` cookie: 589 = Hayat Mall, Riyadh
  (pickup). `show_store_selector=false` hides the branch pop-up.
- Each product card (div.product-box) has: link /products/<slug>, name,
  current price, and original price when on offer. Prices use Arabic digits.
- Product pages are server-rendered with schema.org JSON-LD (name, sku, brand,
  price) – used for quick refreshes. No barcode is published, so Danube items
  are matched to other stores by name + pack size.
- 18 products per page, ?page=N.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

from bs4 import BeautifulSoup

from ..common import Offer, jsonld_products, offer_from_jsonld, parse_size, to_float
from ..http import Fetcher

log = logging.getLogger(__name__)

STORE = "danube"
BASE = "https://danube.sa"
DISTRICT_ID = "589"  # Hayat, Riyadh
COOKIES = {"danube_district_id": DISTRICT_ID, "show_store_selector": "false"}

GROCERY_DEPARTMENTS = [
    "bakery-2", "fresh-fruits-vegetables", "meat-poultry-seafood", "deli", "cheese",
    "dairy-eggs", "pantry", "baking-essentials", "canned-food", "sauces-dressings",
    "sweets-snacks", "cereals-corn-flakes", "beverages-water", "tea-coffee",
    "dates-roastery", "frozen-food-2", "ready-to-eat", "organic-diet-food",
]


def parse_cards(html: str, category: str = "") -> list[Offer]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for box in soup.select("div.product-box"):
        a = box.find("a", href=re.compile(r"^/products/"))
        if not a:
            continue
        name_el = box.select_one(".product-box__name")
        name = name_el.get_text(" ", strip=True) if name_el else None
        cur = box.select_one(".product-price__current-price")
        orig = box.select_one(".product-price__original-price")
        price = to_float(cur.get_text()) if cur else None
        old = to_float(orig.get_text()) if orig else None
        img = box.select_one(".product-box__image__element")
        img_url = None
        if img and img.get("style"):
            m = re.search(r"url\(([^)]+)\)", img["style"])
            img_url = m.group(1).strip("'\"") if m else None
        # the URL slug is the stable id: it is the same on cards and product pages
        slug = a["href"].split("/products/")[-1].split("?")[0]
        size = parse_size(name)
        out.append(Offer(
            store=STORE,
            store_sku=slug,
            name_ar=name,
            price=price,
            old_price=old if old and price and old > price else None,
            in_stock=box.select_one(".add-to-cart__btn--submit") is not None,
            category=category,
            url=f"{BASE}{a['href']}",
            image_url=img_url,
            size_value=size[0],
            size_unit=size[1],
        ))
    return out


def last_page(html: str) -> int:
    nums = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
    return max(nums) if nums else 1


def parse_product(html: str, url: Optional[str] = None) -> Optional[Offer]:
    lds = jsonld_products(html)
    if not lds:
        return None
    offer = offer_from_jsonld(STORE, lds[0], url)
    page_url = url or offer.url or ""
    if "/products/" in page_url:
        offer.store_sku = page_url.split("/products/")[-1].split("?")[0]
    m = re.search(r'product-price__original-price__span">.*?([\d.,]+)\s*</span>', html, re.S)
    old = to_float(m.group(1)) if m else None
    if old and offer.price and old > offer.price:
        offer.old_price = old
    return offer


async def _crawl_with_browser(limit: Optional[int]) -> AsyncIterator[Offer]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(locale="ar-SA")
        await ctx.add_cookies([
            {"name": k, "value": v, "domain": "danube.sa", "path": "/"} for k, v in COOKIES.items()
        ])
        page = await ctx.new_page()
        seen: set[str] = set()
        count = 0

        async def load(url: str) -> str:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector("div.product-box", timeout=20000)
            except Exception:
                pass
            await asyncio.sleep(1.0)
            return await page.content()

        for dept in GROCERY_DEPARTMENTS:
            url = f"{BASE}/departments/{dept}"
            html = await load(url)
            pages = last_page(html)
            log.info("danube %s: %d pages", dept, pages)
            for n in range(1, pages + 1):
                if n > 1:
                    html = await load(f"{url}?page={n}")
                for o in parse_cards(html, dept):
                    if o.store_sku in seen:
                        continue
                    seen.add(o.store_sku)
                    yield o
                    count += 1
                    if limit and count >= limit:
                        await browser.close()
                        return
        await browser.close()


async def crawl(urls: Optional[list[str]] = None, limit: Optional[int] = None,
                concurrency: int = 2) -> AsyncIterator[Offer]:
    if urls is None:
        async for o in _crawl_with_browser(limit):
            yield o
        return
    # quick refresh: product pages are plain server-rendered HTML
    async with Fetcher(BASE, COOKIES, concurrency=concurrency) as f:
        async def one(u):
            html = await f.get(u)
            return parse_product(html, u) if html else None
        for offer in await asyncio.gather(*(one(u) for u in urls[:limit] if u)):
            if offer:
                yield offer
