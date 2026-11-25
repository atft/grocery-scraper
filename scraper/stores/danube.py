"""Danube (danube.sa)

How the data is reached (checked 2026-11-24):
- There is no sitemap, and department pages fill their product grid in the
  browser after the visitor picks a city/branch. So this store is read with a
  headless browser (Playwright), page by page, the same way a visitor sees it.
- Branch: the crawler picks 'pickup' + 'حياة' (Hayat Mall, Riyadh) in the site's
  pop-up like a visitor. The cookie `danube_district_id=589` alone is not enough
  for the product grid (first run returned 0), but is sent on product pages.
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


BRANCH_NAME = "حياة"  # Hayat Mall, Riyadh – as written in the site's branch list
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


async def choose_branch(page, base: str = BASE, branch: Optional[str] = None) -> bool:
    """Pick 'pickup from store' + the Riyadh branch in the site's own pop-up,
    exactly as a visitor does. The site keeps the choice in its session."""
    branch = branch or BRANCH_NAME
    await page.goto(f"{base}/departments/pantry", wait_until="domcontentloaded", timeout=60000)
    pickup = page.get_by_text("الإستلام من المتجر").first
    try:
        await pickup.wait_for(state="visible", timeout=20000)
    except Exception:
        log.warning("danube: branch pop-up did not appear")
        return False
    await pickup.click()
    # the branch list is filled after the click
    try:
        await page.wait_for_function(
            """(name) => [...document.querySelectorAll('select')]
                 .some(s => [...s.options].some(o => o.text.trim() === name))""",
            arg=branch, timeout=20000)
    except Exception:
        log.warning("danube: branch %s not found in the list", branch)
        return False
    await page.evaluate(
        """(name) => {
             const s = [...document.querySelectorAll('select')]
               .find(s => [...s.options].some(o => o.text.trim() === name));
             s.selectedIndex = [...s.options].findIndex(o => o.text.trim() === name);
             s.dispatchEvent(new Event('change', {bubbles: true}));
           }""", branch)
    await page.wait_for_timeout(800)
    await page.get_by_role("button", name="اختار").first.click()
    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    log.info("danube: branch selected (%s)", branch)
    return True


async def _debug_dump(page, label: str):
    """When a page shows no products, keep a screenshot + text to see why."""
    from pathlib import Path
    Path("out").mkdir(exist_ok=True)
    try:
        await page.screenshot(path=f"out/danube-{label}.png", full_page=False)
        text = (await page.inner_text("body"))[:400].replace("\n", " | ")
        log.warning("danube %s: no products. title=%r url=%s text=%s",
                    label, await page.title(), page.url, text)
    except Exception as e:
        log.warning("danube %s: debug dump failed: %s", label, e)


async def _crawl_with_browser(limit: Optional[int], base: str = BASE) -> AsyncIterator[Offer]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(locale="ar-SA", timezone_id="Asia/Riyadh",
                                        user_agent=BROWSER_UA, viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        await choose_branch(page, base)
        seen: set[str] = set()
        count = 0
        dumps = 0

        async def load(url: str) -> str:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector("div.product-box", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
            return await page.content()

        for dept in GROCERY_DEPARTMENTS:
            url = f"{base}/departments/{dept}"
            html = await load(url)
            pages = last_page(html)
            cards = parse_cards(html, dept)
            log.info("danube %s: %d pages, %d products on page 1", dept, pages, len(cards))
            if not cards and dumps < 2:
                await _debug_dump(page, dept)
                dumps += 1
            for n in range(1, pages + 1):
                if n > 1:
                    html = await load(f"{url}?page={n}")
                    cards = parse_cards(html, dept)
                for o in cards:
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
