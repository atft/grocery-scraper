"""Lulu Hypermarket KSA (gcc.luluhypermarket.com/ar-sa)

How the data is reached (checked 2026-11-24):
- /ar-sa/sitemap/categories-1 lists every category page. Grocery ones start
  with /ar-sa/grocery-... and /ar-sa/fresh-... ; the top pages (/grocery/)
  are landing pages, so we read the leaf categories.
- Category pages ?page=N are server-rendered (Next.js), 50 products each:
  `"listing":{"data":{"pagination":{num_pages,...},"products":[{pk, name, sku,
  attributes:{ean, brand, level_1..3}, price, retail_price, in_stock,
  absolute_url}]}}`. `ean` can hold several barcodes separated by commas.
- Location is held in the `userLocationWeb` / `erp_code` cookies. Default is
  Al Khaleej, Riyadh (store 3734) – we set it explicitly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional
from urllib.parse import unquote

from ..common import (Offer, clean_barcodes, decode_next_flight, extract_json_after,
                      jsonld_products, offer_from_jsonld, parse_size, to_float)
from ..http import Fetcher

log = logging.getLogger(__name__)

STORE = "lulu"
BASE = "https://gcc.luluhypermarket.com"
COOKIES = {
    "pz-locale": "ar-sa",
    "pz-currency": "sar",
    "erp_code": "3734",
    "userLocationWeb": json.dumps({
        "country": "KSA", "locationTitle": "Al Khaleej",
        "latitude": 24.7522805, "longitude": 46.7693938, "ffc": "3734",
    }, separators=(",", ":")),
}

GROCERY_PREFIXES = ("grocery-", "fresh-")
# inside grocery-* these are not food
EXCLUDE_WORDS = ("household", "personal-care", "baby-care", "pet", "health-beauty",
                 "beauty", "tobacco", "laundry", "cleaning", "air-fresheners", "paper")


def parse_listing(html: str) -> tuple[list[Offer], Optional[int]]:
    flight = decode_next_flight(html)
    listing, _ = extract_json_after(flight, '"listing":')
    if not isinstance(listing, dict):
        return [], None
    data = listing.get("data") or {}
    pag = data.get("pagination") or {}
    pages = int(to_float(pag.get("num_pages")) or 1)
    offers = []
    for p in data.get("products") or []:
        a = p.get("attributes") or {}
        price = to_float(p.get("price"))
        retail = to_float(p.get("retail_price"))
        name = p.get("name")
        size = parse_size(name)
        imgs = p.get("productimage_set") or []
        offers.append(Offer(
            store=STORE,
            store_sku=str(p.get("sku") or p.get("pk")),
            name_ar=name,
            name_en=a.get("product_name") if isinstance(a.get("product_name"), str) else None,
            brand=a.get("brand"),
            barcodes=clean_barcodes(a.get("ean")) + [b for b in clean_barcodes(a.get("main_ean"))
                                                    if b not in clean_barcodes(a.get("ean"))],
            price=price,
            old_price=retail if retail and price and retail > price else None,
            in_stock=p.get("in_stock"),
            category=" / ".join(x for x in (a.get("level_1"), a.get("level_2"), a.get("level_3")) if x),
            url=f"{BASE}/ar-sa{p['absolute_url']}" if p.get("absolute_url") else None,
            image_url=imgs[0].get("image") if imgs and isinstance(imgs[0], dict) else None,
            size_value=size[0],
            size_unit=size[1],
        ))
    return offers, pages


def parse_product(html: str, url: Optional[str] = None) -> Optional[Offer]:
    lds = jsonld_products(html)
    if not lds:
        return None
    offer = offer_from_jsonld(STORE, lds[0], url)
    if offer.price is None:  # price is also printed in the page
        m = re.search(r'data-testid="price"[^>]*>\s*([\d.,]+)', html)
        offer.price = to_float(m.group(1)) if m else None
    if not offer.barcodes:
        m = re.search(r'data-loadbee-gtin="(\d+)"', html)
        offer.barcodes = clean_barcodes(m.group(1)) if m else []
    return offer


def is_grocery_category(path: str) -> bool:
    slug = path.strip("/").split("/")[-1]
    return slug.startswith(GROCERY_PREFIXES) and not any(w in slug for w in EXCLUDE_WORDS)


async def leaf_categories(f: Fetcher) -> list[str]:
    body = await f.get("/ar-sa/sitemap/categories-1") or ""
    paths = [unquote(u).replace(BASE, "") for u in re.findall(r"<loc>([^<]+)</loc>", body)]
    paths = [p for p in paths if is_grocery_category(p)]
    slugs = [p.strip("/").split("/")[-1] for p in paths]
    # keep leaves only: no other slug extends this one
    return [p for p, s in zip(paths, slugs) if not any(o != s and o.startswith(s + "-") for o in slugs)]


async def crawl(urls: Optional[list[str]] = None, limit: Optional[int] = None,
                concurrency: int = 3) -> AsyncIterator[Offer]:
    async with Fetcher(BASE, COOKIES, concurrency=concurrency) as f:
        if urls is not None:
            async def one(u):
                html = await f.get(u)
                return parse_product(html, u) if html else None
            for offer in await asyncio.gather(*(one(u) for u in urls[:limit] if u)):
                if offer:
                    yield offer
            return

        cats = await leaf_categories(f)
        log.info("lulu: %d grocery leaf categories", len(cats))
        seen: set[str] = set()
        count = 0
        for cat in cats:
            html = await f.get(cat)
            if not html:
                continue
            offers, pages = parse_listing(html)
            if pages and pages > 1:
                rest = await asyncio.gather(*(f.get(f"{cat}?page={n}") for n in range(2, pages + 1)))
                for h in rest:
                    if h:
                        offers += parse_listing(h)[0]
            for o in offers:
                if o.store_sku in seen:
                    continue
                seen.add(o.store_sku)
                yield o
                count += 1
                if limit and count >= limit:
                    return
