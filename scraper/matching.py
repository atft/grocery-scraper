"""Match items that have no barcode (Danube) to unified products by name.

Step 1  candidates from Postgres (pg_trgm similarity, same unit, size ±2%).
Step 2  score in Python after Arabic normalisation (brand + size aware).
Step 3  grey zone -> optional Gemini yes/no (GEMINI_API_KEY). Otherwise the
        item gets its own product so it still shows up in search.
"""
from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Optional

from .common import normalize_digits, parse_size

log = logging.getLogger(__name__)

ACCEPT = 0.72     # link automatically (both sizes known and equal)
ACCEPT_NO_SIZE = 0.85  # stricter when a pack size is missing
GREY = 0.55       # ask Gemini between GREY and ACCEPT

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_STOP = {"من", "مع", "و", "في", "ال", "عبوة", "عبوه", "حجم", "اقتصادي", "اقتصادية",
         "جديد", "طازج", "pack", "of", "the", "and", "with", "x", "×"}
_UNIT_WORDS = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:كجم|كغ|كيلو|جم|جرام|غرام|غ|لتر|ل|مل|حبة|حبات|قطعة|قطع|kg|g|gm|ml|l|ltr|pcs|pc)\b",
    re.I)


def normalize_ar(text: Optional[str]) -> str:
    if not text:
        return ""
    t = normalize_digits(text).lower()
    t = _DIACRITICS.sub("", t)
    t = re.sub("[إأآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = _UNIT_WORDS.sub(" ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


_PREFIXES = ("وال", "بال", "لل", "ال", "و", "ب")


def _stem(w: str) -> str:
    """Strip attached و / ب / ال (e.g. والكرز -> كرز, بالزبده -> زبده)."""
    for p in _PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    return w


def tokens(text: Optional[str]) -> list[str]:
    out = []
    for w in normalize_ar(text).split():
        w = _stem(w)
        if w in _STOP or w.isdigit() or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
    return out


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True  # شوكو / شوكولاته
    return len(a) >= 4 and len(b) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.8  # امريكانا / اميركانا


def _matched(ta: list[str], tb: list[str]) -> int:
    used, m = set(), 0
    for a in ta:
        for j, b in enumerate(tb):
            if j not in used and _same_word(a, b):
                used.add(j)
                m += 1
                break
    return m


def name_score(a: str, b: str) -> float:
    """F1 of fuzzily-matched words (0..1); 0 when the brands clearly differ.
    The brand is the first word in almost every listing here."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    brand_ok = any(_same_word(ta[0], x) for x in tb) or any(_same_word(tb[0], x) for x in ta)
    if not brand_ok:
        return 0.0
    m = _matched(ta, tb)
    return round(2 * m / (len(ta) + len(tb)), 3)


def same_size(a_name: str, b_val, b_unit) -> Optional[bool]:
    va, ua = parse_size(a_name)
    if va is None or b_val is None:
        return None
    if ua != b_unit:
        return False
    return abs(float(va) - float(b_val)) <= max(float(va), float(b_val)) * 0.02


def gemini_same_product(a: str, b: str) -> Optional[bool]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    import httpx

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = (
        "Are these two supermarket listings the exact same product (same brand, same variant, "
        "same pack size)? Answer only YES or NO.\n"
        f"A: {a}\nB: {b}"
    )
    try:
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0, "maxOutputTokens": 5}},
            timeout=30,
        )
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
        return text.startswith("YES")
    except Exception as e:  # never let matching break the run
        log.info("gemini check failed: %s", e)
        return None


def decide(item: dict, candidates: list[dict]) -> tuple[Optional[int], str]:
    """Return (product_id or None, method)."""
    best, best_score, best_sized = None, 0.0, False
    for c in candidates:
        size_ok = same_size(item.get("name_ar", ""), c.get("size_value"), item.get("size_unit"))
        if size_ok is False:
            continue  # different pack size is never the same product
        sc = name_score(item.get("name_ar", ""), c.get("name_ar", ""))
        if sc > best_score:
            best, best_score, best_sized = c, sc, bool(size_ok)
    if not best:
        return None, "own"
    if best_score >= (ACCEPT if best_sized else ACCEPT_NO_SIZE):
        return best["product_id"], "name"
    if best_score >= GREY:
        verdict = gemini_same_product(item.get("name_ar", ""), best.get("name_ar", ""))
        if verdict:
            return best["product_id"], "gemini"
    return None, "own"


def match_unlinked(db, store: Optional[str] = None, limit: int = 50000,
                   workers: int = 6, batch: int = 1000) -> dict:
    """Link every item that has no product yet. Supabase returns at most
    1000 rows per request, so we work in batches until none are left."""
    from concurrent.futures import ThreadPoolExecutor

    stats = {"name": 0, "gemini": 0, "own": 0, "errors": 0}
    done: set = set()

    def handle(item):
        try:
            pid, method = decide(item, db.candidates(item["id"]))
            db.link(item["id"], pid, method)
            return method
        except Exception as e:  # one bad item must not stop the run
            log.info("match failed for %s: %s", item.get("id"), e)
            return "errors"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while sum(stats.values()) < limit:
            items = [i for i in db.unmatched(store, min(batch, limit - sum(stats.values())))
                     if i["id"] not in done]
            if not items:
                break  # nothing left (or only items that keep failing)
            done.update(i["id"] for i in items)
            for method in pool.map(handle, items):
                stats[method] += 1
            log.info("matching progress: %s", stats)
    return stats


if __name__ == "__main__":  # quick manual check
    print(json.dumps({
        "score": name_score("عافية زيت دوار الشمس 1.5 لتر", "عافية زيت دوار الشمس ١٫٥ لتر"),
    }, ensure_ascii=False))
