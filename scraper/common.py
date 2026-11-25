"""Shared helpers: data model, Next.js payload decoding, number/size parsing.

Everything here is standard-library only so it can be unit-tested anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Offer:
    """One product as sold by one store (one row in `store_products`)."""

    store: str                      # tamimi | panda | lulu | danube
    store_sku: str                  # the store's own id for the item
    name_ar: Optional[str]
    name_en: Optional[str] = None
    brand: Optional[str] = None
    barcodes: list[str] = field(default_factory=list)
    price: Optional[float] = None   # what the customer pays now
    old_price: Optional[float] = None  # price before discount (None if no offer)
    in_stock: Optional[bool] = None
    category: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    size_value: Optional[float] = None  # normalised: grams / millilitres / pieces
    size_unit: Optional[str] = None     # g | ml | pc

    def to_dict(self) -> dict:
        d = asdict(self)
        d["unit_price"] = self.unit_price
        return d

    @property
    def unit_price(self) -> Optional[float]:
        """Price per kg / litre / piece, for fair comparison across pack sizes."""
        if not self.price or not self.size_value:
            return None
        if self.size_unit in ("g", "ml"):
            return round(self.price / self.size_value * 1000, 3)
        if self.size_unit == "pc":
            return round(self.price / self.size_value, 3)
        return None


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")


def normalize_digits(s: str) -> str:
    """Arabic-Indic digits and separators -> ASCII."""
    return s.translate(_AR_DIGITS)


def to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "$undefined":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = normalize_digits(str(v))
    s = re.sub(r"[^\d.,]", "", s).replace(",", "")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def clean_barcodes(raw) -> list[str]:
    """Accepts a string (possibly comma separated) or list; returns digit-only
    codes of plausible GTIN length, without leading zeros padding issues."""
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,\s;|]+", str(raw))
    out = []
    for item in items:
        code = re.sub(r"\D", "", str(item))
        if not 8 <= len(code) <= 14:
            continue
        norm = normalize_gtin(code)
        # GS1 prefix 2x = in-store / variable-weight codes: every chain reuses
        # them for different things, so they are useless for cross-store matching.
        if len(norm) in (12, 13) and norm.startswith("2"):
            continue
        out.append(norm)
    return list(dict.fromkeys(out))


def normalize_gtin(code: str) -> str:
    """Canonical form used for matching: GTIN-14 style zero padding removed so
    UPC-A (12) and EAN-13 with a leading 0 compare equal."""
    code = code.lstrip("0")
    return code.zfill(12)


# --------------------------------------------------------------------------
# Pack size parsing  (e.g. "زيت دوار الشمس 2 × 1.5 لتر" -> 3000 ml)
# --------------------------------------------------------------------------
_UNIT_MAP = {
    # weight -> grams
    "كجم": ("g", 1000), "كغ": ("g", 1000), "كغم": ("g", 1000), "كلغ": ("g", 1000), "كيلوغرام": ("g", 1000), "كيلو": ("g", 1000), "كيلوجرام": ("g", 1000),
    "كيلو جرام": ("g", 1000), "كيلوغرام": ("g", 1000), "kg": ("g", 1000), "kgs": ("g", 1000),
    "جم": ("g", 1), "جرام": ("g", 1), "غرام": ("g", 1), "غ": ("g", 1), "جم.": ("g", 1),
    "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1), "gr": ("g", 1), "grams": ("g", 1),
    # volume -> millilitres
    "لتر": ("ml", 1000), "ل": ("ml", 1000), "لترات": ("ml", 1000), "l": ("ml", 1000),
    "ltr": ("ml", 1000), "litre": ("ml", 1000), "liter": ("ml", 1000), "litres": ("ml", 1000),
    "مل": ("ml", 1), "مليلتر": ("ml", 1), "ml": ("ml", 1),
    "oz": ("g", 28.3495), "اونصة": ("g", 28.3495),
    # count
    "حبة": ("pc", 1), "حبات": ("pc", 1), "قطعة": ("pc", 1), "قطع": ("pc", 1),
    "بيضة": ("pc", 1), "كيس": ("pc", 1), "أكياس": ("pc", 1), "ظرف": ("pc", 1), "رول": ("pc", 1), "pcs": ("pc", 1), "pc": ("pc", 1), "pieces": ("pc", 1), "piece": ("pc", 1),
}
_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNIT_MAP), key=len, reverse=True))
_SIZE_RE = re.compile(
    rf"(?:(\d+)\s*[x×*]\s*)?(\d+(?:\.\d+)?)\s*({_UNIT_RE})(?![a-z؀-ۿ])",
    re.IGNORECASE,
)
_MULT_AFTER_RE = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT_RE})\s*[x×*]\s*(\d+)", re.IGNORECASE)


def parse_size(text: Optional[str], unit_hint: Optional[str] = None) -> tuple[Optional[float], Optional[str]]:
    """Return (value, unit) with unit in g|ml|pc, from free text like
    '2 × 1.5 لتر', '500ml', '30 pcs'. If `unit_hint` is given, `text` may be a
    bare number (Panda gives size and unit separately)."""
    if not text:
        return None, None
    t = normalize_digits(str(text)).lower().replace("،", ",")
    if unit_hint:
        t = f"{t} {normalize_digits(unit_hint).lower()}"
    m = _MULT_AFTER_RE.search(t)
    if m:
        qty, unit, mult = float(m.group(1)), m.group(2), float(m.group(3))
        base, factor = _UNIT_MAP[unit]
        return round(qty * factor * mult, 3), base
    best = None
    for m in _SIZE_RE.finditer(t):
        mult = float(m.group(1)) if m.group(1) else 1.0
        qty = float(m.group(2))
        base, factor = _UNIT_MAP[m.group(3)]
        best = (round(mult * qty * factor, 3), base)  # last match wins: sizes sit at the end
    return best if best else (None, None)


# --------------------------------------------------------------------------
# Next.js (App Router) flight payload decoding
# --------------------------------------------------------------------------
_NEXT_F_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)


def decode_next_flight(html: str) -> str:
    """Concatenate the JSON-string chunks that Next.js streams into the page.
    The result contains the server-side props as plain JSON fragments."""
    parts = []
    for m in _NEXT_F_RE.finditer(html):
        try:
            parts.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def extract_json_after(text: str, marker: str, start: int = 0) -> tuple[Optional[object], int]:
    """Find `marker` (which must end right before a JSON value, e.g. '"products":')
    and parse the balanced JSON object/array that follows it.
    Returns (value, end_index) or (None, -1)."""
    i = text.find(marker, start)
    if i < 0:
        return None, -1
    j = i + len(marker)
    while j < len(text) and text[j] in " \n\t":
        j += 1
    if j >= len(text) or text[j] not in "[{":
        return None, -1
    open_c = text[j]
    close_c = "]" if open_c == "[" else "}"
    depth, k, in_str = 0, j, False
    while k < len(text):
        c = text[k]
        if in_str:
            if c == "\\":
                k += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[j : k + 1]), k + 1
                except json.JSONDecodeError:
                    return None, -1
        k += 1
    return None, -1


def iter_json_after(text: str, marker: str) -> Iterable[object]:
    pos = 0
    while True:
        val, end = extract_json_after(text, marker, pos)
        if end < 0:
            i = text.find(marker, pos)
            if i < 0:
                return
            pos = i + len(marker)
            continue
        yield val
        pos = end


# --------------------------------------------------------------------------
# schema.org JSON-LD (used by Panda, Lulu, Danube product pages)
# --------------------------------------------------------------------------
_LD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def jsonld_products(html: str) -> list[dict]:
    out = []
    for m in _LD_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        for d in stack:
            if isinstance(d, dict) and d.get("@type") == "Product":
                out.append(d)
            elif isinstance(d, dict) and isinstance(d.get("@graph"), list):
                out.extend(x for x in d["@graph"] if isinstance(x, dict) and x.get("@type") == "Product")
    return out


def offer_from_jsonld(store: str, d: dict, url: Optional[str] = None) -> Offer:
    offers = d.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    brand = d.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    image = d.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    name = d.get("name")
    size = parse_size(name)
    avail = str(offers.get("availability", ""))
    return Offer(
        store=store,
        store_sku=str(d.get("sku") or d.get("productID") or url or name),
        name_ar=name,
        brand=brand,
        barcodes=clean_barcodes(d.get("gtin13") or d.get("gtin") or d.get("gtin12") or d.get("gtin14")),
        price=to_float(offers.get("price")),
        in_stock=("InStock" in avail) if avail else None,
        category=d.get("category"),
        url=offers.get("url") or url,
        image_url=image,
        size_value=size[0],
        size_unit=size[1],
    )
