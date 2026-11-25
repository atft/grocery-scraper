"""Tamimi Markets (tamimimarkets.com)

How the data is reached (checked 2026-11-24):
- /sitemap.xml -> /sitemaps/products-0..N.xml list every product page.
- Each product page is server-rendered (Next.js). Its payload holds
  `"product":{barcode, product_id, product_name, product_name_ar, department,
  brand, in_stock, variant_name ...}` followed by
  `"pricing":{price, old_price, discount_percent}`.
- Branch is chosen with the `store_code` cookie. V131 = Olaya, Riyadh.
- Listing pages are filled in the browser by a search service, so we read
  product pages instead.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

from ..common import Offer, clean_barcodes, decode_next_flight, extract_json_after, parse_size, to_float
from ..http import Fetcher

log = logging.getLogger(__name__)

STORE = "tamimi"
BASE = "https://www.tamimimarkets.com"
COOKIES = {"store_code": "V131", "language": "ar"}  # Olaya, Riyadh

# Departments counted as groceries. Add "HOUSEHOLD" for cleaning products.
GROCERY_DEPARTMENTS = {"FRESH", "FOOD AND BEVERAGES", "HEALTHY LIVING"}


def parse_product(html: str, url: Optional[str] = None) -> Optional[Offer]:
    flight = decode_next_flight(html)
    product, end = extract_json_after(flight, '"product":')
    # the first '"product":' may be something else; find the one with a barcode/product_id
    pos = 0
    while product is not None and not (isinstance(product, dict) and "product_id" in product):
        pos = end
        product, end = extract_json_after(flight, '"product":', pos)
    if not isinstance(product, dict):
        return None
    pricing, _ = extract_json_after(flight, '"pricing":', end)
    pricing = pricing if isinstance(pricing, dict) else {}

    price = to_float(pricing.get("price"))
    old = to_float(pricing.get("old_price"))
    name_ar = product.get("product_name_ar")
    name_en = product.get("product_name")
    variant = product.get("variant_name") or ""
    size = parse_size(variant) if variant else parse_size(name_en)
    if size == (None, None):
        size = parse_size(name_ar)

    image = None
    # first product image after the pricing block belongs to this product's variants
    m = re.compile(r'https://ecommedia\.tamimimarkets\.com/[^"\\]+productimages/[^"\\]+').search(flight, end)
    if m:
        image = m.group(0)

    return Offer(
        store=STORE,
        store_sku=str(product.get("variant_id") or product.get("product_id")),
        name_ar=f"{name_ar} {variant}".strip() if name_ar else None,
        name_en=f"{name_en} {variant}".strip() if name_en else None,
        brand=product.get("brand"),
        barcodes=clean_barcodes(product.get("barcode")),
        price=price,
        old_price=old if old and price and old > price else None,
        in_stock=product.get("in_stock"),
        category=" / ".join(
            x for x in (product.get("department"), product.get("parent_category"), product.get("category")) if x
        ),
        url=url,
        image_url=image,
        size_value=size[0],
        size_unit=size[1],
    )


def is_grocery(offer: Offer) -> bool:
    dept = (offer.category or "").split(" / ")[0].upper()
    return dept in GROCERY_DEPARTMENTS


async def product_urls(f: Fetcher) -> list[str]:
    index = await f.get("/sitemap.xml") or ""
    maps = re.findall(r"<loc>([^<]*sitemaps/products-\d+\.xml)</loc>", index)
    urls: list[str] = []
    for sm in maps:
        body = await f.get(sm) or ""
        urls += re.findall(r"<loc>([^<]*/products/[^<]+)</loc>", body)
    return list(dict.fromkeys(urls))


async def crawl(urls: Optional[list[str]] = None, limit: Optional[int] = None,
                concurrency: int = 4) -> AsyncIterator[Offer]:
    """Full crawl when `urls` is None, otherwise refresh just these pages."""
    import asyncio

    async with Fetcher(BASE, COOKIES, concurrency=concurrency) as f:
        if urls is None:
            urls = await product_urls(f)
            log.info("tamimi: %d product urls in sitemap", len(urls))
        if limit:
            urls = urls[:limit]

        async def one(u):
            html = await f.get(u)
            return parse_product(html, u) if html else None

        for batch_start in range(0, len(urls), 50):
            batch = urls[batch_start: batch_start + 50]
            for offer in await asyncio.gather(*(one(u) for u in batch)):
                if offer and is_grocery(offer):
                    yield offer
