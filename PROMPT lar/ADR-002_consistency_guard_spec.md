# ADR-002 — `pickup_date ↔ route_date` Consistency Guard (Spec)

| Field | Value |
|---|---|
| **Tarih** | 2026-05-09 |
| **Author** | Architect (Software_Team) |
| **Source** | Solution_Analyst denetimi 2026-05-09 (KARIMA / ORD-0163) |
| **Predecessor** | ADR-001 (LIVE 2026-05-09 02:14 UTC) — mesaj kalitesi düzeltildi |
| **Status** | Spec READY → Developer hand-off |
| **Hand-off** | Developer (Software_Team) — migration deploy + smoke test |
| **Risk** | DÜŞÜK — read filter daraltma + AFTER trigger; transaction'ı bloke etmez |
| **Geri uyumluluk** | Tam korunur — RPC sütun şeması değişmez, çağıran tek workflow var |

---

## 0. Yönetici Özeti

KARIMA vakasında (2026-05-06) `orders.pickup_date = 2026-05-08` (Cuma) olan bir order, `route_date = 2026-05-06` (Çarşamba) bir pickup rotasındaki stop'a bağlanmıştı. ETA reminder workflow `Hzuyvr5EK6grSyY7` o gün tetiklendi ve müşteriye **yanlış güne ait** mesaj atıldı (ADR-001 mesajın kelime hatasını düzeltti, ama tetik ihlalini değil).

ADR-002 sistemik problemi iki katmanda kapatır:

1. **Yumuşak DB-level uyarı (trigger):** `route_stops` INSERT/UPDATE'lerde `pickup_date != route_date AND route_type='pickup'` çelişkisi tespit edildiğinde yeni `data_consistency_warnings` tablosuna kayıt yazar. **EXCEPTION fırlatmaz** — operatör akışını durdurmaz, sadece görünürlük sağlar.
2. **Sert RPC-level filtre:** `get_upcoming_eta_reminders` WHERE koşuluna `(o.pickup_date IS NULL OR o.pickup_date = r.route_date OR r.route_type = 'delivery')` eklenir. Çelişkili order'lar reminder ALMAZ — müşteriye yanlış mesaj çıkması imkânsız hale gelir.

**Felsefe:** *"Eksik mesajlama < yanlış mesajlama; ama operatörü engellemek de istemiyoruz."* Trigger uyarır, RPC bloke eder.

---

## 1. Mevcut Schema Durumu (Bölüm 1)

### 1.1 İlgili tablolar

`Dashboard_SaaS/supabase/migrations/20260215184835_create_logistics_schema.sql` ve sonraki ekler:

| Tablo | İlgili sütunlar | Notlar |
|---|---|---|
| `orders` | `id uuid PK`, `company_id uuid NOT NULL`, `pickup_date date NULL` (DEFAULT yok), `customer_phone text NOT NULL` | `pickup_date` üzerinde trigger/constraint YOK; sadece `idx_orders_pickup_date` (B-tree) |
| `routes` | `id uuid PK`, `company_id uuid NOT NULL`, `route_type text NOT NULL` (`'pickup' \| 'delivery'`), `route_date date NOT NULL`, `status text` (`planned/in_progress/completed/cancelled`) | `route_type` üzerinde CHECK YOK — string olarak saklanıyor |
| `route_stops` | `id uuid PK`, `route_id uuid NOT NULL → routes`, `order_id uuid NOT NULL → orders`, `stop_order int`, `address text`, `estimated_arrival time`, `completed bool`, `reminder_sent bool`, `initial_notif_sent bool` | İndeksler: `idx_route_stops_route_id`, `idx_route_stops_reminder`, `idx_route_stops_initial_notif` |
| `audit_log` / `data_consistency_warnings` | **YOK** | Mevcut audit altyapısı yok; ADR-003 daha geniş bir audit tablosu önerecek (`order_changes` veya `pickup_date_history JSONB`) |

### 1.2 Mevcut RPC

`get_upcoming_eta_reminders()` — `Dashboard_SaaS/supabase/migrations/20260322_eta_notification_setup.sql:44-88`:

```sql
CREATE OR REPLACE FUNCTION public.get_upcoming_eta_reminders()
RETURNS TABLE(
  stop_id uuid, route_id uuid, order_id uuid,
  customer_name text, customer_phone text, language text,
  estimated_arrival_time time, route_date date,
  address text, route_type text
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
  SELECT
    rs.id AS stop_id, rs.route_id, rs.order_id,
    o.customer_name, o.customer_phone,
    COALESCE(c.language, 'fr') AS language,
    rs.estimated_arrival AS estimated_arrival_time,
    r.route_date, rs.address, r.route_type
  FROM public.route_stops rs
  INNER JOIN public.routes r  ON rs.route_id = r.id
  INNER JOIN public.orders  o ON rs.order_id = o.id
  LEFT  JOIN public.customers c
         ON  c.phone      = o.customer_phone
         AND c.company_id = r.company_id
  WHERE
    (r.route_date::date + rs.estimated_arrival::time)::timestamp
      AT TIME ZONE 'Europe/Brussels'
      BETWEEN NOW() + INTERVAL '2 hours 50 minutes'
          AND NOW() + INTERVAL '3 hours 10 minutes'
    AND rs.completed   = false
    AND (rs.reminder_sent IS NULL OR rs.reminder_sent = false)
    AND r.status IN ('planned', 'in_progress')
  ORDER BY rs.estimated_arrival ASC;
$$;
```

`o.pickup_date` HİÇ kullanılmıyor → çelişki yakalanmıyor.

### 1.3 Mevcut trigger envanteri (route_stops üzerinde)

| Trigger | Durum | Not |
|---|---|---|
| `eta_change_trigger` | `DROP`'lanmış (migration `20260401000000_fix_eta_trigger_type_mismatch.sql`) | Tip uyumsuzluğu yüzünden silindi |
| (başka) | Yok | route_stops üzerinde aktif trigger yok → ADR-002 trigger'ı temiz alana iniyor |

### 1.4 RPC çağıranları (geriye uyumluluk taraması)

`F:\AI AGENCY K-SAT\AYKA Transport lojistics projet` altında `get_upcoming_eta_reminders` substring grep:

| Konum | Tip | Etki |
|---|---|---|
| `Dashboard_SaaS/supabase/migrations/20260322_eta_notification_setup.sql` | tanım | RPC'nin kendisi |
| `_workflow_backups/prod_Hzuyvr5EK6grSyY7_*.json` (3 dosya) | n8n workflow snapshot | Tek aktif çağıran: ETA Reminder workflow `Hzuyvr5EK6grSyY7` |
| `ADR-001_hot-fix_spec.md` | döküman | Yalnızca referans |

**Sonuç:** Tek çağıran var, çıktı şeması (`stop_id, route_id, …, route_type`) korunduğu sürece kırılma yok. WHERE filtresi daralma olduğundan DOWNSTREAM yan etki: bazı satırlar bu RPC çağrısında dönmeyecek → ETA Reminder o stop için reminder atmayacak. Bu **istenen davranış**.

---

## 2. Tasarım Kararları (Bölüm 2)

### 2.1 Audit altyapısı: yeni tablo (`data_consistency_warnings`)

**Karar:** Mevcut bir audit tablosu yok. ADR-002 kapsamında **dar amaçlı** bir tablo ekle: `public.data_consistency_warnings`. ADR-003'ün daha geniş `order_changes` audit tablosu **ayrı** olarak gelecek; karıştırılmamalı.

**Neden ayrı:**
- ADR-002 sadece *otomatik tespit edilen veri tutarsızlıklarını* tutar (sistem-driven, append-only).
- ADR-003 ise *operatör/sistem tarafından yapılan UPDATE'lerin tarihçesini* (kim, ne zaman, neyi nasıl değiştirdi) tutacak — farklı sorgu profili.
- İleride iki tablo birleştirilmek istenirse VIEW eklemek kolay; ters yön (büyük tabloyu bölmek) zor.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS public.data_consistency_warnings (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   uuid        REFERENCES public.companies(id) ON DELETE CASCADE,
  warning_type text        NOT NULL,    -- ör. 'pickup_date_route_mismatch'
  table_name   text        NOT NULL,    -- ör. 'route_stops'
  record_id    uuid,                    -- tetikleyen satır (route_stops.id)
  payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_company_id
  ON public.data_consistency_warnings (company_id);

CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_type_created
  ON public.data_consistency_warnings (warning_type, created_at DESC);

ALTER TABLE public.data_consistency_warnings ENABLE ROW LEVEL SECURITY;

-- Sadece şirket üyeleri kendi şirketlerinin uyarılarını görebilsin
CREATE POLICY "Users can view their company consistency warnings"
  ON public.data_consistency_warnings FOR SELECT
  TO authenticated
  USING (
    company_id IN (
      SELECT company_id FROM public.profiles WHERE id = auth.uid()
    )
  );

-- INSERT yalnızca trigger (SECURITY DEFINER) tarafından yapılır.
-- Authenticated kullanıcıya INSERT/UPDATE/DELETE policy'si verilmez (yok = yasak).
-- service_role RLS'ten muaf olduğu için ek policy gerekmez.
```

**Tasarım notları:**
- `payload jsonb` → ileride yeni warning türleri için şema değişikliği gerekmez.
- `company_id` kolonu RLS için zorunlu. Trigger içinde `routes.company_id` üzerinden doldurulacak.
- `record_id` UUID — tetikleyen `route_stops.id` (FK değil, çünkü stop silinse bile uyarı geçmişi kalmalı).

### 2.2 Trigger: yumuşak (AFTER, soft, no-exception)

**Karar matrisi:**

| Karar | Seçilen | Alternatif | Gerekçe |
|---|---|---|---|
| AFTER vs BEFORE | **AFTER** | BEFORE | AFTER row-level commit'inden önce ama satır oluştuktan sonra çalışır → log her zaman gerçek state'i yansıtır. BEFORE'da satır iptal olursa sahte uyarı kalabilirdi. |
| RAISE EXCEPTION vs INSERT | **INSERT** (soft) | RAISE | Solution_Analyst direktifi: meşru durumlar olabilir (operatör bilinçli tarih kayması yapabilir). Engellemek operatör otonomisini bozar. |
| Tetik koşulu | `INSERT OR UPDATE OF route_id, order_id` | `INSERT OR UPDATE` (tüm UPDATE) | Sadece *ilişki* değişikliklerinde tetik. `actual_arrival`, `notes`, `completed` gibi field UPDATE'lerinde gereksiz log yazmamak için. |
| FOR EACH ROW vs STATEMENT | **ROW** | STATEMENT | Her satırı ayrı ayrı değerlendirip, sadece çelişkili olan(lar) için log yazmak gerek. |
| SECURITY DEFINER vs INVOKER | **DEFINER** | INVOKER | Trigger anonim auth context'inde de (driver_app, n8n service_role) çalışacak. RLS bypass gerekli. |
| Pencere: hangi route_type | sadece `'pickup'` | tüm tipler | Solution_Analyst kararı: delivery rotalarında `pickup_date != route_date` MEŞRU (kapı `pickup_date`'ten sonraki bir tarihte teslim). |

### 2.3 RPC: sert filtre (WHERE eki)

**Karar matrisi:**

| Karar | Seçilen | Alternatif | Gerekçe |
|---|---|---|---|
| Tam fonksiyonu yeniden yaz vs ALTER | **Tam yeniden** (`CREATE OR REPLACE`) | yok | PostgreSQL'de fonksiyon body parça-değişimi yok; tek yol body'yi tümüyle yeniden tanımlamak. |
| NULL davranışı | `pickup_date IS NULL → reminder DÖNER` | NULL → reminder dönmez | Defansif: bilgi yokluğunda mevcut davranışı koru. ADR-001'in NULL fallback yaklaşımıyla tutarlı (mesaj `prochainement` döner). |
| Delivery için filtre | `route_type = 'delivery' → muafiyet` | tüm tiplerde filtre | Delivery rotasında pickup_date ile route_date ilişkisi yok. |
| Sütun şeması | **DEĞİŞMEZ** | yeni alan eklemek | n8n workflow `Hzuyvr5EK6grSyY7` mevcut alanlara `$json.<field>` ile erişiyor. Şema değişmemeli. |

### 2.4 Migration paketi: tek dosya (atomik)

**Karar:** Tek migration dosyası. Sıra: (1) tablo + RLS → (2) trigger fonksiyonu → (3) trigger → (4) RPC `CREATE OR REPLACE`.

**Gerekçe:** İçerik birlikte deploy edilmeli; iki dosyaya bölünürse RPC dosyası önce uygulansa bile trigger gecikse kısmi koruma olur. Tek dosya transaction'da çalışır → atomik.

**Rollback complexity tradeoff:** Tek revert dosyasıyla yönetilebilir (Bölüm 5).

### 2.5 Migration dosyası adı

`Dashboard_SaaS/supabase/migrations/20260509150000_pickup_date_route_consistency_guard.sql`

Saat (`150000`): Brüksel TZ ile rapor zamanı sonrası — bugüne kadar uygulanmış son migration `20260508130000` olduğundan zaman sırası korunur.

---

## 3. Migration SQL'leri (Bölüm 3)

> **Hatırlatma — Developer için:** Migration deploy pattern'i `reference_supabase_migration_push.md`'de:
> 1. Her statement ayrı `npx supabase db query` ile uygula (aşağıdaki SQL bloğu ; ile bölünmüş çoklu ifade içeriyor).
> 2. Bittiğinde `INSERT INTO supabase_migrations.schema_migrations (version, name, statements) VALUES ('20260509150000', 'pickup_date_route_consistency_guard', ARRAY[...]) ON CONFLICT DO NOTHING;`

### 3.1 Migration dosyası tam içeriği

```sql
-- =====================================================================
-- ADR-002 — pickup_date ↔ route_date consistency guard
-- Tarih: 2026-05-09
-- Architect spec: PROMPT lar/ADR-002_consistency_guard_spec.md
-- Önce: ADR-001 LIVE (mesaj formatı). Bu migration sistemik tutarlılık.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. data_consistency_warnings tablosu (otomatik tespit edilen ihlaller)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.data_consistency_warnings (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   uuid        REFERENCES public.companies(id) ON DELETE CASCADE,
  warning_type text        NOT NULL,
  table_name   text        NOT NULL,
  record_id    uuid,
  payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_company_id
  ON public.data_consistency_warnings (company_id);

CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_type_created
  ON public.data_consistency_warnings (warning_type, created_at DESC);

ALTER TABLE public.data_consistency_warnings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their company consistency warnings"
  ON public.data_consistency_warnings;

CREATE POLICY "Users can view their company consistency warnings"
  ON public.data_consistency_warnings FOR SELECT
  TO authenticated
  USING (
    company_id IN (
      SELECT company_id FROM public.profiles WHERE id = auth.uid()
    )
  );

-- ---------------------------------------------------------------------
-- 2. Trigger fonksiyonu: route_stops üzerinde pickup_date/route_date çelişki dedektörü
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.check_pickup_date_route_consistency()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_route_date     date;
  v_route_type     text;
  v_company_id     uuid;
  v_pickup_date    date;
BEGIN
  -- Rota ve order bilgilerini topla
  SELECT r.route_date, r.route_type, r.company_id
    INTO v_route_date, v_route_type, v_company_id
    FROM public.routes r
   WHERE r.id = NEW.route_id;

  SELECT o.pickup_date
    INTO v_pickup_date
    FROM public.orders o
   WHERE o.id = NEW.order_id;

  -- Çelişki koşulu:
  --   * pickup_date dolu (NULL → bilinmeyen, log yazma)
  --   * pickup_date != route_date
  --   * route_type = 'pickup' (delivery'de meşru fark olabilir)
  IF v_pickup_date IS NOT NULL
     AND v_pickup_date <> v_route_date
     AND v_route_type = 'pickup'
  THEN
    INSERT INTO public.data_consistency_warnings (
      company_id, warning_type, table_name, record_id, payload
    )
    VALUES (
      v_company_id,
      'pickup_date_route_mismatch',
      'route_stops',
      NEW.id,
      jsonb_build_object(
        'route_id',         NEW.route_id,
        'order_id',         NEW.order_id,
        'route_date',       v_route_date,
        'pickup_date',      v_pickup_date,
        'route_type',       v_route_type,
        'trigger_op',       TG_OP,
        'detected_at_utc',  now()
      )
    );
  END IF;

  RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------
-- 3. Trigger: AFTER INSERT veya OF (route_id, order_id) UPDATE
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS check_pickup_date_route_consistency_trg
  ON public.route_stops;

CREATE TRIGGER check_pickup_date_route_consistency_trg
  AFTER INSERT OR UPDATE OF route_id, order_id
  ON public.route_stops
  FOR EACH ROW
  EXECUTE FUNCTION public.check_pickup_date_route_consistency();

-- ---------------------------------------------------------------------
-- 4. RPC update: get_upcoming_eta_reminders — pickup_date filter eklenir
--    (Yeni satır: AND (o.pickup_date IS NULL OR o.pickup_date = r.route_date OR r.route_type = 'delivery'))
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_upcoming_eta_reminders()
RETURNS TABLE(
  stop_id                uuid,
  route_id               uuid,
  order_id               uuid,
  customer_name          text,
  customer_phone         text,
  language               text,
  estimated_arrival_time time,
  route_date             date,
  address                text,
  route_type             text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
  SELECT
    rs.id                                   AS stop_id,
    rs.route_id,
    rs.order_id,
    o.customer_name,
    o.customer_phone,
    COALESCE(c.language, 'fr')              AS language,
    rs.estimated_arrival                    AS estimated_arrival_time,
    r.route_date,
    rs.address,
    r.route_type
  FROM public.route_stops rs
  INNER JOIN public.routes r  ON rs.route_id  = r.id
  INNER JOIN public.orders  o ON rs.order_id  = o.id
  LEFT  JOIN public.customers c
         ON  c.phone      = o.customer_phone
         AND c.company_id = r.company_id
  WHERE
    (r.route_date::date + rs.estimated_arrival::time)::timestamp
      AT TIME ZONE 'Europe/Brussels'
      BETWEEN NOW() + INTERVAL '2 hours 50 minutes'
          AND NOW() + INTERVAL '3 hours 10 minutes'
    AND rs.completed   = false
    AND (rs.reminder_sent IS NULL OR rs.reminder_sent = false)
    AND r.status IN ('planned', 'in_progress')
    -- ADR-002 sert filtre: çelişkili order'lar reminder ALMASIN
    AND (
      o.pickup_date IS NULL
      OR o.pickup_date = r.route_date
      OR r.route_type = 'delivery'
    )
  ORDER BY rs.estimated_arrival ASC;
$$;

-- =====================================================================
-- ADR-002 migration tamamlandı.
-- Sonra çalıştırılması gereken:
--   INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
--   VALUES ('20260509150000', 'pickup_date_route_consistency_guard', ARRAY[<statements>])
--   ON CONFLICT (version) DO NOTHING;
-- =====================================================================
```

### 3.2 `db query` için bölünmüş statement listesi

Developer her birini ayrı `npx supabase db query "..."` çağrısıyla çalıştırır:

1. `CREATE TABLE IF NOT EXISTS public.data_consistency_warnings (...)`
2. `CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_company_id ...`
3. `CREATE INDEX IF NOT EXISTS idx_data_consistency_warnings_type_created ...`
4. `ALTER TABLE public.data_consistency_warnings ENABLE ROW LEVEL SECURITY;`
5. `DROP POLICY IF EXISTS "Users can view their company consistency warnings" ON public.data_consistency_warnings;`
6. `CREATE POLICY "Users can view their company consistency warnings" ...`
7. `CREATE OR REPLACE FUNCTION public.check_pickup_date_route_consistency() ...` (PLpgSQL gövdesi içeren tek statement)
8. `DROP TRIGGER IF EXISTS check_pickup_date_route_consistency_trg ON public.route_stops;`
9. `CREATE TRIGGER check_pickup_date_route_consistency_trg AFTER INSERT OR UPDATE OF route_id, order_id ON public.route_stops FOR EACH ROW EXECUTE FUNCTION public.check_pickup_date_route_consistency();`
10. `CREATE OR REPLACE FUNCTION public.get_upcoming_eta_reminders() ...` (yeni body)
11. `INSERT INTO supabase_migrations.schema_migrations (...) ON CONFLICT (version) DO NOTHING;`

PowerShell'den heredoc ile değil, her statement tek string parametresi olarak `npx supabase db query "..."` şeklinde gönder. `$$ ... $$` body'lerinde dolar işaretlerini PowerShell escape kuralları ile ilet (`'@`/`@'` here-string).

---

## 4. Test Plan (Bölüm 4)

### 4.1 Trigger testleri (5 senaryo)

| # | Senaryo | Beklenen sonuç |
|---|---|---|
| **T1** | Çelişkili INSERT: `orders.pickup_date = 2026-05-08`, `routes.route_date = 2026-05-06`, `routes.route_type = 'pickup'`. Yeni `route_stops` insert. | `data_consistency_warnings`'ta 1 yeni kayıt (`warning_type='pickup_date_route_mismatch'`, `payload.pickup_date='2026-05-08'`, `payload.route_date='2026-05-06'`, `payload.trigger_op='INSERT'`) |
| **T2** | Tutarlı INSERT: `pickup_date == route_date`, `route_type='pickup'`. | `data_consistency_warnings` boş kalır (insert tetiklenmez). |
| **T3** | Delivery muafiyeti: `pickup_date != route_date`, `route_type='delivery'`. | `data_consistency_warnings` boş kalır. |
| **T4** | NULL muafiyeti: `orders.pickup_date IS NULL`, `route_type='pickup'`. | `data_consistency_warnings` boş kalır. |
| **T5** | UPDATE: mevcut `route_stops` satırının `route_id`'si farklı bir rotaya (yine pickup, ama route_date çelişkili) güncellenir. | `data_consistency_warnings`'ta 1 yeni kayıt (`payload.trigger_op='UPDATE'`). |

**Smoke senaryoları (gözlem):**
- T6 (sızdırma kontrolü): `route_stops.notes` veya `actual_arrival` UPDATE'i — trigger TETİKLENMEMELI (sadece `route_id, order_id` UPDATE'inde tetik).
- T7 (RLS): İki farklı şirketin warning satırları — şirket A operatörü sadece A'nın warning'lerini görmeli.

### 4.2 RPC testleri (4 senaryo)

| # | Senaryo | Beklenen sonuç |
|---|---|---|
| **R1** | Tutarlı stop, ETA penceresi içinde, reminder_sent=false, status='planned'. | RPC bu satırı **DÖNER**. |
| **R2** | Çelişkili stop (`pickup_date != route_date`, `route_type='pickup'`), ETA penceresi içinde, reminder_sent=false. | RPC bu satırı **DÖNDÜRMEZ** (yeni filtre nedeniyle). |
| **R3** | `orders.pickup_date IS NULL`, ETA penceresi içinde. | RPC **DÖNER** (defansif: bilinmeyen → mevcut davranış). |
| **R4** | Delivery rotası, `pickup_date != route_date` (örn. pickup-Cuma, delivery-Salı). | RPC **DÖNER** (delivery muafiyeti). |

**KARIMA simülasyonu (entegrasyon smoke):**
- Test order: `customer_phone='+999000000001'`, `pickup_date='2026-05-08'`.
- Test route: `route_date='2026-05-06'`, `route_type='pickup'`, `status='planned'`.
- route_stops INSERT → trigger T1 yazsın + RPC R2'de gözükmesin.
- ETA pencere için `estimated_arrival` ayarlanır (NOW + ~3h Brüksel).
- `SELECT * FROM get_upcoming_eta_reminders();` → bu test row'u görünmemeli.

### 4.3 Performans gözlemi

- `route_stops` INSERT/UPDATE sıklığı düşük (operatör driven, günde onlarca kayıt). AFTER ROW trigger ihmal edilebilir.
- `data_consistency_warnings` büyümesi yavaş; günde <10 satır beklenir. Index'ler 6 ay sonra revize edilebilir (low-priority).

---

## 5. Rollback (Bölüm 5)

Bir aksaklık halinde tek dosyalı revert:

```sql
-- ---------------------------------------------------------------------
-- ADR-002 ROLLBACK
-- ---------------------------------------------------------------------

-- 1. Trigger ve fonksiyonu kaldır
DROP TRIGGER IF EXISTS check_pickup_date_route_consistency_trg
  ON public.route_stops;

DROP FUNCTION IF EXISTS public.check_pickup_date_route_consistency();

-- 2. RPC'yi ADR-002 öncesi haline döndür (pickup_date filtresi kaldırılmış)
CREATE OR REPLACE FUNCTION public.get_upcoming_eta_reminders()
RETURNS TABLE(
  stop_id uuid, route_id uuid, order_id uuid,
  customer_name text, customer_phone text, language text,
  estimated_arrival_time time, route_date date,
  address text, route_type text
)
LANGUAGE sql STABLE SECURITY DEFINER
AS $$
  SELECT
    rs.id AS stop_id, rs.route_id, rs.order_id,
    o.customer_name, o.customer_phone,
    COALESCE(c.language, 'fr') AS language,
    rs.estimated_arrival AS estimated_arrival_time,
    r.route_date, rs.address, r.route_type
  FROM public.route_stops rs
  INNER JOIN public.routes r  ON rs.route_id = r.id
  INNER JOIN public.orders  o ON rs.order_id = o.id
  LEFT  JOIN public.customers c
         ON  c.phone      = o.customer_phone
         AND c.company_id = r.company_id
  WHERE
    (r.route_date::date + rs.estimated_arrival::time)::timestamp
      AT TIME ZONE 'Europe/Brussels'
      BETWEEN NOW() + INTERVAL '2 hours 50 minutes'
          AND NOW() + INTERVAL '3 hours 10 minutes'
    AND rs.completed   = false
    AND (rs.reminder_sent IS NULL OR rs.reminder_sent = false)
    AND r.status IN ('planned', 'in_progress')
  ORDER BY rs.estimated_arrival ASC;
$$;

-- 3. (İsteğe bağlı) data_consistency_warnings tablosunu koru (geçmiş veriyi tutmak için)
--    Tablo silinmek istenirse:
--    DROP TABLE IF EXISTS public.data_consistency_warnings;

-- 4. schema_migrations'tan kaydı sil (revert temizliği)
DELETE FROM supabase_migrations.schema_migrations
 WHERE version = '20260509150000';
```

**Rollback notu:** Tabloyu silmek genellikle istenmez (audit kayıtları kıymetli). Default: tabloyu KORU, sadece trigger + RPC değişikliğini geri al.

---

## 6. Geriye Uyumluluk (Bölüm 6)

### 6.1 RPC çağıran etkisi

| Çağıran | Tip | Etki |
|---|---|---|
| n8n workflow `Hzuyvr5EK6grSyY7` (ETA Reminder) | aktif | Çıktı şeması değişmedi → kod değişikliği gerekmez. Daha az satır dönebilir (çelişkili order'lar filtrelenir) → bu **tasarım amacı**. |
| Diğer n8n workflow'ları | yok (grep sonucu) | Etki yok. |
| Dashboard frontend | yok | RPC frontend'den çağrılmıyor. |
| Diğer migrations | sadece tanım | Etki yok. |

### 6.2 Trigger çalışma yolları (route_stops INSERT/UPDATE noktaları)

Mevcut INSERT/UPDATE noktaları (taranmamış ama tasarım açısından risk değerlendirmesi):

| Yazıcı | Davranış |
|---|---|
| n8n ROUTES PLANNING workflow `OhBvaPoczlPgIJmr` (`insert_route_with_stops` RPC üzerinden) | INSERT — trigger AFTER → bulk insert sırasında yavaşlatma yok |
| Dashboard `routes/route_stops` UPDATE'leri (Driver_app, Workshop_app) | UPDATE — sadece `route_id, order_id` değişikliklerinde tetik; reminder_sent vb. UPDATE'lerde tetik yok |
| Driver_app `actual_arrival` UPDATE'i | sızmaz (UPDATE OF route_id, order_id değil) |

### 6.3 RLS uyumluluğu

`data_consistency_warnings` SELECT policy: kullanıcı sadece kendi company'sinin warning'lerini görür. `Users can view their company consistency warnings` policy'si `profiles.company_id` JOIN'i kullanır — RLS recursion riski yok (mevcut diğer tablolarla aynı kalıp).

---

## 7. Developer Hand-off (Bölüm 7)

### 7.1 Migration deploy adımları

1. **Pre-deploy state snapshot:**
   ```
   npx supabase db query "SELECT version FROM supabase_migrations.schema_migrations ORDER BY version DESC LIMIT 5;" --db-url "..."
   ```
   Sonuç son uygulanan migration'ı göstermeli (`20260508130000` beklenen).

2. **Migration dosyasını yaz:**
   - Yol: `Dashboard_SaaS/supabase/migrations/20260509150000_pickup_date_route_consistency_guard.sql`
   - İçerik: Bölüm 3.1.

3. **Statement-by-statement uygula** (`reference_supabase_migration_push.md`):
   - Bölüm 3.2'deki 11 statement'ı sırayla `npx supabase db query "<stmt>"` ile çalıştır.
   - Her birinin başarılı olduğunu doğrula (NOTICE/error yok).

4. **Hızlı sanity check:**
   ```sql
   SELECT proname, prosrc FROM pg_proc WHERE proname = 'check_pickup_date_route_consistency';
   SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'public.route_stops'::regclass;
   SELECT proname FROM pg_proc WHERE proname = 'get_upcoming_eta_reminders';
   SELECT to_regclass('public.data_consistency_warnings');
   ```
   Beklenen: 4 sonuç da dolu.

5. **Smoke test:** Bölüm 4.1 T1 + Bölüm 4.2 R2 senaryolarını test verisiyle çalıştır. Sonra test verilerini sil.

6. **Live monitor (24 saat):**
   ```sql
   SELECT warning_type, payload, created_at
     FROM public.data_consistency_warnings
    WHERE created_at > now() - INTERVAL '24 hours'
    ORDER BY created_at DESC;
   ```
   Eğer üretim verisinde warning oluşursa Solution_Analyst'e ilet (bu mevcut çelişkili veri olduğu anlamına gelir — ADR-003 audit log'undan önce manuel analiz gerek).

### 7.2 KARIMA için geriye dönük doğrulama (opsiyonel)

KARIMA stop'u (route 2026-05-06 + ORD-0163) hâlâ DB'deyse, migration sonrası elle bir UPDATE no-op tetiklemeden önce şu sorgu o vakanın kayda girdiğini gösterir:
```sql
-- Mevcut çelişkili row'ları (geçmiş + güncel) tespit et:
SELECT rs.id AS stop_id, rs.route_id, rs.order_id,
       o.pickup_date, r.route_date, r.route_type
  FROM public.route_stops rs
  JOIN public.routes  r ON rs.route_id = r.id
  JOIN public.orders  o ON rs.order_id = o.id
 WHERE o.pickup_date IS NOT NULL
   AND o.pickup_date <> r.route_date
   AND r.route_type = 'pickup';
```
Bu sorgu KARIMA gibi geçmiş çelişkili stop'ları listeleyecek. **Trigger sadece yeni INSERT/UPDATE'lerde çalışır → geçmiş veriyi backfill için yapılması gereken:**
```sql
-- Backfill: mevcut çelişkili row'lar için warning yaz
INSERT INTO public.data_consistency_warnings (company_id, warning_type, table_name, record_id, payload)
SELECT r.company_id,
       'pickup_date_route_mismatch',
       'route_stops',
       rs.id,
       jsonb_build_object(
         'route_id',    rs.route_id,
         'order_id',    rs.order_id,
         'route_date',  r.route_date,
         'pickup_date', o.pickup_date,
         'route_type',  r.route_type,
         'trigger_op',  'BACKFILL',
         'detected_at_utc', now()
       )
  FROM public.route_stops rs
  JOIN public.routes  r ON rs.route_id = r.id
  JOIN public.orders  o ON rs.order_id = o.id
 WHERE o.pickup_date IS NOT NULL
   AND o.pickup_date <> r.route_date
   AND r.route_type = 'pickup';
```
Backfill **isteğe bağlı** — eğer Director geçmiş vakaları görünür kılmak isterse uygula. Aksi takdirde sadece bundan sonraki çelişkiler kayda girer.

### 7.3 Tek cümlelik hand-off

> Developer: `Dashboard_SaaS/supabase/migrations/20260509150000_pickup_date_route_consistency_guard.sql` dosyasını yaz (Bölüm 3.1), `reference_supabase_migration_push.md` pattern'iyle 11 statement'ı sıralı uygula, schema_migrations'a kaydı düş, ardından Bölüm 4 test planını kestir; tüm testler geçerse System_Tester'a smoke devret.

---

## 8. ADR-003 ile İlişki (out of scope, not bilgisi)

ADR-003 (`order_changes` audit log) ADR-002'den **bağımsız** ve **sonra** gelir. ADR-002'nin `data_consistency_warnings` tablosu otomatik tespit içindir; ADR-003'ün `order_changes` tablosu *operatör/sistem UPDATE tarihçesi* için. KARIMA'nın 05-06 rotasına nasıl bağlandığı sorusu (Solution_Analyst raporu, "Açık konular") sadece ADR-003 ile cevaplanır.

İki tablonun semantik ayrımı:
- `data_consistency_warnings` → "sistem bir tutarsızlık tespit etti" (otomatik, dar)
- `order_changes` → "şu anda kim bunu değiştirdi" (manuel/sistem UPDATE'leri, geniş)

---

## 9. Architect İmzası

- **Spec hazır:** 2026-05-09 (Architect)
- **Solution_Analyst referansı:** kök neden raporu — `~/.claude/projects/F--AI-AGENCY-K-SAT/memory/project_ayka_eta_reminder_root_cause.md`
- **ADR-001 referansı:** `PROMPT lar/ADR-001_hot-fix_spec.md` (LIVE 2026-05-09 02:14 UTC)
- **Read-only inceleme:** Schema, RPC, n8n workflow snapshot'ları, mevcut trigger envanteri okundu; hiçbir DB write yapılmadı.

✅ **Done**
- Schema/RPC/trigger envanteri çıkarıldı (orders, routes, route_stops, customers; mevcut triggerlar; RPC çağıranları).
- Audit altyapı kararı: yeni `data_consistency_warnings` tablosu (ADR-003'ün `order_changes` ile karışmasın diye semantik ayrım).
- Trigger spec yazıldı: AFTER INSERT OR UPDATE OF (route_id, order_id), FOR EACH ROW, SECURITY DEFINER, EXCEPTION fırlatmaz.
- RPC spec yazıldı: `CREATE OR REPLACE` ile `WHERE` koşuluna `(o.pickup_date IS NULL OR o.pickup_date = r.route_date OR r.route_type = 'delivery')` eklendi.
- 5 trigger + 4 RPC test senaryosu + KARIMA smoke + RLS sızıntı testi yazıldı.
- Rollback SQL ve schema_migrations cleanup statement'ı dahil.
- Geriye uyumluluk doğrulandı: tek aktif RPC çağıran (`Hzuyvr5EK6grSyY7`), çıktı şeması değişmiyor.
- Developer için statement-by-statement deploy listesi + sanity check + opsiyonel backfill SQL'i yazıldı.

🔄 **In Progress**
- Yok — spec final.

⚠️ **Blockers**
- Yok. Director onayı gerekmez (ADR-002 önceliği Solution_Analyst tarafından "orta" olarak verildi; Director sprint'e koyma kararı dışında engel yok).

📋 **Next Steps**
- Developer: Bölüm 7.1 deploy adımlarını uygula → migration LIVE.
- System_Tester: Migration sonrası Bölüm 4.1 + 4.2 testlerini staging clone'da koş; sonra prod smoke.
- Solution_Analyst: Backfill (Bölüm 7.2) yapılsın mı kararı (Director ile birlikte).
- Architect (sonra): ADR-003 (`order_changes` audit log) spec — Director sprint önceliği bekliyor.
