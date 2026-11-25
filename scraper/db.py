"""Thin Supabase (PostgREST) client: batch ingest + matching helpers.

Needs env vars SUPABASE_URL and SUPABASE_SERVICE_KEY (service_role key, kept
in GitHub Secrets — never in the frontend)."""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable, Optional

import httpx

from .common import Offer

log = logging.getLogger(__name__)


class Supabase:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        url = url or os.environ["SUPABASE_URL"]
        key = key or os.environ["SUPABASE_SERVICE_KEY"]
        self.client = httpx.Client(
            base_url=url.rstrip("/") + "/rest/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            timeout=120,
        )

    def rpc(self, fn: str, args: dict):
        r = self.client.post(f"/rpc/{fn}", content=json.dumps(args, ensure_ascii=False))
        r.raise_for_status()
        return r.json() if r.content else None

    def ingest(self, offers: Iterable[Offer], quick: bool = False, batch_size: int = 300) -> dict:
        totals = {"new": 0, "changed": 0, "linked": 0, "sent": 0}
        batch: list[dict] = []

        def flush():
            if not batch:
                return
            res = self.rpc("ingest_offers", {"payload": batch, "quick": quick}) or {}
            for k in ("new", "changed", "linked"):
                totals[k] += res.get(k, 0)
            totals["sent"] += len(batch)
            batch.clear()

        for o in offers:
            if o.price is None:
                continue
            batch.append(o.to_dict())
            if len(batch) >= batch_size:
                flush()
        flush()
        return totals

    def select(self, table: str, params: dict) -> list[dict]:
        r = self.client.get(f"/{table}", params=params)
        r.raise_for_status()
        return r.json()

    def watched_urls(self, max_rows: int = 3000) -> dict[str, list[str]]:
        rows = self.rpc("watched_offers", {"max_rows": max_rows}) or []
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["store_id"], []).append(r["url"])
        return out

    def unmatched(self, store: Optional[str] = None, limit: int = 1000) -> list[dict]:
        params = {"select": "id,store_id,name_ar,brand,size_value,size_unit",
                  "product_id": "is.null", "order": "id", "limit": str(limit)}
        if store:
            params["store_id"] = f"eq.{store}"
        return self.select("store_products", params)

    def candidates(self, sp_id: int) -> list[dict]:
        return self.rpc("match_candidates", {"sp_id": sp_id, "max_results": 5}) or []

    def link(self, sp_id: int, product_id: Optional[int], method: str = "name") -> int:
        return self.rpc("link_store_product",
                        {"sp_id": sp_id, "target_product": product_id, "method": method})
