import asyncio

import pytest

from scraper.common import clean_barcodes, normalize_digits, parse_size, to_float, Offer
from scraper.matching import name_score, tokens, decide
from scraper.stores import danube, lulu, panda, tamimi
from tests import fixtures as fx


# ------------------------------------------------------------------ helpers
@pytest.mark.parametrize("text,unit_hint,expected", [
    ("نور زيت دوار الشمس 2×1.5 لتر", None, (3000.0, "ml")),
    ("نور زيت دوار الشمس 2 × 1.5 لتر", None, (3000.0, "ml")),
    ("المراعي سمن الزبدة النقية عبوة اقتصادية 2 × 400 جم", None, (800.0, "g")),
    ("عافية زيت دوار الشمس 2.9 لتر", None, (2900.0, "ml")),
    ("أمريكان جاردن صلصة سلطة رانش ٢٦٧مل", None, (267.0, "ml")),
    ("باونتي ١٥٠غرام", None, (150.0, "g")),
    ("Eggs Large 30 pcs", None, (30.0, "pc")),
    ("Olive Oil 250ml", None, (250.0, "ml")),
    ("رز بسمتي 5 كجم", None, (5000.0, "g")),
    ("135", "جرام", (135.0, "g")),
    ("1.5", "لتر", (1500.0, "ml")),
    ("كيس 500 جم × 3", None, (1500.0, "g")),
    ("خبز عربي", None, (None, None)),
])
def test_parse_size(text, unit_hint, expected):
    assert parse_size(text, unit_hint) == expected


def test_numbers():
    assert normalize_digits("١٦٫٥٠") == "16.50"
    assert to_float("‏١٠٫٥٠\xa0‏") == 10.5
    assert to_float("45.850") == 45.85
    assert to_float("$undefined") is None


def test_barcodes():
    assert clean_barcodes("6281007053099,6281583005659") == ["6281007053099", "6281583005659"]
    # UPC-A and the same code written as EAN-13 with leading 0 compare equal
    assert clean_barcodes("0717273504640") == clean_barcodes("717273504640")
    # in-store / weighed codes (prefix 2) are dropped
    assert clean_barcodes("2503380000000") == []
    assert clean_barcodes(None) == [] and clean_barcodes("abc") == []


def test_unit_price():
    o = Offer(store="x", store_sku="1", name_ar="t", price=45.85, size_value=2900, size_unit="ml")
    assert o.unit_price == pytest.approx(15.81, abs=0.01)
    assert Offer(store="x", store_sku="1", name_ar="t", price=17.99, size_value=30, size_unit="pc").unit_price \
        == pytest.approx(0.6, abs=0.01)


# ------------------------------------------------------------------ Tamimi
def test_tamimi_product():
    o = tamimi.parse_product(fx.TAMIMI_HTML, "https://www.tamimimarkets.com/products/olive-oil-250ml-310472")
    assert o.store_sku == "310472EA"
    assert o.barcodes == ["6281100044017"]
    assert o.name_ar == "زيت زيتون 250ml" and o.name_en == "Olive Oil 250ml"
    assert o.price == 21.95 and o.old_price is None
    assert (o.size_value, o.size_unit) == (250.0, "ml")
    assert o.brand == "Al Jouf" and o.in_stock is True
    assert o.image_url.endswith("310472EA_1.png")
    assert tamimi.is_grocery(o)


def test_tamimi_discount_and_filter():
    eggs = tamimi.parse_product(fx.TAMIMI_EGGS_HTML)
    assert eggs.price == 17.99 and eggs.old_price == 22.5
    assert (eggs.size_value, eggs.size_unit) == (30.0, "pc")
    assert tamimi.is_grocery(eggs)
    assert not tamimi.is_grocery(tamimi.parse_product(fx.TAMIMI_TOBACCO_HTML))


def test_tamimi_garbage():
    assert tamimi.parse_product("<html>nothing</html>") is None


# ------------------------------------------------------------------ Panda
def test_panda_listing():
    offers, pages = panda.parse_listing(fx.PANDA_LISTING_HTML, "cooking-essentials-467",
                                        {"15200": "https://panda.sa/ar/p/panda-tomato-paste-15200"})
    assert pages == 54 and len(offers) == 3
    paste, ranch, tahina = offers
    assert paste.price == 10 and paste.old_price == 13.99
    assert paste.size_value == 135 and paste.size_unit == "g"
    assert paste.url == "https://panda.sa/ar/p/panda-tomato-paste-15200"
    assert ranch.old_price is None and ranch.barcodes == ["717273504640"]
    assert ranch.size_value == 267 and ranch.size_unit == "ml"
    assert tahina.barcodes == [] and tahina.in_stock is False


def test_panda_product_jsonld():
    o = panda.parse_product(fx.PANDA_PRODUCT_HTML)
    assert o.store_sku == "2380205" and o.price == 40.99 and o.in_stock
    assert o.barcodes == ["4015400245940"] and o.brand == "Always"


# ------------------------------------------------------------------ Lulu
def test_lulu_listing():
    offers, pages = lulu.parse_listing(fx.LULU_LISTING_HTML)
    assert pages == 5 and len(offers) == 3
    afia, olive, ghee = offers
    assert afia.price == 45.85 and afia.old_price is None
    assert afia.size_value == 2900 and afia.unit_price == pytest.approx(15.81, abs=0.01)
    assert afia.url.startswith("https://gcc.luluhypermarket.com/ar-sa/afia-")
    assert afia.image_url.endswith("a.jpg")
    assert olive.price == 30.4 and olive.old_price == 38.6
    assert ghee.barcodes == ["6281007053099", "6281583005659"] and ghee.size_value == 800


def test_lulu_categories():
    keep = [p for p in fx.LULU_SITEMAP_PATHS if lulu.is_grocery_category(p)]
    assert "/ar-sa/grocery-household-air-fresheners-candles-incense/" not in keep
    assert "/ar-sa/electronics-mobiles/" not in keep
    assert "/ar-sa/grocery-food-cupboard-cooking-ingredients-oils-ghee/" in keep

    class FakeFetcher:
        async def get(self, url):
            return "".join(f"<loc>https://gcc.luluhypermarket.com{p}</loc>" for p in fx.LULU_SITEMAP_PATHS)

    leaves = asyncio.run(lulu.leaf_categories(FakeFetcher()))
    assert leaves == [
        "/ar-sa/grocery-food-cupboard-cooking-ingredients-oils-ghee/",
        "/ar-sa/grocery-food-cupboard-cooking-ingredients-pulses/",
        "/ar-sa/fresh-fruits-vegetables-fruits/",
    ]


# ------------------------------------------------------------------ Danube
def test_danube_cards():
    offers = danube.parse_cards(fx.DANUBE_CARDS_HTML, "sweets-snacks")
    assert len(offers) == 2
    bounty, oil = offers
    assert bounty.store_sku == "bounty-miniatures-150g"
    assert bounty.price == 10.5 and bounty.old_price == 16.5
    assert bounty.size_value == 150 and bounty.size_unit == "g"
    assert bounty.image_url.startswith("https://d1c124wpoew66.cloudfront.net/")
    assert bounty.in_stock is True
    assert oil.price == 21.95 and oil.old_price is None and oil.size_value == 1500
    assert danube.last_page(fx.DANUBE_CARDS_HTML) == 7


def test_danube_product_page_same_sku_as_card():
    o = danube.parse_product(fx.DANUBE_PRODUCT_HTML, "https://danube.sa/products/bounty-miniatures-150g")
    assert o.store_sku == "bounty-miniatures-150g"  # same id as on the card -> updates the same row
    assert o.price == 10.5 and o.old_price == 16.5


# ------------------------------------------------------------------ matching
def test_arabic_normalisation():
    assert tokens("الزيـت  النباتي ١٫٥ لتر") == tokens("زيت النباتى 1.5 ل") == ["زيت", "نباتي"]


def test_name_matching():
    same = name_score("نور زيت دوار الشمس ١٫٥ لتر", "نور زيت دوار الشمس 1.5 لتر")
    other = name_score("نور زيت دوار الشمس ١٫٥ لتر", "عافية زيت ذرة 1.5 لتر")
    assert same > 0.9 and other < 0.55

    item = {"name_ar": "نور زيت دوار الشمس ١٫٥ لتر", "size_unit": "ml"}
    cands = [{"product_id": 7, "name_ar": "نور زيت دوار الشمس 1.5 لتر", "size_value": 1500},
             {"product_id": 8, "name_ar": "نور زيت دوار الشمس 1.8 لتر", "size_value": 1800}]
    assert decide(item, cands) == (7, "name")
    # different size must never match even with an identical name
    assert decide(item, cands[1:]) == (None, "own")
