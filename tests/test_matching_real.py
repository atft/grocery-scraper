"""Real Danube items vs their best candidate from the other stores
(sample pulled from Supabase on 2026-11-26), labelled by hand."""
import pytest

from scraper.common import parse_size
from scraper.matching import decide

SAME = "same"        # must be linked
DIFF = "different"   # must NOT be linked
EITHER = "either"    # acceptable either way (close variant) – must not crash

CASES = [
    ("رضوى دجاج كامل طازج فاخر ١١٠٠غرام", "رضوى دجاج طازج فاخر 1.1 كجم", 1100, SAME),
    ("كي دي دي نكتار الفواكه المشكلة الكوكتيل خالي من السكر المضاف ٦*١٢٥مل", "كي دي دي نكتار فواكه بدون سكر مضاف 6 × 125 مل", 750, SAME),
    ("امريكانا تمبورا ناجت الدجاج ٧٠٠غرام", "أميركانا تمبورا ناجت الدجاج 700جرام", 700, SAME),
    ("بيتي كروكر خليط البانكيك بزبدة الحليب ٩٠٧غرام", "بيتي كروكر خليط فطائر البانكيك بالزبدة و الحليب ٩٠٧ جم", 907, SAME),
    ("جرينز نكهة الليمون ٢٨مل", "جرينز نكهة ليمون 28 مل", 28, SAME),
    ("فيتامين ويل مشروب مضاد الأكسدة بنكهة الخوخ ٥٠٠مل", "فيتامين ويل مشروب مضاد للأكسدة بنكهة الخوخ 500 مل", 500, SAME),
    ("بروك بوند ريد ليبل شاي أسود ١٠٠كيس شاي", "بروك بوند ريد ليبل شاي أسود 100 كيس شاي", 100, SAME),
    ("السعودية حليب دبل شوكولاتة ٢٠٠مل", "السعودية حليب دبل شوكو 200 مل", 200, SAME),
    ("جاك إن جيل بياتوس رقائق البطاطس بنكهة الباربيكيو ٨٥غرام", "جاك أند جيل بياتوس رودهاوس رقائق بطاطس بالباربيكيو 85 جم", 85, EITHER),
    ("دورسيت حبوب الإفطار بالتوت البري والكرز واللوز ٥٤٠غرام", "دورسيت رقائق اللوز و الكرز و التوت العليق 540 جم", 540, EITHER),
    ("أميريكان جاردن الصلصة الإيطالية ٧٥٪ دهون أقل ٢٦٧مل", "أمريكان جاردن صلصة سلطة فرنسية ٢٦٧مل", 267, DIFF),
    ("طماطم عنقودية (علبة)", "طماطم كرزية (علبة) 1 pack", None, DIFF),
    ("مزارع الغربية بيض طازج حجم وسط و كبير ٣٠بيضة", "طبق بيض طازج حجم كبير 30 pcs", 30, DIFF),
    ("تويا صلصة حارة سومطرا ١٤٠مل", "تويا صلصة فلفل حارة جداً 140 مل", 140, DIFF),
]


@pytest.mark.parametrize("danube,cand,cand_size,label", CASES)
def test_real_pairs(danube, cand, cand_size, label, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # deterministic: no AI in tests
    size, unit = parse_size(danube)
    item = {"id": 1, "name_ar": danube, "size_value": size, "size_unit": unit}
    pid, method = decide(item, [{"product_id": 42, "name_ar": cand, "size_value": cand_size}])
    if label == SAME:
        assert pid == 42, f"should link: {danube}  <->  {cand}"
    elif label == DIFF:
        assert pid is None, f"must not link: {danube}  <->  {cand}"


@pytest.mark.parametrize("text,expected", [
    ("لونو شوفان سريع التحضير ١كغم", (1000.0, "g")),
    ("افوكادو ١كغم", (1000.0, "g")),
    ("بروك بوند ريد ليبل شاي أسود ١٠٠كيس شاي", (100.0, "pc")),
    ("المراعي حليب بنكهة الفراولة ١٨*٢٠٠مل", (3600.0, "ml")),
])
def test_units_seen_on_danube(text, expected):
    assert parse_size(text) == expected
