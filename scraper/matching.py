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

ACCEPT = 0.78     # link automatically
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
    words = [w[2:] if w.startswith("ال") and len(w) > 4 else w for w in t.split()]
    return " ".join(w for w in words if w not in _STOP and not w.isdigit())


def name_score(a: str, b: str) -> float:
    na, nb = normalize_ar(a), normalize_ar(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jacc = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return round(0.6 * jacc + 0.4 * seq, 3)


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
    best, best_score = None, 0.0
    for c in candidates:
        s = name_score(item.get("name_ar", ""), c.get("name_ar", ""))
        size_ok = same_size(item.get("name_ar", ""), c.get("size_value"), item.get("size_unit"))
        if size_ok is False:
            continue
        if size_ok:
            s += 0.05
        if s > best_score:
            best, best_score = c, s
    if best and best_score >= ACCEPT:
        return best["product_id"], "name"
    if best and best_score >= GREY:
        verdict = gemini_same_product(item.get("name_ar", ""), best.get("name_ar", ""))
        if verdict:
            return best["product_id"], "gemini"
    return None, "own"


def match_unlinked(db, store: Optional[str] = None, limit: int = 2000) -> dict:
    stats = {"name": 0, "gemini": 0, "own": 0}
    for item in db.unmatched(store, limit):
        pid, method = decide(item, db.candidates(item["id"]))
        db.link(item["id"], pid, method)
        stats[method] += 1
    return stats


if __name__ == "__main__":  # quick manual check
    print(json.dumps({
        "score": name_score("عافية زيت دوار الشمس 1.5 لتر", "زيت دوار الشمس عافية ١٫٥ لتر"),
    }, ensure_ascii=False))
