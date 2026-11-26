"""Panda (panda.sa)

How the data is reached (checked 2026-11-24):
- Category pages /ar/c/<slug>-<id>?page=N are server-rendered (Next.js) with
  30 products per page. Payload: `"products":[{id, name, brand, category,
  varieties:[{id, price, undiscounted_price, size, unit, barcode, sku,
  availability}]}]` and `"totalPages":N`.
- Product page links (/ar/p/<slug>-<id>) come from the sitemap.
- No branch selection is needed for browsing; prices shown are the default
  online prices.
- Product pages also carry schema.org JSON-LD (used for quick refreshes).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

from ..common import (Offer, clean_barcodes, decode_next_flight, iter_json_after,
                      jsonld_products, offer_from_jsonld, parse_size, to_float)
from ..http import Fetcher

log = logging.getLogger(__name__)

STORE = "panda"
BASE = "https://panda.sa"
COOKIES: dict = {}

# Top-level grocery categories (slug-id). Household/beauty/pets/electronics left out.
GROCERY_CATEGORIES = [
    "fresh-311", "bakery-235", "food-basics-466", "cooking-essentials-467",
    "breakfast-468", "frozen-211", "beverages-288", "snacks-238",
    "candy-corner-733", "ready-to-eat-799", "health-and-wellness-790",
]


def parse_listing(html: str, category_slug: str = "",
                  url_by_id: Optional[dict] = None) -> tuple[list[Offer], Optional[int]]:
    flight = decode_next_flight(html)
    # the page can hold several "products" arrays (menus, carousels): take the
    # first one whose items carry varieties
    products = next((v for v in iter_json_after(flight, '"products":')
                     if isinstance(v, list) and v and isinstance(v[0], dict) and "varieties" in v[0]), None)
    m = re.search(r'"totalPages":(\d+)', flight)
    total_pages = int(m.group(1)) if m else None
    offers: list[Offer] = []
    if not isinstance(products, list):
        return offers, total_pages
    for p in products:
        if not isinstance(p, dict):
            continue
        brand = p["brand"].get("name") if isinstance(p.get("brand"), dict) else p.get("brand")
        cat = p["category"].get("name") if isinstance(p.get("category"), dict) else None
        pid = str(p.get("id")) if p.get("id") is not None else None
        for v in p.get("varieties") or []:
            price = to_float(v.get("price"))
            old = to_float(v.get("undiscounted_price"))
            size = parse_size(v.get("size"), v.get("unit")) if v.get("size") else (None, None)
            by_name = parse_size(p.get("name"))
            if size == (None, None):
                size = by_name
            elif (by_name[0] and by_name[1] == size[1] and by_name[0] > size[0]
                  and abs(by_name[0] / size[0] - round(by_name[0] / size[0])) < 0.01):
                # the size field is one unit; the name says it's a multipack ("2 × 1.5 لتر")
                size = by_name
            offers.append(Offer(
                store=STORE,
                store_sku=str(v.get("sku") or v.get("id")),
                name_ar=p.get("name"),
                brand=brand,
                barcodes=clean_barcodes(v.get("barcode")),
                price=price,
                old_price=old if old and price and old > price else None,
                in_stock=bool(v.get("availability")),
                category=cat or category_slug,
                url=(url_by_id or {}).get(pid),
                image_url=v.get("imageURL"),
                size_value=size[0],
                size_unit=size[1],
            ))
    return offers, total_pages


def parse_product(html: str, url: Optional[str] = None) -> Optional[Offer]:
    lds = jsonld_products(html)
    return offer_from_jsonld(STORE, lds[0], url) if lds else None


async def product_url_map(f: Fetcher) -> dict[str, str]:
    """product id -> Arabic product page URL, from the sitemap."""
    index = await f.get("/sitemap.xml") or ""
    maps = re.findall(r"<loc>([^<]*sitemaps/products-\d+\.xml)</loc>", index)
    out: dict[str, str] = {}
    for body in await asyncio.gather(*(f.get(m) for m in maps)):
        for u in re.findall(r"<loc>(https://panda\.sa/ar/p/[^<]+)</loc>", body or ""):
            m = re.search(r"-(\d+)$", u)
            if m:
                out[m.group(1)] = u
    return out


async def crawl(urls: Optional[list[str]] = None, limit: Optional[int] = None,
                concurrency: int = 3) -> AsyncIterator[Offer]:
    async with Fetcher(BASE, COOKIES, concurrency=concurrency) as f:
        if urls is not None:  # quick refresh of known product pages
            async def one(u):
                html = await f.get(u)
                return parse_product(html, u) if html else None
            for offer in await asyncio.gather(*(one(u) for u in urls[:limit] if u)):
                if offer:
                    yield offer
            return

        url_by_id = await product_url_map(f)
        log.info("panda: %d product urls in sitemap", len(url_by_id))
        seen: set[str] = set()
        count = 0
        for slug in GROCERY_CATEGORIES:
            html = await f.get(f"/ar/c/{slug}")
            if not html:
                continue
            offers, pages = parse_listing(html, slug, url_by_id)
            pages = pages or 1
            log.info("panda %s: %s pages", slug, pages)
            rest = await asyncio.gather(*(f.get(f"/ar/c/{slug}?page={n}") for n in range(2, pages + 1)))
            for h in rest:
                if h:
                    offers += parse_listing(h, slug, url_by_id)[0]
            for o in offers:
                if o.store_sku in seen:
                    continue
                seen.add(o.store_sku)
                yield o
                count += 1
                if limit and count >= limit:
                    return
