"""Entry point.

  python -m scraper.run full   --stores tamimi,panda,lulu,danube
  python -m scraper.run quick                      # hourly: watched items only
  python -m scraper.run full --stores panda --limit 50 --dry-run   # test, no DB

--dry-run writes JSON lines to out/<store>.jsonl instead of Supabase.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

from .stores import danube, lulu, panda, tamimi

STORES = {"tamimi": tamimi, "panda": panda, "lulu": lulu, "danube": danube}
log = logging.getLogger("scraper")


async def collect(store: str, urls=None, limit=None) -> list:
    mod = STORES[store]
    out = []
    try:
        async for offer in mod.crawl(urls=urls, limit=limit):
            out.append(offer)
    except Exception:
        log.exception("%s crawl failed", store)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["full", "quick", "match"])
    ap.add_argument("--stores", default="tamimi,panda,lulu,danube")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-expected", type=int, default=50,
                    help="warn (exit 2) if a full crawl returns fewer offers than this")
    a = ap.parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stores = [s.strip() for s in a.stores.split(",") if s.strip()]

    db = None
    if not a.dry_run:
        from .db import Supabase
        db = Supabase()

    if a.mode == "match":
        from .matching import match_unlinked
        print(json.dumps(match_unlinked(db, None, limit=20000), ensure_ascii=False))
        return 0

    watched = db.watched_urls() if (a.mode == "quick" and db) else {}
    status = 0
    for store in stores:
        t0 = time.time()
        urls = None
        if a.mode == "quick":
            urls = watched.get(store, [])
            if not urls:
                log.info("%s: nothing to refresh", store)
                continue
        offers = asyncio.run(collect(store, urls, a.limit))
        took = round(time.time() - t0)
        log.info("%s: %d offers in %ss", store, len(offers), took)

        if a.mode == "full" and not a.limit and len(offers) < a.min_expected:
            # the site probably changed its layout or blocked us — flag the run
            log.error("%s returned only %d offers – check the site / parser", store, len(offers))
            status = 2

        if a.dry_run:
            Path("out").mkdir(exist_ok=True)
            with open(f"out/{store}.jsonl", "w", encoding="utf-8") as fh:
                for o in offers:
                    fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")
        else:
            res = db.ingest(offers, quick=(a.mode == "quick"))
            log.info("%s ingest: %s", store, res)

    # Name matching for items without a usable barcode runs as its own step
    # (`python -m scraper.run match`) after all stores finish, so parallel
    # store jobs don't race each other.
    return status


if __name__ == "__main__":
    sys.exit(main())
