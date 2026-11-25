# منصة مقارنة أسعار الهايبر ماركت – الرياض (بقالة)

بتسحب أسعار منتجات البقالة من **التميمي، بنده، لولو، الدانوب**، وتطابق المنتج الواحد بين المتاجر، وتحفظ كل ده في Supabase. الواجهة اللي هتتعمل على Lovable بتقرأ من Supabase مباشرة.

```
GitHub Actions (مجاني)  ──►  scraper (Python)  ──►  Supabase (Postgres)  ◄──  Lovable (الواجهة)
   كل ليلة: كتالوج كامل                                 products / store_products
   كل ساعة: الأسعار المهمة                               price_history / shopping_lists
```

## كل متجر بنقرأه إزاي (اتفحص يوم 24-11-2026)

| المتجر | الفرع | المصدر | الباركود | ملاحظات |
|---|---|---|---|---|
| التميمي | العليا – الرياض (كوكي `store_code=V131`) | صفحة كل منتج (من الـ sitemap، حوالي 23 ألف صفحة) | ✅ | بنحتفظ بأقسام: طازج، أغذية ومشروبات، حياة صحية |
| بنده | السعر الأونلاين العام | صفحات الأقسام (30 منتج في الصفحة) | ✅ | 11 قسم بقالة |
| لولو | الخليج – الرياض (`erp_code=3734`) | صفحات الأقسام الفرعية (50 منتج في الصفحة) | ✅ (أحياناً أكتر من باركود) | منظفات وعناية شخصية مستبعدة |
| الدانوب | حياة مول – الرياض (`danube_district_id=589`) | متصفح آلي (Playwright) لأن المنتجات بتظهر بعد اختيار الفرع | ❌ | المطابقة بالاسم والحجم |

**المطابقة:**
1. **بالباركود** وده بيتم داخل قاعدة البيانات في دالة `ingest_offers`. الأكواد اللي بتبدأ بـ 2 (منتجات بالوزن أو أكواد داخلية) بنتجاهلها لأنها مش موحدة بين المتاجر.
2. **بالاسم** للمنتجات اللي مالهاش باركود (الدانوب والمنتجات الطازجة): مقارنة نصية بعد توحيد الحروف العربية، **وبشرط إن الحجم يكون نفسه**. لو المقارنة مش حاسمة، بنسأل Gemini (اختياري). ولو برضه مش متأكدين، المنتج بيتسجل لوحده ومش بيتلخبط مع منتج تاني.

## التشغيل خطوة بخطوة

### 1) Supabase
- افتح مشروع جديد (الخطة المجانية) ← **SQL Editor** ← الصق محتوى `sql/schema.sql` ← Run.
- من **Project Settings ← API** خد قيمة `Project URL` وقيمة `service_role key`.
  ⚠️ مفتاح الـ service_role يتحط في GitHub بس، **أوعى تحطه في Lovable**. Lovable بيستخدم مفتاح `anon` العادي.

### 2) GitHub
- اعمل repository جديد وارفع عليه الملفات دي كلها.
  نصيحة: خليه **Public**، لأن دقائق GitHub Actions في الـ repos العامة مجانية من غير حد. الكود مافيهوش أي سر، والمفاتيح بتتحفظ في Secrets. لو خليته Private، الحد 2000 دقيقة في الشهر، والسحب الليلي للتميمي لوحده ممكن ياخد حوالي ساعة.
- من **Settings ← Secrets and variables ← Actions** ضيف:
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_KEY`
  - `GEMINI_API_KEY` (اختياري، للمطابقة الصعبة)
- من تبويب **Actions** ← `scrape-prices` ← **Run workflow** ← اختار `mode = full` لأول مرة.
  بعد كده هيشتغل لوحده: كتالوج كامل كل ليلة الساعة 2:17 بتوقيت الرياض، وتحديث الأسعار المهمة كل ساعة من 7 الصبح لحد 12 بالليل.

### 3) تجربة على جهازك (اختياري)
```bash
pip install -r requirements.txt
python -m playwright install chromium        # للدانوب بس
python -m pytest -q                          # 27 اختبار
python -m scraper.run full --stores panda --limit 50 --dry-run   # النتيجة في out/panda.jsonl
```

## إيه اللي بيتحدّث كل ساعة؟
دالة `watched_offers` بتختار لحد 3000 منتج من اللي موجودين في متجرين أو أكتر، بالترتيب ده:
1. المنتجات اللي في قوائم تسوق العملاء.
2. المنتجات اللي عليها عرض.
3. الباقي.

وده بيخلي التحديث كل ساعة خفيف على المواقع، وبيركّز على المنتجات اللي العملاء بيهتموا بيها فعلاً.

## الواجهة على Lovable
اربط Lovable بنفس مشروع Supabase، والصق له الطلب ده:

> Build an Arabic (RTL) grocery price-comparison web app on my Supabase project.
> Data (read-only for visitors):
> - view `v_product_offers` (product_id, name_ar, brand, size_value, size_unit, category, image_url, store_product_id, store_id, store_name, price, old_price, unit_price, in_stock, url, price_rank, store_count, price_changed_at)
> - view `v_cheapest` (one row per product: its cheapest store)
> - table `price_history` (store_product_id, price, old_price, recorded_at)
> Pages:
> 1. Search: text search on name_ar, filters by category / brand / store, sort by lowest price or lowest unit price (SAR per litre/kg/piece). Each product card shows every store's price side by side, highlights the cheapest, shows a discount badge when old_price is set, and "آخر تحديث" from price_changed_at.
> 2. Product page: prices per store + a 30-day price chart from price_history.
> 3. Shopping list (Supabase Auth, tables `shopping_lists` and `shopping_list_items`): "أضف للقائمة" adds the cheapest store_product_id by default; the user can switch store per item. The list page groups items by store (use view `v_list_by_store`) with a subtotal per store, a grand total and "وفّرت X ريال" versus buying everything at the single most expensive store. Buttons: share to WhatsApp (wa.me link with the list as text grouped by store), download/print as PDF, and a share link via share_token.
> 4. A note under prices: "الأسعار من المواقع الإلكترونية لفروع الرياض وقد تختلف في الفرع".
> Use the anon key only. Mobile-first.

## حاجات لازم تاخد بالك منها
- **التزم بقواعد المواقع:** الكود بيقرأ صفحات عامة بس، وبيمشي على 3–4 طلبات في نفس الوقت مع فاصل زمني بينهم، ولو الموقع رجّع 403 أو 429 بيستنى ويقلل السرعة. مابنستخدمش أي API داخلي، ومابنحتفظش بصور المنتجات (بنعرض الرابط الأصلي بس). راجع شروط استخدام كل موقع قبل ما تطلق المنصة للناس.
- **لو موقع غيّر شكله:** السحب الليلي هيفشل وهيظهر عليه علامة حمرا في GitHub Actions، والسجل هيقول "returned only N offers". ساعتها بنعدّل ملف المتجر ده بس في `scraper/stores/`.
- **سعر الموقع ممكن يختلف عن سعر الفرع.** يستاهل تقارن بنفسك كام منتج في الفروع الأول.
- لو حابب تضيف المنظفات والمنتجات المنزلية: التميمي ← ضيف `HOUSEHOLD` في `GROCERY_DEPARTMENTS`، ولولو ← شيل الكلمات دي من `EXCLUDE_WORDS`، وبنده والدانوب ← ضيف أقسامهم.

## الملفات
```
scraper/common.py      نموذج البيانات، قراءة بيانات Next.js، الأرقام العربية، استخراج الحجم
scraper/stores/*.py    ملف لكل متجر (طريقة الوصول مشروحة في أوله)
scraper/matching.py    المطابقة بالاسم (+ Gemini اختياري)
scraper/db.py          الاتصال بـ Supabase
scraper/run.py         التشغيل: full | quick | match
sql/schema.sql         الجداول والدوال والـ views وصلاحيات الأمان
.github/workflows/     الجدولة
tests/                 اختبارات على نماذج حقيقية من المواقع الأربعة
```
