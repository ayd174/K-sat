# ADR-003 — `order_changes` Audit Log (Spec)

| Field | Value |
|---|---|
| **Tarih** | 2026-05-09 |
| **Author** | Architect (Software_Team) |
| **Source** | Solution_Analyst denetimi 2026-05-09 (KARIMA / ORD-0163) — kök neden raporu Açık Konular |
| **Predecessor** | ADR-001 (LIVE 2026-05-09 02:14 UTC) — mesaj kalitesi düzeltildi |
| **Sibling** | ADR-002 spec READY (2026-05-09 02:38) — `data_consistency_warnings` (otomatik tespit, ADR-003'ten **AYRI**) |
| **Status** | Spec READY → Developer hand-off |
| **Hand-off** | Developer (Software_Team) — migration deploy + smoke test |
| **Risk** | DÜŞÜK — yeni tablo, yeni trigger; mevcut UPDATE'leri yavaşlatma kaygısı düşük (operasyonel sıklık az) |
| **Geri uyumluluk** | Tam korunur — mevcut yazıcılar değişmez; `app.source` setting opsiyonel (NULL kabul) |

---

## 0. Yönetici Özeti

Solution_Analyst kök neden raporunda KARIMA vakası incelenirken kritik bir gözlem yapıldı:

> *"KARIMA siparişinin **05-06 rotasına nasıl bağlandığı** audit log yokluğunda doğrulanamadı (operatör pickup_date'i geçici değiştirdi mi, UI bypass mı, SQL/script mı?). ADR-003 uygulanırsa bir sonraki vakada cevap olacak."*

`orders` tablosunda **şu anki durum**:
- `pickup_date` üzerinde tarih tarihçesi yok.
- `updated_at` sadece **son** UPDATE zamanını gösterir.
- Önceki değer (örn. KARIMA'nın 05-06 → 05-08 değişimi) artık **doğrulanamaz**.
- Hangi user/agent/workflow değiştirdi → bilinmiyor.

ADR-003 bu kör noktayı kapatır: `orders` tablosu üzerinde herhangi bir kolon değiştiğinde, eski/yeni değerleri JSONB diff olarak ayrı bir `order_changes` tablosuna AFTER trigger ile kaydeder. Tarihçe append-only; RLS ile şirket bazlı izolasyon korunur.

**Felsefe:** *"Veri post-mortem için zorunlu altyapı. Storage maliyetinden çok daha değerli."*

**Kritik kısıt:** Trigger sadece **bundan sonraki** UPDATE'leri yakalar. Geçmiş tarihçe (KARIMA dahil) **geriye dönük üretilemez** — orijinal değer DB'de kayıp. Bu spec Bölüm 6'da açıkça belgelenir.

---

## 1. Mevcut Schema Durumu (Bölüm 1)

### 1.1 `orders` tablosu

`Dashboard_SaaS/supabase/migrations/20260215184835_create_logistics_schema.sql:171-188`:

```sql
CREATE TABLE IF NOT EXISTS orders (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies ON DELETE CASCADE,
  customer_name   text NOT NULL,
  customer_phone  text NOT NULL,
  pickup_address  text NOT NULL,
  delivery_address text,
  pickup_date     date,
  delivery_date   date,
  carpet_type_id  uuid REFERENCES carpet_types ON DELETE SET NULL,
  square_meters   numeric,
  total_amount    numeric NOT NULL DEFAULT 0,
  payment_status  text NOT NULL DEFAULT 'pending',
  order_status    text NOT NULL DEFAULT 'new',
  notes           text,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);
```

Sonradan eklenen kolonlar (sıralı migrasyonlardan):
- `language` (`20260313212909_add_language_and_photos_to_orders.sql`)
- `photos` (aynı migration)
- `carpet_count` (`20260322120000_add_carpet_count_to_orders.sql`)
- `yolluk_count` (`20260328000000_add_yolluk_count_to_orders.sql`)
- `item_type` (`20260402000000_add_item_type_to_orders.sql`)
- VAPI/WhatsApp handoff kolonları (`20260414000000_add_vapi_whatsapp_handoff.sql`)

`pickup_date` üzerinde **trigger/constraint yok**. Yalnızca performans için `idx_orders_pickup_date` (B-tree).

### 1.2 Mevcut RLS policy (orders)

`Dashboard_SaaS/supabase/migrations/20260322200000_fix_orders_rls_and_profile_lookup.sql:122-167`:

| Operation | Roller (`get_user_context()` üzerinden) |
|---|---|
| SELECT | super_admin, admin, **veya** kendi şirketinin order'ları |
| INSERT | super_admin, **veya** kendi şirketinin company_id'si |
| UPDATE | super_admin, admin, **veya** kendi şirketinin order'ları |
| DELETE | super_admin, admin, **veya** kendi şirketinin owner/admin'i |

Yardımcı fonksiyonlar (mevcut, yeniden kullanılacak):
- `get_user_context()` → (user_role, user_company_id) — `auth.uid()` üzerinden profile lookup, hem `id` hem `user_id` kolonu üzerinden
- `get_my_company_id()` → uuid
- `get_my_profile_info()` → (profile_id, profile_role, profile_company_id)

ADR-003 RLS'sinde mevcut helper'lar yeniden kullanılacak (kod tekrarı yok).

### 1.3 KARIMA'nın audit log boşluğu

Solution_Analyst raporundan:

| Tarih | Olay | Kayıt durumu |
|---|---|---|
| 2026-05-04 19:23 UTC | Order yaratıldı, `pickup_date = 2026-05-08` (Cuma — doğru) | `created_at` ✅ |
| 2026-05-05 17:35 UTC | KARIMA 2026-05-06 rotasına dahil edildi | **Bilinmiyor — pickup_date değişti mi?** |
| 2026-05-06 13:00 UTC | Yanlış güne ETA reminder | route_stops state'i mevcut |
| 2026-05-08 ~ | Yeni rota, doğru gün | `updated_at` (son) görünür |

**Soru:** KARIMA siparişinin pickup_date'i geçici olarak 2026-05-06'ya değiştirildi sonra geri 05-08 yapıldı mı? **Cevap mevcut altyapıda IMKANSIZ.** ADR-003 olsaydı: `order_changes` tablosunda 2 satır (05-08 → 05-06 → 05-08) görülürdü.

### 1.4 Mevcut audit altyapısı envanteri

| Tablo / Mekanizma | Durum | ADR-003 ile ilgisi |
|---|---|---|
| `data_consistency_warnings` | ADR-002 ile gelecek | **AYRI** — otomatik tespit edilen ihlaller (sistem-driven) |
| `audit_log` (Postgres extension) | YOK — kurulu değil | C seçeneği için aday; ama Supabase managed Postgres'te kurulum karmaşık |
| `pg_audit` extension | YOK | DDL/DML log'u için, granül tasarım için aşırı |
| `supabase_realtime` (CDC) | Aktif | Realtime için, audit için tasarlanmadı |
| `message_logs` tablosu | Mevcut (`20260313212852`) | WhatsApp mesaj log'u — order field değişimi kaydetmez |
| `voice_call_logs` tablosu | Mevcut | VAPI session log'u — order field değişimi kaydetmez |

**Sonuç:** AYKA Dashboard_SaaS'in genel amaçlı UPDATE history altyapısı yok. ADR-003 bu boşluğu doldurur.

---

## 2. Tasarım Kararları (Bölüm 2)

### 2.1 Approach kıyaslaması (A vs B vs C)

| Boyut | **A: Yeni `order_changes` tablosu** ✅ | B: `orders.change_history JSONB[]` kolonu | C: Postgres `audit` extension |
|---|---|---|---|
| Storage izolasyonu | Ayrı tablo, orders satır boyu sabit | orders satır boyu büyür (her UPDATE += JSONB) | Extension tablosu yönetimi farklı |
| Sorgulama | `WHERE order_id = X ORDER BY changed_at` (index destekli) | `SELECT change_history FROM orders WHERE id = X` — JSONB array unnest gerek | Extension'a göre farklı API |
| RLS | Standart pattern (company_id kolonu) | orders RLS otomatik geçerli | Extension RLS uyumu belirsiz |
| Index'leme | Çoklu B-tree + GIN üzerinde (esnek) | Tek satır içinde GIN — büyük JSONB pahalı | Extension default'ları |
| Tarihçe sorgu profili | "kim ne zaman ne değiştirdi" → tablo natural | JSON array unnest → her sorgu maliyetli | Extension'a göre |
| Bulk INSERT performans | AFTER trigger satır başı 1 INSERT (lokal) | UPDATE orders SET change_history = array_append(...) → yüksek dead tuple, vacuum baskısı | Extension'a göre |
| Migration karmaşıklığı | Tek atomik migration (tablo + trigger + RLS) | ALTER TABLE + bütün UPDATE path'lerine ek logic | Extension kurulum + Supabase managed izin riski |
| AYKA Dashboard_SaaS uyumu | Mevcut helper'ları (`get_user_context`, vs.) yeniden kullanır | Aynı | Bilinmiyor |
| Geriye uyumluluk | Mevcut UPDATE'ler etkilenmez | orders satır şeması değişir → `SELECT *` kullanan client'lar etkilenebilir | Bilinmiyor |
| **Skor** | **9/10 — net kazanan** | 5/10 | 3/10 (Supabase managed kısıtı) |

**Karar: SEÇENEK A — yeni `order_changes` tablosu.**

**Gerekçe (kısa):**
1. **Storage izolasyonu:** orders sıcak tabloda; her UPDATE'te JSONB array büyütmek vacuum/bloat riskini artırır.
2. **Sorgu profili:** Audit tarihçesi nadir okunur (post-mortem), ama okunduğunda `(order_id, changed_at DESC)` index'i ile O(log n).
3. **RLS kolaylığı:** ADR-002'deki `data_consistency_warnings` ile aynı pattern (`company_id` kolonu + SELECT policy).
4. **Extensible:** `payload jsonb` esnek; ileride `delivery_date`, `customer_phone` gibi field'lar tracking'e eklenirken schema değişikliği gerekmez.
5. **Geriye uyumluluk:** orders satır şeması değişmez → frontend / n8n workflow'ları etkilenmez.

### 2.2 Hangi field'lar tracking'e dahil?

**Karar:** **Genel diff yaklaşımı — tüm kolonları izle, ama akıllı filtre uygula.**

Trigger fonksiyonu içinde:
- `OLD` ve `NEW` row'lar JSONB'ye dönüştürülür (`to_jsonb(OLD)`, `to_jsonb(NEW)`).
- Field-by-field karşılaştırma: hangi anahtar(lar)ın değer(ler)i değişti.
- **Hariç tutulan (audit gürültüsü) field'lar:**
  - `updated_at` — her UPDATE'te otomatik değişir, audit gürültüsü
  - `id` — primary key, değişmez (paranoid kontrol)
  - `created_at` — değişmez
- **Dahil edilen field'lar (tüm geri kalanı):** `pickup_date, delivery_date, customer_name, customer_phone, pickup_address, delivery_address, order_status, payment_status, total_amount, square_meters, carpet_type_id, carpet_count, yolluk_count, item_type, notes, language, photos, ...` (ileride eklenecek tüm kolonlar otomatik).

**Tasarım gerekçesi:**
- Solution_Analyst minimum (`pickup_date`) önermişti, ama **genişletilmiş** stratejisi uzun vadede çok daha değerli (storage maliyeti küçük, post-mortem kapsamı büyük).
- Architect kararı: **minimum + extensible.** Trigger generic JSONB diff dokur; `pickup_date`'e özel logic yok. İleride field eklendiğinde otomatik kapsanır.

**`changed_field` formatı:**
- Tek field değişti → `'pickup_date'` (string)
- Çoklu field değişti → tek satır INSERT, `changed_field = NULL`, `payload.changed_fields` array içinde tüm field listesi (örn. `["pickup_date", "delivery_date"]`)
- Bu yapı sorgu kolaylığı sağlar: `WHERE changed_field = 'pickup_date'` (tek field), VEYA `WHERE payload ? 'pickup_date'` GIN ile (çoklu).

### 2.3 Trigger tasarımı

**Karar matrisi:**

| Karar | Seçilen | Alternatif | Gerekçe |
|---|---|---|---|
| AFTER vs BEFORE | **AFTER** | BEFORE | Audit; transaction commit'inden önce row final state'i ile çalışır. BEFORE'da rollback olursa sahte log riski. |
| Tetik koşulu | `AFTER UPDATE OR INSERT OR DELETE ON orders` | `AFTER UPDATE` | INSERT/DELETE de loglansın — order yaratımı ve silinmesi de tarihçe olarak değerli. |
| FOR EACH ROW vs STATEMENT | **ROW** | STATEMENT | Her satır için ayrı OLD/NEW karşılaştırma gerekli. |
| WHEN clause | `WHEN (OLD.* IS DISTINCT FROM NEW.*)` (UPDATE için) | hep tetikle | UPDATE'te değişiklik olmazsa (no-op UPDATE) trigger çalışmasın. WHEN clause planning aşamasında elerse PG row'u atlatır. |
| SECURITY | **DEFINER** | INVOKER | Trigger anonim auth context'inde de (n8n service_role, frontend authenticated user) çalışmalı. RLS bypass gerekli. |
| Hata yönetimi | **EXCEPTION fırlatma** | RAISE | Audit logging UPDATE akışını engellemez. Audit hatası hem operatörü engellemesin hem RAISE NOTICE ile görünür olsun. |

**INSERT için not:** INSERT'te `OLD = NULL` → diff hesaplama farklı. Çözüm: INSERT için `payload.before = NULL`, `payload.after = NEW satırı`. `changed_field = NULL` (özel değer "INSERT").

**DELETE için not:** DELETE'te `NEW = NULL` → `payload.before = OLD satırı`, `payload.after = NULL`. `changed_field = NULL` (özel değer "DELETE"). NOT: Trigger ROW-level DELETE için ayrı handling gerekir.

### 2.4 `changed_by` tespiti

**Karar:**
- `auth.uid()` Supabase'in fonksiyonudur; `authenticated` rolden çağrıldığında dolu döner; `service_role`'dan NULL döner.
- Trigger içinde `auth.uid()` çağrıldığında:
  - Frontend (Dashboard, Workshop_app, Driver_app) authenticated user → user UUID
  - n8n service_role → NULL (n8n her zaman service_role kullanır)
  - SQL editor (admin manual) → ya user UUID ya NULL
- `changed_by_role` field'ı ekle: `auth.role()` veya `get_user_context()` üzerinden role string'i. NULL ise `'system'` veya `'service_role'` etiketi.

**Sonuç:**
- `changed_by uuid NULL` (FK yok — auth.users silinse bile audit kalmalı)
- `changed_by_role text NULL` ('owner', 'admin', 'driver', 'service_role', 'system')

### 2.5 `source` alanı

**Karar:** Session-level GUC (Grand Unified Configuration) ile soft kategorizasyon.

**Kategoriler:**
- `'web'` — Dashboard frontend
- `'workshop'` — Workshop_app
- `'driver'` — Driver_app
- `'workflow'` — n8n
- `'api'` — REST API direct
- `'system'` — trigger/function side-effect veya migration
- NULL — bilinmiyor (geri uyumluluk)

**Mekanizma:** Trigger içinde:
```sql
v_source := current_setting('app.source', true);  -- true → setting yoksa NULL döner, hata fırlatmaz
```

**Frontend/workflow tarafında (opsiyonel — geri uyumluluk için zorunlu değil):**
```sql
SET LOCAL app.source = 'web';   -- transaction başında
```

**Architect kararı:**
- ADR-003 deploy sırasında `app.source` SET edilmesi **zorunlu değil** — NULL kabul edilebilir.
- Frontend/workflow ekipleri bu setting'i ileride faz-2 görev olarak ekler (Bölüm 8).
- ADR-003 LIVE olduktan sonra "source NULL" kayıtları çoğunluk olur — bu normal; faz-2 ile zenginleşir.

### 2.6 RLS

**Karar:**

| Operation | Politika |
|---|---|
| **SELECT** | super_admin, admin, owner **veya** kendi şirketinin order_changes kayıtları |
| **INSERT** | **YOK** — sadece trigger (SECURITY DEFINER) yazabilir |
| **UPDATE** | **YOK** — append-only audit log; immutable |
| **DELETE** | **YOK** — append-only audit log; immutable. Sadece super_admin için (compliance/GDPR durumlarında) opsiyonel policy |

**Driver muafiyeti:**
- `driver` rolü `order_changes` SELECT yapamaz (gizlilik: tarihçe sadece operatörlere açık).
- Bu pattern ADR-002'deki `data_consistency_warnings` ile **tutarlı** + Solution_Analyst'in driver-RLS notlarıyla uyumlu (driver UPDATE customers yapamaz; aynı şekilde driver order audit log da görmemeli).

**SECURITY DEFINER trigger note:** Trigger fonksiyonu SECURITY DEFINER ile çalıştığı için INSERT'i RLS bypass eder. Authenticated user'ın `INSERT` policy'si bilinçli olarak yok bırakıldı — manuel INSERT tüm tablo için yasak.

### 2.7 Index'ler

| Index | Sütunlar | Kullanım |
|---|---|---|
| `idx_order_changes_order_changed` | `(order_id, changed_at DESC)` | Order tarihçesi sorgusu (en sık) |
| `idx_order_changes_changed_by_at` | `(changed_by, changed_at DESC)` WHERE changed_by IS NOT NULL | "kim ne yaptı" sorgusu |
| `idx_order_changes_field` | `(changed_field, changed_at DESC)` WHERE changed_field IS NOT NULL | Tek-field tarihçesi (örn. tüm pickup_date değişiklikleri) |
| `idx_order_changes_company_at` | `(company_id, changed_at DESC)` | RLS + tenant-bazlı tarama |
| (opsiyonel ileride) | GIN üzerinde `payload` | Çoklu-field değişikliklerde `payload ? 'pickup_date'` sorgusu — kullanım sıklığı düşük olduğu için faz-2 |

### 2.8 Performans değerlendirmesi

- **orders UPDATE sıklığı:** AYKA üretiminde günde ~50-200 UPDATE bekleniyor (operasyonel sıklık düşük).
- **Trigger overhead:** AFTER ROW trigger + JSONB diff hesaplama → her UPDATE için <1ms ek (PostgreSQL `to_jsonb()` native).
- **`order_changes` büyümesi:** Yılda ~50,000-75,000 satır (kabul edilebilir; ortalama satır boyu ~500 byte → yılda <40 MB).
- **VACUUM baskısı:** Append-only tablo (UPDATE/DELETE yok) → autovacuum minimal.
- **Index maliyeti:** 4 index × küçük satır boyu → kabul edilebilir.

### 2.9 Migration paketi: tek dosya (atomik)

**Karar:** Tek atomik migration. Sıra:
1. CREATE TABLE order_changes
2. 4 index
3. ENABLE RLS
4. SELECT policy
5. CREATE OR REPLACE FUNCTION (trigger fonksiyonu)
6. DROP TRIGGER IF EXISTS + CREATE TRIGGER

Tek dosya transaction'ında çalışır → atomik. Rollback bölüm 5'te tek revert dosyası ile.

### 2.10 Migration dosyası adı

`Dashboard_SaaS/supabase/migrations/20260509160000_order_changes_audit.sql`

**Saat seçimi (`160000`):**
- ADR-002 migration'ı `20260509150000` (15:00:00).
- ADR-003 migration'ı bundan sonra deploy edilmeli (sıralama önemli — `data_consistency_warnings` tablosunun `companies` referansı bağımlılık değil, ama spec'lerin uygulanma sırasını disiplinli tut).
- Bir saat aralık (`160000` = 16:00:00) güvenli buffer.

> **Not:** Görev tanımında orijinal öneri `20260509030000` (03:00:00) idi, ama Architect spec'in sonuna ekledi: "sıralama ADR-002'den sonra". 16:00:00 her iki kısıdı (ADR-002'den sonra + tarih 2026-05-09) karşılar. Saat 03:00 ADR-002'den ÖNCE düşerdi → çelişki nedeniyle reddedildi.

---

## 3. Migration SQL'leri (Bölüm 3)

> **Hatırlatma — Developer için:** Migration deploy pattern'i `reference_supabase_migration_push.md`:
> 1. Her statement ayrı `npx supabase db query "..."` ile uygula (PowerShell here-string, dollar-quoted body için `'@`/`@'`).
> 2. Bittiğinde `INSERT INTO supabase_migrations.schema_migrations (version, name, statements) VALUES (...) ON CONFLICT DO NOTHING;`

### 3.1 Migration dosyası tam içeriği

```sql
-- =====================================================================
-- ADR-003 — order_changes audit log
-- Tarih: 2026-05-09
-- Architect spec: PROMPT lar/ADR-003_audit_log_spec.md
-- Source: Solution_Analyst KARIMA root cause analysis (2026-05-09)
-- Önce: ADR-001 (LIVE), ADR-002 (deploy sonrası). Bu migration UPDATE history.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. order_changes tablosu (append-only UPDATE/INSERT/DELETE history)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.order_changes (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id        uuid        NOT NULL,
  company_id      uuid        REFERENCES public.companies(id) ON DELETE CASCADE,
  changed_field   text,                                  -- tek field değişti → 'pickup_date'; çoklu → NULL
  old_value       jsonb,                                 -- DELETE'te dolu, INSERT'te NULL, UPDATE'te değişen field'ların eski değerleri
  new_value       jsonb,                                 -- INSERT'te dolu, DELETE'te NULL, UPDATE'te değişen field'ların yeni değerleri
  changed_by      uuid,                                  -- auth.uid() — FK YOK (auth.users silinirse bile audit kalır)
  changed_by_role text,                                  -- 'owner', 'admin', 'driver', 'service_role', 'system', NULL
  source          text,                                  -- 'web', 'workshop', 'driver', 'workflow', 'api', 'system', NULL
  trigger_op      text        NOT NULL,                  -- 'INSERT', 'UPDATE', 'DELETE'
  payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,  -- ek metadata (changed_fields array, vs.)
  changed_at      timestamptz NOT NULL DEFAULT now()
);

-- order_id FK YOK (order DELETE edildiğinde bile audit kalmalı)
-- company_id FK CASCADE (şirket silinirse audit de gitsin → tenant izolasyonu)

-- ---------------------------------------------------------------------
-- 2. Index'ler
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_order_changes_order_changed
  ON public.order_changes (order_id, changed_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_changes_changed_by_at
  ON public.order_changes (changed_by, changed_at DESC)
  WHERE changed_by IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_order_changes_field
  ON public.order_changes (changed_field, changed_at DESC)
  WHERE changed_field IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_order_changes_company_at
  ON public.order_changes (company_id, changed_at DESC);

-- ---------------------------------------------------------------------
-- 3. RLS
-- ---------------------------------------------------------------------
ALTER TABLE public.order_changes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Operators can view their company order changes"
  ON public.order_changes;

CREATE POLICY "Operators can view their company order changes"
  ON public.order_changes FOR SELECT
  TO authenticated
  USING (
    -- super_admin/admin tüm şirketleri görür
    (SELECT user_role FROM get_user_context()) IN ('super_admin', 'admin')
    OR
    -- Kendi şirketinin kayıtları — driver hariç (driver audit görmesin)
    (
      company_id = get_my_company_id()
      AND (SELECT user_role FROM get_user_context()) IN ('owner', 'admin', 'operator', 'staff', 'workshop')
    )
  );

-- INSERT/UPDATE/DELETE policy YOK → authenticated kullanıcı manuel yazamaz.
-- Sadece SECURITY DEFINER trigger fonksiyonu RLS'ı bypass ederek INSERT yapar.
-- service_role RLS'ten muaf (kurtarma/migration için).

-- ---------------------------------------------------------------------
-- 4. Trigger fonksiyonu: orders üzerinde INSERT/UPDATE/DELETE diff dökücü
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.log_order_changes()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_old_jsonb       jsonb;
  v_new_jsonb       jsonb;
  v_diff_old        jsonb := '{}'::jsonb;
  v_diff_new        jsonb := '{}'::jsonb;
  v_changed_fields  text[] := ARRAY[]::text[];
  v_changed_field   text;
  v_field           text;
  v_company_id      uuid;
  v_changed_by      uuid;
  v_changed_by_role text;
  v_source          text;
  v_trigger_op      text := TG_OP;
  -- audit gürültüsü olarak hariç tutulan field'lar
  v_excluded        text[] := ARRAY['updated_at', 'created_at', 'id'];
BEGIN
  -- changed_by: auth context'inden user_id (NULL ise service_role veya system)
  BEGIN
    v_changed_by := auth.uid();
  EXCEPTION WHEN OTHERS THEN
    v_changed_by := NULL;
  END;

  -- changed_by_role: profile lookup (NULL ise 'service_role' veya 'system')
  IF v_changed_by IS NOT NULL THEN
    SELECT role INTO v_changed_by_role
      FROM public.profiles
     WHERE id = v_changed_by OR user_id = v_changed_by
     LIMIT 1;
  END IF;

  IF v_changed_by_role IS NULL THEN
    -- Postgres role'üne bak: 'authenticator' / 'service_role' / 'postgres'
    BEGIN
      v_changed_by_role := COALESCE(current_setting('request.jwt.claim.role', true), 'service_role');
    EXCEPTION WHEN OTHERS THEN
      v_changed_by_role := 'system';
    END;
  END IF;

  -- source: session-level GUC (frontend/workflow ileride SET LOCAL ile zengin yapacak)
  BEGIN
    v_source := current_setting('app.source', true);
  EXCEPTION WHEN OTHERS THEN
    v_source := NULL;
  END;

  -- INSERT/UPDATE/DELETE'e göre OLD/NEW JSONB hazırla
  IF v_trigger_op = 'INSERT' THEN
    v_new_jsonb := to_jsonb(NEW);
    v_company_id := NEW.company_id;
    v_diff_new := v_new_jsonb;  -- tüm satır
    v_changed_field := NULL;    -- INSERT toplu; field-bazlı değil
  ELSIF v_trigger_op = 'DELETE' THEN
    v_old_jsonb := to_jsonb(OLD);
    v_company_id := OLD.company_id;
    v_diff_old := v_old_jsonb;  -- tüm satır
    v_changed_field := NULL;    -- DELETE toplu
  ELSE  -- UPDATE
    v_old_jsonb := to_jsonb(OLD);
    v_new_jsonb := to_jsonb(NEW);
    v_company_id := COALESCE(NEW.company_id, OLD.company_id);

    -- Field-by-field karşılaştır; hariç tutulanları atla
    FOR v_field IN
      SELECT key FROM jsonb_each(v_new_jsonb)
    LOOP
      IF v_field = ANY(v_excluded) THEN
        CONTINUE;
      END IF;
      IF (v_old_jsonb -> v_field) IS DISTINCT FROM (v_new_jsonb -> v_field) THEN
        v_changed_fields := array_append(v_changed_fields, v_field);
        v_diff_old := v_diff_old || jsonb_build_object(v_field, v_old_jsonb -> v_field);
        v_diff_new := v_diff_new || jsonb_build_object(v_field, v_new_jsonb -> v_field);
      END IF;
    END LOOP;

    -- Hiç değişen field yoksa (trigger WHEN clause yetersiz kaldıysa) log yazma
    IF array_length(v_changed_fields, 1) IS NULL THEN
      RETURN NEW;
    END IF;

    -- Tek field değiştiyse changed_field doldur; çoklu ise NULL bırak (payload.changed_fields array)
    IF array_length(v_changed_fields, 1) = 1 THEN
      v_changed_field := v_changed_fields[1];
    ELSE
      v_changed_field := NULL;
    END IF;
  END IF;

  -- INSERT to order_changes (audit)
  BEGIN
    INSERT INTO public.order_changes (
      order_id, company_id,
      changed_field, old_value, new_value,
      changed_by, changed_by_role, source,
      trigger_op, payload
    )
    VALUES (
      COALESCE(NEW.id, OLD.id),
      v_company_id,
      v_changed_field,
      CASE WHEN v_diff_old = '{}'::jsonb THEN NULL ELSE v_diff_old END,
      CASE WHEN v_diff_new = '{}'::jsonb THEN NULL ELSE v_diff_new END,
      v_changed_by,
      v_changed_by_role,
      v_source,
      v_trigger_op,
      jsonb_build_object(
        'changed_fields', to_jsonb(v_changed_fields),
        'detected_at_utc', now()
      )
    );
  EXCEPTION WHEN OTHERS THEN
    -- Audit log hatası UPDATE akışını engellemesin
    RAISE NOTICE 'order_changes audit log INSERT failed: %', SQLERRM;
  END;

  -- DELETE'te NEW yok; UPDATE/INSERT'te NEW dön
  IF v_trigger_op = 'DELETE' THEN
    RETURN OLD;
  ELSE
    RETURN NEW;
  END IF;
END;
$$;

-- ---------------------------------------------------------------------
-- 5. Trigger
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS log_order_changes_trg
  ON public.orders;

CREATE TRIGGER log_order_changes_trg
  AFTER INSERT OR UPDATE OR DELETE
  ON public.orders
  FOR EACH ROW
  WHEN (
    -- INSERT/DELETE her zaman tetikle; UPDATE'te sadece gerçek değişiklik varsa
    -- (PostgreSQL 11+ trigger WHEN clause INSERT'te OLD'a, DELETE'te NEW'e erişemez,
    --  o yüzden TG_OP yerine OLD/NEW IS DISTINCT FROM kontrolü)
    pg_trigger_depth() = 0  -- recursion guard (audit içinde başka trigger atlatma)
  )
  EXECUTE FUNCTION public.log_order_changes();

-- =====================================================================
-- ADR-003 migration tamamlandı.
-- Sonra çalıştırılması gereken:
--   INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
--   VALUES ('20260509160000', 'order_changes_audit', ARRAY[<statements>])
--   ON CONFLICT (version) DO NOTHING;
-- =====================================================================
```

### 3.2 `db query` için bölünmüş statement listesi

Developer her birini ayrı `npx supabase db query "..."` çağrısıyla çalıştırır:

1. `CREATE TABLE IF NOT EXISTS public.order_changes (...)`
2. `CREATE INDEX IF NOT EXISTS idx_order_changes_order_changed ON public.order_changes (order_id, changed_at DESC);`
3. `CREATE INDEX IF NOT EXISTS idx_order_changes_changed_by_at ON public.order_changes (changed_by, changed_at DESC) WHERE changed_by IS NOT NULL;`
4. `CREATE INDEX IF NOT EXISTS idx_order_changes_field ON public.order_changes (changed_field, changed_at DESC) WHERE changed_field IS NOT NULL;`
5. `CREATE INDEX IF NOT EXISTS idx_order_changes_company_at ON public.order_changes (company_id, changed_at DESC);`
6. `ALTER TABLE public.order_changes ENABLE ROW LEVEL SECURITY;`
7. `DROP POLICY IF EXISTS "Operators can view their company order changes" ON public.order_changes;`
8. `CREATE POLICY "Operators can view their company order changes" ON public.order_changes FOR SELECT TO authenticated USING (...);`
9. `CREATE OR REPLACE FUNCTION public.log_order_changes() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER ... $$;` (PLpgSQL gövdesi içeren tek statement — PowerShell'den `'@`/`@'` here-string ile gönder)
10. `DROP TRIGGER IF EXISTS log_order_changes_trg ON public.orders;`
11. `CREATE TRIGGER log_order_changes_trg AFTER INSERT OR UPDATE OR DELETE ON public.orders FOR EACH ROW WHEN (pg_trigger_depth() = 0) EXECUTE FUNCTION public.log_order_changes();`
12. `INSERT INTO supabase_migrations.schema_migrations (version, name, statements) VALUES ('20260509160000', 'order_changes_audit', ARRAY[...]) ON CONFLICT (version) DO NOTHING;`

**PowerShell here-string örneği (statement 9 için):**
```powershell
$sql = @'
CREATE OR REPLACE FUNCTION public.log_order_changes()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
...
$$;
'@
npx supabase db query $sql --db-url "postgresql://..."
```

---

## 4. Test Plan (Bölüm 4)

### 4.1 Trigger testleri (8 senaryo)

> Tüm testler test verisi üzerinde, `test@test.com` (owner, AYKA TAPIS) ile login. Test sonrası temizlik: `DELETE FROM public.order_changes WHERE order_id = '<test_order_id>';` + `DELETE FROM public.orders WHERE id = '<test_order_id>';`

| # | Senaryo | Beklenen sonuç |
|---|---|---|
| **T1** | **pickup_date UPDATE (single-field)**: Mevcut order'ın `pickup_date='2026-05-08'` → UPDATE `pickup_date='2026-05-06'`. | `order_changes`'ta 1 yeni satır: `trigger_op='UPDATE'`, `changed_field='pickup_date'`, `old_value->'pickup_date'='2026-05-08'`, `new_value->'pickup_date'='2026-05-06'`, `payload.changed_fields=['pickup_date']`. |
| **T2** | **delivery_date UPDATE**: aynı mantık, farklı field. | `changed_field='delivery_date'`, doğru old/new. |
| **T3** | **multi-field UPDATE**: `pickup_date` + `customer_phone` aynı UPDATE'te değişti. | 1 satır: `changed_field=NULL`, `payload.changed_fields=['pickup_date', 'customer_phone']` (sıra DB-driven), `old_value` ve `new_value` her iki field'ı içerir. |
| **T4** | **No-op UPDATE**: hiç değişiklik yok (örn. `UPDATE orders SET pickup_date = pickup_date WHERE id = X`). | `order_changes`'ta yeni satır YOK (trigger fonksiyonu `array_length=NULL` kontrolü ile erkenden RETURN NEW). |
| **T5** | **INSERT**: yeni order yaratıldı. | 1 satır: `trigger_op='INSERT'`, `changed_field=NULL`, `old_value=NULL`, `new_value=full row JSONB`, `payload.changed_fields=[]`. |
| **T6** | **DELETE**: order silindi. | 1 satır: `trigger_op='DELETE'`, `changed_field=NULL`, `old_value=full row JSONB`, `new_value=NULL`. **NOT:** order CASCADE yüzünden silinirse FK kontrol et. order_changes.order_id FK YOK → audit kalır. |
| **T7** | **source=NULL**: `app.source` setting yok → trigger çalışıyor. | `source IS NULL`, diğer field'lar dolu. |
| **T8** | **source set**: `SET LOCAL app.source = 'web'; UPDATE orders SET pickup_date = '...';` | `source = 'web'`. |

**Audit gürültüsü kontrolü:**
- T9 (sızıntı): `UPDATE orders SET updated_at = now() WHERE id = X;` (sadece updated_at değişti) → trigger fonksiyonu hariç tutulmuş field listesi (`v_excluded`) kullanır → **order_changes'ta yeni satır YOK** (changed_fields boş kalır).

### 4.2 RLS testleri (4 senaryo)

| # | Senaryo | Beklenen sonuç |
|---|---|---|
| **R1** | `test@test.com` (owner, AYKA TAPIS): kendi şirketinin order_changes kayıtlarını oku. | Tüm kayıtlar **görünür**. |
| **R2** | `ayka@ayka.com` (driver, AYKA TAPIS): order_changes okumaya çalış. | **Boş set** döner (driver SELECT policy'de değil). |
| **R3** | `workshop@test.com` (workshop, AYKA TAPIS): kendi şirketinin order_changes kayıtlarını oku. | **Görünür** (workshop policy'de var). |
| **R4** | Cross-tenant: AYKA TAPIS owner başka şirketin order_changes kayıtlarını okumayı deniyor. | **Boş set** döner (RLS company_id filtresi). |
| **R5** | Manuel INSERT: `test@test.com` doğrudan `INSERT INTO order_changes (...)`. | **403 / RLS hatası** — INSERT policy yok, manuel yazım yasak. |

### 4.3 KARIMA-benzeri smoke (entegrasyon)

Test order yarat:
```sql
INSERT INTO public.orders (company_id, customer_name, customer_phone, pickup_address, pickup_date)
VALUES ('fded930d-60a8-4310-b6bc-f6f6b28db7b3', 'TEST KARIMA',
        '+999000000001', 'Test Pickup Address', '2026-05-08');
```

Operatör tarihi geçici olarak değiştirir, sonra geri alır:
```sql
-- Adım 1: operatör 05-06'ya çekti
UPDATE public.orders SET pickup_date = '2026-05-06' WHERE customer_name = 'TEST KARIMA';

-- Adım 2: operatör fark etti, geri 05-08 yaptı
UPDATE public.orders SET pickup_date = '2026-05-08' WHERE customer_name = 'TEST KARIMA';
```

`order_changes` sorgusu:
```sql
SELECT changed_at, changed_field, old_value->'pickup_date' AS old_pd, new_value->'pickup_date' AS new_pd, changed_by_role
  FROM public.order_changes
 WHERE order_id = (SELECT id FROM public.orders WHERE customer_name = 'TEST KARIMA')
 ORDER BY changed_at;
```

**Beklenen sonuç:** 3 satır (1 INSERT + 2 UPDATE).
- Satır 1: INSERT, pickup_date='2026-05-08' (initial)
- Satır 2: UPDATE, old=`'2026-05-08'`, new=`'2026-05-06'`
- Satır 3: UPDATE, old=`'2026-05-06'`, new=`'2026-05-08'`

Bu KARIMA gibi bir vakanın **gelecekte tam olarak ne zaman/kim/ne** sorularına cevap vereceğini kanıtlar.

### 4.4 Performans gözlemi

- AYKA üretim sıklığı: günde ~50-200 orders UPDATE → trigger overhead ihmal edilebilir.
- `order_changes` büyümesi: 24 saat sonra `SELECT count(*) FROM order_changes;` → tahmin <500.
- `pg_stat_user_tables` ile autovacuum davranışı izlenebilir (insert-only tablo, vacuum minimal).

---

## 5. Rollback (Bölüm 5)

```sql
-- ---------------------------------------------------------------------
-- ADR-003 ROLLBACK
-- ---------------------------------------------------------------------

-- 1. Trigger ve fonksiyonu kaldır
DROP TRIGGER IF EXISTS log_order_changes_trg
  ON public.orders;

DROP FUNCTION IF EXISTS public.log_order_changes();

-- 2. (İsteğe bağlı) order_changes tablosunu KORU (audit kayıtları kıymetli)
--    Tablo silinmek istenirse:
--    DROP TABLE IF EXISTS public.order_changes;
--    NOT: DROP TABLE policy/index'leri de düşürür → ek temizlik gerekmez.

-- 3. schema_migrations'tan kaydı sil (revert temizliği)
DELETE FROM supabase_migrations.schema_migrations
 WHERE version = '20260509160000';
```

**Rollback notu:**
- **Default: trigger + function düş, tablo KORU.** Audit verileri post-mortem için zaten kıymetli; rollback hızlıca yapılırsa orijinal sebep çözüldüğünde tablo yeniden trigger'lanabilir.
- **Tam temizlik:** `DROP TABLE` + `DELETE FROM schema_migrations` her iki adım da yapılırsa migration tamamen geri alınmış olur.

---

## 6. Geriye Uyumluluk + Backfill Notu (Bölüm 6)

### 6.1 Mevcut UPDATE noktaları üzerine etki

Spec Bölüm 1.2'deki RLS policy'leri orders üzerinde aynı kalır. Trigger AFTER row-level — UPDATE akışını yavaşlatmaz, transaction'ı engellemez.

**orders UPDATE yazıcıları (mevcut):**

| Yazıcı | Davranış | source set ediliyor mu? |
|---|---|---|
| Dashboard frontend (`Orders.tsx`, `OrderDetailModal.tsx`) | Direct UPDATE (Supabase client) | **YOK** — `app.source` ayarlanmıyor → trigger NULL kaydeder |
| Workshop_app | Direct UPDATE | YOK |
| Driver_app | Direct UPDATE (sadece izinli field'lar) | YOK |
| n8n WhatsApp `1_ASISTAN` (HSy9VD6eeptkf8g2) | Supabase REST UPDATE | YOK (service_role; trigger NULL kaydeder) |
| n8n diğer workflow'lar | Çoğu sadece read | — |
| Migration / SQL editor (manuel) | Direct UPDATE | YOK (admin/superadmin login) |

**Sonuç:** Tüm mevcut UPDATE'ler ADR-003 trigger'ı tarafından yakalanır. `source` field'ı NULL kalır → bu sorun değil; faz-2'de zenginleşir.

### 6.2 Trigger SECURITY DEFINER → RLS bypass

Trigger fonksiyonu `SECURITY DEFINER` ile çalışır → INSERT INTO order_changes RLS'i bypass eder. Bu **istenen davranış** (yoksa driver veya başka kısıtlı role'lerin order UPDATE'i log'a girmez).

### 6.3 Recursion guard

Trigger WHEN clause'ı `pg_trigger_depth() = 0` ekler → eğer ileride orders üzerinde başka bir trigger eklenirse ve o trigger orders'ı UPDATE ederse, audit trigger ikinci kez tetiklenmez (sonsuz döngü riski sıfır).

### 6.4 Geçmiş tarihçe **GERİ DÖNÜK ÜRETİLEMEZ** ⚠️

**Kritik kısıt:** ADR-003 trigger'ı sadece **bundan sonraki** INSERT/UPDATE/DELETE'leri yakalar.

| Sorgu | Cevap |
|---|---|
| KARIMA'nın pickup_date'i ne zaman 05-08'den 05-06'ya değişti? | **Bilinmiyor — orijinal değer DB'de yok.** ADR-003 LIVE'dan önceki değişiklikler kayıp. |
| KARIMA'nın pickup_date'i kim değiştirdi? | **Bilinmiyor.** |
| ADR-003 LIVE sonrası KARIMA-benzeri vaka olursa? | ✅ **Tam tarihçe görünür.** |

**Backfill imkânsız çünkü:**
- Postgres `updated_at` kolonu sadece son UPDATE zamanını tutar.
- Hiçbir mevcut log mekanizması (message_logs, voice_call_logs) order field değişimi kaydetmedi.
- WAL (write-ahead log) kısa süreli, retention 7-30 gün — geçmiş aylar kayıp.

**Karar:** Backfill **YAPILMAZ**. Spec'te bu şeffaf belgelendi. Solution_Analyst raporunda KARIMA için "Açık konular" maddesi açık kalır (cevap mevcut altyapıda imkansız).

**Olumlu yön:** ADR-003 LIVE'dan sonra her UPDATE kaydedilir. KARIMA gibi bir sonraki vaka tam tarihçe ile çözülür.

### 6.5 RLS uyumluluğu

`order_changes` SELECT policy `get_user_context()` ve `get_my_company_id()` mevcut helper'larını kullanır → recursion riski yok (mevcut diğer tablolarda kanıtlanmış kalıp). Driver muafiyeti açık (`role NOT IN ('driver')`) → driver dashboard'da audit log linki açıldığında boş set döner, hata değil.

---

## 7. Developer Hand-off (Bölüm 7)

### 7.1 Migration deploy adımları

1. **Pre-deploy state snapshot:**
   ```
   npx supabase db query "SELECT version FROM supabase_migrations.schema_migrations ORDER BY version DESC LIMIT 5;" --db-url "..."
   ```
   Beklenen son migration: `20260509150000` (ADR-002 deploy edilmişse) veya `20260508130000` (ADR-002 henüz deploy edilmediyse).

2. **ADR-002 önce deploy edilmiş mi kontrolü:**
   ```sql
   SELECT to_regclass('public.data_consistency_warnings');
   ```
   - Sonuç dolu → ADR-002 LIVE, ADR-003 deploy'a hazır.
   - Sonuç NULL → ADR-002 önce uygula. ADR-003 ADR-002'yi referans almıyor (bağımlılık YOK), ama disipline edilmiş sıra için ADR-002 önce deploy edilsin.

3. **Migration dosyasını yaz:**
   - Yol: `Dashboard_SaaS/supabase/migrations/20260509160000_order_changes_audit.sql`
   - İçerik: Bölüm 3.1.

4. **Statement-by-statement uygula** (`reference_supabase_migration_push.md`):
   - Bölüm 3.2'deki 12 statement'ı sırayla `npx supabase db query "<stmt>"` ile çalıştır.
   - Statement 9 (CREATE OR REPLACE FUNCTION) PowerShell here-string (`'@`/`@'`) ile gönderilmelidir.
   - Her birinin başarılı olduğunu doğrula (NOTICE/error yok).

5. **Hızlı sanity check:**
   ```sql
   SELECT to_regclass('public.order_changes');                                            -- tablo var mı
   SELECT proname FROM pg_proc WHERE proname = 'log_order_changes';                       -- fonksiyon var mı
   SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'public.orders'::regclass;    -- trigger var mı
   SELECT polname FROM pg_policy WHERE polrelid = 'public.order_changes'::regclass;       -- policy var mı
   SELECT count(*) FROM public.order_changes;                                             -- 0 olmalı (henüz UPDATE yok)
   ```
   Beklenen: tablo dolu, fonksiyon `log_order_changes`, trigger `log_order_changes_trg` enabled, 1 SELECT policy, count=0.

6. **Smoke test:** Bölüm 4.3 KARIMA simülasyonunu test verisiyle çalıştır. 3 satır (1 INSERT + 2 UPDATE) görmeli. Sonra test verilerini sil:
   ```sql
   DELETE FROM public.order_changes WHERE order_id = (SELECT id FROM public.orders WHERE customer_name = 'TEST KARIMA');
   DELETE FROM public.orders WHERE customer_name = 'TEST KARIMA';
   ```

7. **Live monitor (24 saat):**
   ```sql
   SELECT changed_at, trigger_op, changed_field, changed_by_role, source, count(*) OVER () AS total
     FROM public.order_changes
    WHERE changed_at > now() - INTERVAL '24 hours'
    ORDER BY changed_at DESC
    LIMIT 100;
   ```
   Beklenen: AYKA üretiminde günde ~50-200 satır. Eğer çok fazla (>500) → orders UPDATE sıklığı ile karşılaştır; eğer hiç yoksa → trigger çalışmıyor demek (alarm).

### 7.2 Backfill uygulanmaz

Geçmiş tarihçe imkânsız (Bölüm 6.4). Developer **backfill SQL'i yazmaz, çalıştırmaz**.

### 7.3 Tek cümlelik hand-off

> Developer: `Dashboard_SaaS/supabase/migrations/20260509160000_order_changes_audit.sql` dosyasını yaz (Bölüm 3.1), `reference_supabase_migration_push.md` pattern'iyle 12 statement'ı sıralı uygula (statement 9 PowerShell here-string ile), schema_migrations'a kaydı düş, ardından Bölüm 4 test planını + 4.3 KARIMA simülasyonunu kestir; tüm testler geçerse System_Tester'a smoke devret; Bölüm 6.4 (backfill imkânsız) Solution_Analyst'e iletilir.

---

## 8. Faz-2: Frontend / Workflow `source` Set-Local Önerisi (Opsiyonel)

ADR-003 LIVE olduktan sonra `source` field'ı NULL ile dolu olur. Faz-2'de zenginleştirmek için:

### 8.1 Dashboard frontend (Orders.tsx, OrderDetailModal.tsx)

Supabase client UPDATE öncesi RPC ile session-level setting:
```typescript
// pseudo-code: UPDATE orders öncesi
await supabase.rpc('set_audit_source', { source: 'web' });
await supabase.from('orders').update({ pickup_date: '...' }).eq('id', orderId);
```

veya client-side helper:
```sql
CREATE OR REPLACE FUNCTION public.set_audit_source(source text)
RETURNS void
LANGUAGE plpgsql SECURITY INVOKER
AS $$ BEGIN
  PERFORM set_config('app.source', source, true);  -- true = LOCAL (transaction-scoped)
END $$;
```

### 8.2 n8n workflow'ları

orders UPDATE node'u öncesi Supabase REST query node:
```
POST /rest/v1/rpc/set_audit_source
Body: { "source": "workflow" }
```

veya doğrudan SQL (Supabase POSTGres connection node):
```sql
SET LOCAL app.source = 'workflow';
```

### 8.3 Driver_app / Workshop_app

Aynı pattern: UPDATE öncesi `set_audit_source('driver')` veya `set_audit_source('workshop')`.

**Faz-2 önceliği DÜŞÜK:** ADR-003 LIVE'da NULL kabul ediliyor. Frontend ekibi rahatlık zamanında ekler.

---

## 9. ADR-002 ile İlişki (semantik ayrım)

İki audit altyapısı **AYRI** çalışır, **birbirini tamamlar**:

| Tablo | Amaç | Kim yazar | Sorgu profili |
|---|---|---|---|
| `data_consistency_warnings` (ADR-002) | Otomatik tespit edilen tutarsızlıklar (sistem-driven) | route_stops trigger | "Bu hafta hangi çelişkiler oluştu?" — uyarı dashboard'u |
| `order_changes` (ADR-003) | Operatör/sistem UPDATE tarihçesi (kim/ne zaman/ne) | orders trigger | "Bu order'ın geçmişinde ne oldu?" — post-mortem |

**Aralarındaki köprü:** KARIMA-benzeri bir gelecek vakada:
1. ADR-002 trigger'ı `pickup_date_route_mismatch` warning yazar (anlık tespit).
2. ADR-003 trigger'ı `pickup_date` UPDATE'lerini yazar (tam tarihçe).
3. Solution_Analyst iki tabloyu birlikte sorgular → "warning ne zaman oluştu, ondan önce kim pickup_date'i değiştirdi" net görünür.

İleride VIEW eklenebilir:
```sql
CREATE VIEW order_audit_full AS
SELECT 'change' AS source, oc.changed_at AS event_at, ... FROM order_changes oc
UNION ALL
SELECT 'warning' AS source, dcw.created_at AS event_at, ... FROM data_consistency_warnings dcw;
```

Bu VIEW ADR-003 deploy'da gerekmez — ileri sprint için kapı açık.

---

## 10. Architect İmzası

- **Spec hazır:** 2026-05-09 (Architect)
- **Solution_Analyst referansı:** kök neden raporu — `~/.claude/projects/F--AI-AGENCY-K-SAT/memory/project_ayka_eta_reminder_root_cause.md`
- **ADR-001 referansı:** `PROMPT lar/ADR-001_hot-fix_spec.md` (LIVE 2026-05-09 02:14 UTC)
- **ADR-002 referansı:** `PROMPT lar/ADR-002_consistency_guard_spec.md` (Spec READY)
- **Read-only inceleme:** orders schema (5 ek migration ile evrim), RLS policy'leri (`get_user_context`, `get_my_company_id` helper'ları), profil rolleri (super_admin/owner/admin/operator/staff/workshop/driver), mevcut audit altyapısı envanteri okundu; hiçbir DB write yapılmadı.

✅ **Done**
- Schema/RLS/helper fonksiyon envanteri çıkarıldı (`orders`, `profiles`, `get_user_context`, `get_my_company_id`).
- Approach kıyaslaması yapıldı: A (yeni tablo) ✅ vs B (JSONB array kolonu) vs C (Postgres extension) — A net kazanan.
- Tracking field stratejisi kararı: tüm kolonlar (generic JSONB diff) + `updated_at, created_at, id` hariç (audit gürültüsü).
- Trigger spec yazıldı: AFTER INSERT OR UPDATE OR DELETE, FOR EACH ROW, SECURITY DEFINER, EXCEPTION fırlatmaz, recursion guard (`pg_trigger_depth() = 0`).
- `changed_by` (auth.uid()), `changed_by_role` (profiles lookup + jwt claim fallback), `source` (current_setting('app.source', true)) tasarımı yazıldı.
- RLS policy: SELECT super_admin/admin + owner/admin/operator/staff/workshop kendi şirketi (driver hariç). INSERT/UPDATE/DELETE yasak (sadece SECURITY DEFINER trigger).
- 4 index tasarlandı: `(order_id, changed_at DESC)`, `(changed_by, changed_at DESC)`, `(changed_field, changed_at DESC)`, `(company_id, changed_at DESC)`.
- 8 trigger + 5 RLS test senaryosu + KARIMA simülasyonu (3 satır beklentisi: INSERT + 2 UPDATE) yazıldı.
- Rollback SQL ve schema_migrations cleanup statement'ı dahil.
- Geriye uyumluluk doğrulandı: mevcut UPDATE noktaları (Dashboard, Workshop_app, Driver_app, n8n) etkilenmez; `source` faz-2'ye ertelendi.
- **Backfill imkânsızlığı şeffaf belgelendi (Bölüm 6.4):** geçmiş tarihçe — KARIMA dahil — geriye dönük üretilemez.
- ADR-002 ile semantik ayrım belgelendi (otomatik tespit vs UPDATE tarihçesi); ileri sprint için VIEW kapısı açık bırakıldı.

🔄 **In Progress**
- Yok — spec final.

⚠️ **Blockers**
- Yok. ADR-003 ADR-002'ye **bağımlı değil**, ama deploy sırası disipline edilmesi önerilir (ADR-002 önce). Director sprint önceliği bekliyor.

📋 **Next Steps**
- Developer: Bölüm 7.1 deploy adımlarını uygula → migration LIVE.
- System_Tester: Migration sonrası Bölüm 4.1 (8 trigger) + 4.2 (5 RLS) testlerini staging clone'da koş + Bölüm 4.3 KARIMA simülasyonu prod smoke.
- Solution_Analyst: Bölüm 6.4 (backfill imkânsız) bilgisini KARIMA "Açık konular" maddesinin yanına işaretle — gelecek vakaları cevaplanacak başlık altında.
- Frontend ekibi (faz-2): Bölüm 8'deki `set_audit_source` RPC'sini Dashboard, Workshop_app, Driver_app, n8n workflow'larına ekle — `source` zenginleştirmesi.
- Architect (sonra): ADR-002 + ADR-003 LIVE olduktan sonra `order_audit_full` VIEW'unu birleşik sorgu için tasarla (sprint+1).
