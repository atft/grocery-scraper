"""Page fixtures rebuilt from real payloads captured on 2026-11-24.

Next.js pages stream their data as `self.__next_f.push([1,"<json string>"])`
chunks; we reproduce that encoding (including a split across two chunks)."""
import json


def next_page(*fragments: str) -> str:
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(f, ensure_ascii=False)}])</script>"
                     for f in fragments)
    return f"<!DOCTYPE html><html><head></head><body>{pushes}</body></html>"


# ---------------------------------------------------------------- Tamimi
TAMIMI_PRODUCT = {
    "barcode": "6281100044017", "product_id": "310472", "product_name": "Olive Oil",
    "product_name_ar": "زيت زيتون", "article_number": "310472", "department": "HEALTHY LIVING",
    "parent_category": "ORGANIC FOOD", "category": None, "sub_category": None, "brand": "Al Jouf",
    "brand_id": 34902, "brand_code": None, "image_url": None, "product_url": "/products/olive-oil-310472",
    "in_stock": True, "stock_count": 44, "rating": 0, "review_count": 0, "variant_id": "310472EA",
    "variant_name": "250ml", "uom": "EA",
    "tags": [{"id": 106, "tagNameEn": "Healthy Living", "tagNameAr": "حياة صحية"}],
}
_tamimi_flight = (
    '1:["$","nav",null,{"categories":[{"id":"TM1","name":"Fresh","nameAr":"طازج",'
    '"icon":"https://ecommedia.tamimimarkets.com/ecom-prod/categories/departments/fresh.svg"}]}]\n'
    '2:["$","$L7f",null,{"product":' + json.dumps(TAMIMI_PRODUCT, ensure_ascii=False)
    + ',"pricing":{"price":21.95,"currency":"SAR","old_price":null,"discount_percent":"$undefined"}}],'
    '["$","$L82",null,{"variants":[{"variantId":"310472EA","href":"/products/olive-oil-250ml-310472",'
    '"label":"250ml","price":21.95,"oldPrice":null,"inStock":true,'
    '"images":["https://ecommedia.tamimimarkets.com/ecom-prod/productimages/310472EA_1.png"]}]}]'
)
_cut = len(_tamimi_flight) // 2
TAMIMI_HTML = next_page(_tamimi_flight[:_cut], _tamimi_flight[_cut:])

TAMIMI_EGGS_HTML = next_page(
    '2:["$","$L7f",null,{"product":{"barcode":"6281062351765","product_id":"211503",'
    '"product_name":"Eggs Large","product_name_ar":"بيض كبير","department":"FRESH",'
    '"parent_category":"EGGS","brand":"Al Watania","in_stock":true,"variant_id":"211503EA",'
    '"variant_name":"30 pcs"},"pricing":{"price":17.99,"currency":"SAR","old_price":22.5,'
    '"discount_percent":20.04}}]'
)

TAMIMI_TOBACCO_HTML = next_page(
    '2:["$","$L7f",null,{"product":{"barcode":"6290000000001","product_id":"9","product_name":"X",'
    '"product_name_ar":"س","department":"TOBACCO AND NICOTINE","variant_id":"9EA","variant_name":"1 pcs"},'
    '"pricing":{"price":20,"currency":"SAR","old_price":null}}]'
)

# ---------------------------------------------------------------- Panda
PANDA_PRODUCTS = [
    {"id": 15200, "brand_id": 1569, "category_id": 371, "name": "بندة معجون طماطم 8 حبات 135 جرام",
     "brand": {"id": 1569, "name": "بنده", "imageURL": None},
     "category": {"id": 371, "name": "الصوصات والتتبيلات", "parent": 467},
     "varieties": [{"id": 24317, "price": "10", "undiscounted_price": "13.99", "show_discount": True,
                    "size": "135", "unit": "جرام", "wighted": False, "barcode": "449998020410",
                    "sku": 999802041, "availability": 1,
                    "imageURL": "https://images.todoorstep.com/product/999802041/Ar_small.jpg"}]},
    {"id": 47273, "brand_id": 762, "category_id": 371, "name": "أمريكان جاردن صلصة سلطة رانش ٢٦٧مل",
     "brand": {"id": 762, "name": "أميريكان جاردن", "imageURL": None},
     "category": {"id": 371, "name": "الصوصات والتتبيلات", "parent": 467},
     "varieties": [{"id": 53139, "price": "14.99", "undiscounted_price": None, "show_discount": False,
                    "size": "267", "unit": "مل", "wighted": False, "barcode": "717273504640",
                    "sku": 100248032, "availability": 1}]},
    {"id": 140000, "name": "مزار النخيل طحينة سمسم 250 جرام", "brand": {"name": "مزار النخيل"},
     "category": {"id": 371, "name": "الصوصات والتتبيلات"},
     "varieties": [{"id": 140825, "price": "17.99", "undiscounted_price": None, "size": "250",
                    "unit": "جرام", "wighted": False, "barcode": "2503380000000", "sku": 143900321,
                    "availability": 0}]},
]
PANDA_LISTING_HTML = next_page(
    '3:["$","$L9",null,{"menu":{"products":[],"recent":{"products":[{"id":1,"title":"x"}]}}}]\n'
    '5:["$","$L20",null,{"item_list_name":"x","item_list_id":"15200, 47273","products":'
    + json.dumps(PANDA_PRODUCTS, ensure_ascii=False) + ',"totalPages":54}]'
)
PANDA_PRODUCT_HTML = (
    '<html><head><script type="application/ld+json">'
    + json.dumps({
        "@context": "https://schema.org", "@type": "Product",
        "name": "أولويز فوط صحية بالصبار ماكسي سميكة 50 فوطة", "sku": "2380205", "gtin": "4015400245940",
        "brand": {"@type": "Brand", "name": "Always"}, "category": "Female Personal Care",
        "offers": {"@type": "Offer",
                   "url": "https://panda.sa/ar/p/always-sanitary-pads-15290",
                   "priceCurrency": "SAR", "price": "40.99",
                   "availability": "https://schema.org/InStock"}}, ensure_ascii=False)
    + "</script></head><body></body></html>"
)

# ---------------------------------------------------------------- Lulu
LULU_PRODUCTS = [
    {"pk": "23364", "name": "عافية زيت دوار الشمس نقي غني بفيتامينات أ د والزنك 2.9 لتر", "sku": "1671737",
     "attributes": {"ean": "6281011701894", "brand": "Afia", "level_1": "Grocery",
                    "level_2": "Food Cupboard", "level_3": "Cooking Ingredients"},
     "productimage_set": [{"pk": 1, "image": "https://bf1af2.akinoncloudcdn.com/products/a.jpg"}],
     "price": "45.850", "in_stock": True, "retail_price": "45.850",
     "absolute_url": "/afia-pure-sunflower-oil-enriched-with-vitamins-a-d-zinc-29-litres/p/1671737/"},
    {"pk": "17563", "name": "المراعي زيت زيتون بكر ممتاز 500 مل", "sku": "1064226",
     "attributes": {"ean": "6281007033114", "brand": "Almarai", "level_1": "Grocery"},
     "price": "30.400", "in_stock": True, "retail_price": "38.600",
     "absolute_url": "/almarai-extra-virgin-olive-oil-500-ml/p/1064226/"},
    {"pk": "26257", "name": "المراعي سمن الزبدة النقية عبوة اقتصادية 2 × 400 جم", "sku": "1295293",
     "attributes": {"ean": "6281007053099,6281583005659", "brand": "Almarai", "level_1": "Grocery"},
     "price": "60.700", "in_stock": True, "retail_price": "60.700",
     "absolute_url": "/almarai-pure-butter-ghee-2-400-g/p/1295293/"},
]
LULU_LISTING_HTML = next_page(
    '52:["$","$L6e",null,{"listing":{"data":{"pagination":{"current_page":"1","num_pages":"5",'
    '"page_size":"50","total_count":"203"},"facets":[],"products":'
    + json.dumps(LULU_PRODUCTS, ensure_ascii=False) + '}}}]'
)
LULU_SITEMAP_PATHS = [
    "/ar-sa/grocery/", "/ar-sa/grocery-food-cupboard/",
    "/ar-sa/grocery-food-cupboard-cooking-ingredients/",
    "/ar-sa/grocery-food-cupboard-cooking-ingredients-oils-ghee/",
    "/ar-sa/grocery-food-cupboard-cooking-ingredients-pulses/",
    "/ar-sa/grocery-household-air-fresheners-candles-incense/",
    "/ar-sa/electronics-mobiles/",
    "/ar-sa/fresh-fruits-vegetables-fruits/",
]

# ---------------------------------------------------------------- Danube
DANUBE_CARDS_HTML = """
<div class="product-box product-box--add-to-cart" data-hook="products_list_item"> <a href="/products/bounty-miniatures-150g"> <div class="product-box__image text-center"> <div class="product-box__image__element" style="background-image: url(https://d1c124wpoew66.cloudfront.net/spree/images/attachments/000/027/872/product/103585-Bounty-150g-pouch-700x700.jpg);"></div> <div class="product-validity_tag"></div> </div> <div class="product-loyalty-point-mustache"> ١١ نقاط </div> <div class="product-box__name multiline-ellipsis">باونتي قطع شوكولاتة محشوة بجوز الهند ١٥٠غرام</div> </a> <div class="product-box__price"> <div class="product-price product-price--on-sale"> <div class="product-price__original-price"> <span class="product-price__original-price__span"><i class="riyal-icon"></i> ‏١٦٫٥٠&nbsp;‏</span> </div> <div class="product-price__current-price "><i class="riyal-icon"></i> ‏١٠٫٥٠&nbsp;‏</div> </div> </div> <div class="product-box__add-to-cart"> <div id="add-to-cart-7222" class="add-to-cart"> <form action="/orders/populate" method="post"><input type="hidden" name="variant_id" id="variant_id" value="7222"> <button name="button" type="submit" class="add-to-cart__btn--submit btn btn-primary">إضافة</button></form> </div> </div> </div>
<div class="product-box product-box--add-to-cart" data-hook="products_list_item"> <a href="/products/noor-sunflower-oil-1-5l"> <div class="product-box__name multiline-ellipsis">نور زيت دوار الشمس ١٫٥ لتر</div> </a> <div class="product-box__price"> <div class="product-price"> <div class="product-price__current-price "><i class="riyal-icon"></i> ‏٢١٫٩٥&nbsp;‏</div> </div> </div> <div class="product-box__add-to-cart"></div> </div>
<ul class="pagination"><li><a href="?hierarchicalMenu=x&page=2">2</a></li><li><a href="?hierarchicalMenu=x&page=7">7</a></li></ul>
"""
DANUBE_PRODUCT_HTML = """<html><head><script type="application/ld+json"> {"@context":"https://schema.org","@type":"Product","name":"قطع شوكولاتة محشوة بجوز الهند","image":["https://d1c124wpoew66.cloudfront.net/spree/images/x.jpg"],"description":"...","sku":"32065","brand":{"@type":"Brand","name":"باونتي"},"offers":{"@type":"Offer","url":"https://danube.sa/products/bounty-miniatures-150g","availability":"http://schema.org/InStock","priceCurrency":"SAR","price":"10.5"}} </script></head>
<body><div class="product-show__price-loyalty"> <div class="product-price product-price--on-sale"> <div class="product-price__current-price "> <i class='riyal-icon '>&#xe800</i> 10.50 </div> <div class="product-price__original-price"> <span class="product-price__original-price__span"><i class='riyal-icon '>&#xe800</i> 16.50 </span> </div> </div></div></body></html>"""
