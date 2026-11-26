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

    def _send(self, method: str, url: str, **kw):
        """Retry temporary failures (5xx, timeouts) – the free Supabase tier
        is a small machine and occasionally cancels a slow query."""
        import time
        for attempt in range(4):
            try:
                r = self.client.request(method, url, **kw)
                if r.status_code < 500 or attempt == 3:
                    return r
                log.warning("%s %s -> HTTP %s, retrying: %s", method, url.split("?")[0], r.status_code, r.text[:200])
            except httpx.TransportError as e:
                if attempt == 3:
                    raise
                log.warning("%s %s failed (%s), retrying", method, url.split("?")[0], e)
            time.sleep(5 * (attempt + 1) ** 2)  # 5s, 20s, 45s

    def rpc(self, fn: str, args: dict):
        r = self._send("POST", f"/rpc/{fn}", content=json.dumps(args, ensure_ascii=False))
        if r.status_code >= 400:
            # PostgREST puts the real database error in the body – show it
            raise RuntimeError(f"{fn} -> HTTP {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    def ingest(self, offers: Iterable[Offer], quick: bool = False, batch_size: int = 300) -> dict:
        totals = {"new": 0, "changed": 0, "linked": 0, "errors": 0, "sent": 0}
        batch: list[dict] = []

        def send(rows: list[dict]):
            """Send rows; if the database rejects the whole call, split it in
            halves until the bad row is isolated, log it and skip it."""
            try:
                res = self.rpc("ingest_offers", {"payload": rows, "quick": quick}) or {}
            except Exception as e:
                if len(rows) == 1:
                    log.error("skipped %s/%s (%s): %s", rows[0].get("store"), rows[0].get("store_sku"),
                              rows[0].get("name_ar"), e)
                    totals["errors"] += 1
                    return
                log.warning("batch of %d rejected, splitting: %s", len(rows), e)
                mid = len(rows) // 2
                send(rows[:mid])
                send(rows[mid:])
                return
            for k in ("new", "changed", "linked", "errors"):
                totals[k] += res.get(k, 0)
            for sample in res.get("error_samples") or []:
                log.error("row skipped by database: %s", json.dumps(sample, ensure_ascii=False))
            totals["sent"] += len(rows)

        for o in offers:
            if o.price is None:
                continue
            batch.append(o.to_dict())
            if len(batch) >= batch_size:
                send(batch)
                batch = []
        if batch:
            send(batch)
        return totals

    def select(self, table: str, params: dict) -> list[dict]:
        r = self._send("GET", f"/{table}", params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {table} -> HTTP {r.status_code}: {r.text[:500]}")
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
