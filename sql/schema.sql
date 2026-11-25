-- =====================================================================
-- Riyadh grocery price comparison – Supabase (Postgres) schema
-- Run once in Supabase → SQL Editor.
-- =====================================================================
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------
-- Stores and the branch we read prices from
-- ---------------------------------------------------------------------
create table if not exists stores (
  id          text primary key,             -- tamimi | panda | lulu | danube
  name_ar     text not null,
  branch      text,
  city        text default 'الرياض',
  website     text
);

insert into stores (id, name_ar, branch, website) values
  ('tamimi', 'التميمي', 'العليا (V131)',          'https://www.tamimimarkets.com'),
  ('panda',  'بنده',    'السعر الأونلاين العام',   'https://panda.sa'),
  ('lulu',   'لولو',    'الخليج (3734)',           'https://gcc.luluhypermarket.com/ar-sa'),
  ('danube', 'الدانوب', 'حياة مول (589)',          'https://danube.sa')
on conflict (id) do update set name_ar = excluded.name_ar, branch = excluded.branch;

-- ---------------------------------------------------------------------
-- Unified product (one row per real-world item, across stores)
-- ---------------------------------------------------------------------
create table if not exists products (
  id          bigserial primary key,
  name_ar     text not null,
  name_en     text,
  brand       text,
  size_value  numeric,            -- grams / millilitres / pieces
  size_unit   text check (size_unit in ('g','ml','pc')),
  category    text,
  image_url   text,
  created_at  timestamptz default now()
);
create index if not exists products_name_trgm on products using gin (name_ar gin_trgm_ops);

-- barcode -> product (a product can have several barcodes)
create table if not exists product_barcodes (
  barcode     text primary key,
  product_id  bigint not null references products(id) on delete cascade
);

-- ---------------------------------------------------------------------
-- The item as sold by one store, with its current price
-- ---------------------------------------------------------------------
create table if not exists store_products (
  id            bigserial primary key,
  store_id      text not null references stores(id),
  store_sku     text not null,
  product_id    bigint references products(id) on delete set null,
  match_method  text,             -- barcode | name | manual
  name_ar       text,
  name_en       text,
  brand         text,
  barcodes      text[] default '{}',
  price         numeric(10,2),
  old_price     numeric(10,2),    -- price before discount, null when no offer
  unit_price    numeric(12,3),    -- SAR per kg / litre / piece
  size_value    numeric,
  size_unit     text,
  in_stock      boolean,
  category      text,
  url           text,
  image_url     text,
  first_seen    timestamptz default now(),
  last_seen     timestamptz default now(),
  price_changed_at timestamptz default now(),
  unique (store_id, store_sku)
);
create index if not exists sp_product on store_products(product_id);
create index if not exists sp_name_trgm on store_products using gin (name_ar gin_trgm_ops);
create index if not exists sp_barcodes on store_products using gin (barcodes);

create table if not exists price_history (
  id               bigserial primary key,
  store_product_id bigint not null references store_products(id) on delete cascade,
  price            numeric(10,2),
  old_price        numeric(10,2),
  recorded_at      timestamptz default now()
);
create index if not exists ph_sp_time on price_history(store_product_id, recorded_at desc);

-- ---------------------------------------------------------------------
-- Shopping lists (one per user; Lovable/Supabase Auth gives auth.uid())
-- ---------------------------------------------------------------------
create table if not exists shopping_lists (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid references auth.users(id) on delete cascade,
  name        text default 'قائمة التسوق',
  share_token text unique default substr(md5(random()::text || clock_timestamp()::text), 1, 12),
  created_at  timestamptz default now()
);

create table if not exists shopping_list_items (
  id               bigserial primary key,
  list_id          uuid not null references shopping_lists(id) on delete cascade,
  product_id       bigint references products(id),
  store_product_id bigint references store_products(id),  -- the store the user picked
  quantity         int default 1,
  checked          boolean default false,
  created_at       timestamptz default now()
);

-- ---------------------------------------------------------------------
-- Ingest: called by the scraper with a batch of offers (JSON array).
-- Upserts store_products, writes price history on change, links by barcode.
-- `quick` = true when only prices are being refreshed.
-- ---------------------------------------------------------------------
create or replace function ingest_offers(payload jsonb, quick boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  o jsonb;
  sp store_products%rowtype;
  prev_price numeric;
  prev_old numeric;
  existed boolean;
  pid bigint;
  n_new int := 0; n_changed int := 0; n_linked int := 0;
  codes text[];
begin
  for o in select * from jsonb_array_elements(payload) loop
    codes := coalesce(array(select jsonb_array_elements_text(o->'barcodes')), '{}');

    select price, old_price into prev_price, prev_old
      from store_products where store_id = o->>'store' and store_sku = o->>'store_sku';
    existed := found;

    insert into store_products as t (store_id, store_sku, name_ar, name_en, brand, barcodes,
        price, old_price, unit_price, size_value, size_unit, in_stock, category, url, image_url)
    values (o->>'store', o->>'store_sku', o->>'name_ar', o->>'name_en', o->>'brand', codes,
        (o->>'price')::numeric, (o->>'old_price')::numeric, (o->>'unit_price')::numeric,
        (o->>'size_value')::numeric, o->>'size_unit', (o->>'in_stock')::boolean,
        o->>'category', o->>'url', o->>'image_url')
    on conflict (store_id, store_sku) do update set
        price      = coalesce(excluded.price, t.price),
        old_price  = excluded.old_price,
        in_stock   = coalesce(excluded.in_stock, t.in_stock),
        unit_price = case when excluded.price is not null and t.size_value is not null
                          then case when t.size_unit in ('g','ml') then round(excluded.price / t.size_value * 1000, 3)
                                    else round(excluded.price / t.size_value, 3) end
                          else coalesce(excluded.unit_price, t.unit_price) end,
        last_seen  = now(),
        -- descriptive fields: full crawl refreshes them, quick refresh only fills gaps
        name_ar    = case when quick then coalesce(t.name_ar, excluded.name_ar) else coalesce(excluded.name_ar, t.name_ar) end,
        name_en    = coalesce(excluded.name_en, t.name_en),
        brand      = coalesce(excluded.brand, t.brand),
        barcodes   = case when cardinality(excluded.barcodes) > 0 then excluded.barcodes else t.barcodes end,
        size_value = case when quick then coalesce(t.size_value, excluded.size_value) else coalesce(excluded.size_value, t.size_value) end,
        size_unit  = case when quick then coalesce(t.size_unit, excluded.size_unit) else coalesce(excluded.size_unit, t.size_unit) end,
        category   = case when quick then coalesce(t.category, excluded.category) else coalesce(excluded.category, t.category) end,
        url        = coalesce(excluded.url, t.url),
        image_url  = coalesce(excluded.image_url, t.image_url)
    returning * into sp;

    if not existed then
      n_new := n_new + 1;
      insert into price_history(store_product_id, price, old_price) values (sp.id, sp.price, sp.old_price);
    elsif sp.price is distinct from prev_price or sp.old_price is distinct from prev_old then
      n_changed := n_changed + 1;
      insert into price_history(store_product_id, price, old_price) values (sp.id, sp.price, sp.old_price);
      update store_products set price_changed_at = now() where id = sp.id;
    end if;

    -- link to a unified product by barcode
    if sp.product_id is null and cardinality(sp.barcodes) > 0 then
      select product_id into pid from product_barcodes where barcode = any(sp.barcodes) limit 1;
      if pid is null then
        insert into products(name_ar, name_en, brand, size_value, size_unit, category, image_url)
        values (coalesce(sp.name_ar, sp.name_en, sp.store_sku), sp.name_en, sp.brand,
                sp.size_value, sp.size_unit, sp.category, sp.image_url)
        returning id into pid;
      end if;
      update store_products set product_id = pid, match_method = 'barcode' where id = sp.id;
      insert into product_barcodes(barcode, product_id)
        select unnest(sp.barcodes), pid on conflict do nothing;
      n_linked := n_linked + 1;
    end if;
  end loop;
  return jsonb_build_object('new', n_new, 'changed', n_changed, 'linked', n_linked);
end $$;

-- Link (or create) a product for an item that has no barcode (Danube).
create or replace function link_store_product(sp_id bigint, target_product bigint, method text default 'name')
returns bigint language plpgsql security definer set search_path = public as $$
declare pid bigint := target_product; sp store_products%rowtype;
begin
  select * into sp from store_products where id = sp_id;
  if pid is null then
    insert into products(name_ar, brand, size_value, size_unit, category, image_url)
    values (coalesce(sp.name_ar, sp.store_sku), sp.brand, sp.size_value, sp.size_unit, sp.category, sp.image_url)
    returning id into pid;
    method := 'own';
  end if;
  update store_products set product_id = pid, match_method = method where id = sp_id;
  return pid;
end $$;

-- Candidates for name matching: same unit and close size, similar name.
create or replace function match_candidates(sp_id bigint, max_results int default 5)
returns table(product_id bigint, name_ar text, size_value numeric, score real)
language sql stable set search_path = public as $$
  select p.id, p.name_ar, p.size_value, similarity(p.name_ar, sp.name_ar) as score
  from store_products sp
  join products p on p.size_unit is not distinct from sp.size_unit
                 and (sp.size_value is null or p.size_value is null
                      or abs(p.size_value - sp.size_value) <= greatest(sp.size_value, p.size_value) * 0.02)
  where sp.id = sp_id
    and not exists (select 1 from store_products x where x.product_id = p.id and x.store_id = sp.store_id)
    and p.name_ar % sp.name_ar
  order by score desc
  limit max_results;
$$;

-- Items the hourly job should refresh: in someone's list, or on offer, or
-- the cheapest offer of a product with 2+ stores.
create or replace function watched_offers(max_rows int default 3000)
returns table(store_id text, url text)
language sql stable set search_path = public as $$
  with ranked as (
    select sp.id, sp.store_id, sp.url,
           case when exists (select 1 from shopping_list_items i where i.store_product_id = sp.id
                                or (i.product_id is not null and i.product_id = sp.product_id)) then 0
                when sp.old_price is not null then 1
                else 2 end as prio
    from store_products sp
    where sp.url is not null and sp.product_id in (
      select product_id from store_products where product_id is not null
      group by product_id having count(distinct store_id) >= 2)
  )
  select store_id, url from ranked order by prio, id limit max_rows;
$$;

-- ---------------------------------------------------------------------
-- What the app reads
-- ---------------------------------------------------------------------
create or replace view v_product_offers with (security_invoker = true) as
select
  p.id            as product_id,
  p.name_ar, p.brand, p.size_value, p.size_unit, p.category,
  coalesce(p.image_url, sp.image_url) as image_url,
  sp.id           as store_product_id,
  sp.store_id, s.name_ar as store_name,
  sp.price, sp.old_price, sp.unit_price, sp.in_stock, sp.url,
  sp.last_seen, sp.price_changed_at,
  rank() over (partition by p.id order by sp.price asc nulls last) as price_rank,
  count(*) over (partition by p.id) as store_count
from products p
join store_products sp on sp.product_id = p.id
join stores s on s.id = sp.store_id
where sp.price is not null
  and sp.last_seen > now() - interval '3 days';   -- hide items that disappeared

create or replace view v_cheapest with (security_invoker = true) as
select distinct on (product_id) *
from v_product_offers
where coalesce(in_stock, true)
order by product_id, price asc;

-- Shopping list grouped by store, for the "my trip" screen
create or replace view v_list_by_store with (security_invoker = true) as
select i.list_id, sp.store_id, s.name_ar as store_name,
       i.id as item_id, coalesce(sp.name_ar, p.name_ar) as name_ar,
       i.quantity, sp.price, sp.old_price, (sp.price * i.quantity) as line_total, i.checked
from shopping_list_items i
join store_products sp on sp.id = i.store_product_id
join stores s on s.id = sp.store_id
left join products p on p.id = i.product_id;

-- ---------------------------------------------------------------------
-- Row level security: catalogue is public read-only; lists are private.
-- The scraper writes with the service_role key, which bypasses RLS.
-- ---------------------------------------------------------------------
alter table stores enable row level security;
alter table products enable row level security;
alter table product_barcodes enable row level security;
alter table store_products enable row level security;
alter table price_history enable row level security;
alter table shopping_lists enable row level security;
alter table shopping_list_items enable row level security;

do $$ begin
  create policy "public read" on stores for select using (true);
  create policy "public read" on products for select using (true);
  create policy "public read" on store_products for select using (true);
  create policy "public read" on price_history for select using (true);
  create policy "own lists" on shopping_lists for all
    using (owner_id = auth.uid()) with check (owner_id = auth.uid());
  create policy "own items" on shopping_list_items for all
    using (exists (select 1 from shopping_lists l where l.id = list_id and l.owner_id = auth.uid()))
    with check (exists (select 1 from shopping_lists l where l.id = list_id and l.owner_id = auth.uid()));
exception when duplicate_object then null; end $$;

-- Functions are executable by PUBLIC by default: only the scraper
-- (service_role) may call the write/maintenance ones.
revoke execute on function ingest_offers(jsonb, boolean) from public, anon, authenticated;
revoke execute on function link_store_product(bigint, bigint, text) from public, anon, authenticated;
revoke execute on function match_candidates(bigint, int) from public, anon, authenticated;
revoke execute on function watched_offers(int) from public, anon, authenticated;
do $$ begin
  grant execute on function ingest_offers(jsonb, boolean) to service_role;
  grant execute on function link_store_product(bigint, bigint, text) to service_role;
  grant execute on function match_candidates(bigint, int) to service_role;
  grant execute on function watched_offers(int) to service_role;
exception when undefined_object then null; end $$;  -- role exists on Supabase only
