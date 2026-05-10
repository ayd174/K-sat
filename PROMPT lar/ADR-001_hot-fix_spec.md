# ADR-001 Hot-Fix Specification — ETA Reminder Mutlak Tarih Interpolation

**ADR ID:** ADR-001
**Title:** ETA 3-Saat Hatırlatma workflow'unda göreceli zaman ifadesini (`aujourd'hui/vandaag/bugün/today`) `route_date`'ten interpolate edilmiş mutlak tarih ile değiştir
**Status:** Approved (hot-fix)
**Date:** 2026-05-09
**Author:** Architect (Software_Team)
**Consumer:** Developer (Software_Team)
**Affected workflow:** `Hzuyvr5EK6grSyY7` — `ETA - 3 Saat Oncesi Hatirlatma v2`
**n8n base:** `https://n8n.k-sat.tech/api/v1`
**Workflow versionId at spec time:** `8d478042-8742-4bce-9bcb-23d4fe7b142c` (versionCounter `83`)

---

## 1. Bağlam ve Kök Neden Özeti

2026-05-09'da Solution_Analyst, KARIMA vakasında (ORD-0163) Görsel 1'de görülen *"Notre chauffeur passera chez vous **aujourd'hui** pour votre tapis"* mesajının kaynağının WhatsApp asistanı (`HSy9VD6eeptkf8g2`) **olmadığını**, ETA 3-Saat Hatırlatma workflow'unun (`Hzuyvr5EK6grSyY7`) Set node'larında **hardcoded** 4 dil mesaj template'i olduğunu tespit etti. v9.12.1 prompt güncellemesi WhatsApp asistanını susturdu fakat ETA workflow'unu etkilemedi — Hata 5 (göreceli zaman halüsinasyonu) hâlâ canlı.

Bu spec, workflow'un 4 dil Set node'undaki hardcoded sözcüklerin yerine `route_date`'ten interpolate edilen mutlak tarih ifadesini koymanın eksiksiz değişiklik planıdır.

**RPC çıktı şeması doğrulaması (migration `Dashboard_SaaS/supabase/migrations/20260322_eta_notification_setup.sql:44-88`):** `get_upcoming_eta_reminders` zaten `route_date date` (line 53, 69) field'ını döndürüyor; INNER JOIN `routes r` üzerinden — routes tablosunda NOT NULL. Yani interpolation için ek migration **GEREKMİYOR**.

---

## 2. Tasarım Kararları

### 2.1 Tarih formatı (dile göre)

Yıl YOK (kısa tutmak için), gün adı küçük harfle FR/NL'de (Latin standart), TR'de "günü" eki ile sonda, EN'de virgüllü.

| Dil | Format şablonu | Örnek (route_date = `2026-05-06`) |
|---|---|---|
| FR | `ce <weekday> <day> <month_lowercase>` | `ce mercredi 6 mai` |
| NL | `deze <weekday> <day> <month>` | `deze woensdag 6 mei` |
| TR | `<day> <month> <weekday> günü` | `6 Mayıs Çarşamba günü` |
| EN | `this <weekday>, <day> <month>` | `this Wednesday, 6 May` |

### 2.2 Saat asla ekleme

KARIMA için ETA 18:04'tü, fakat saat eklenmesi **YASAK** (v9.12 Bölüm 1.8 — müşteriye kesin saat/saat aralığı verme yasağı ile tutarlı). Yalnızca tarih (gün adı + gün + ay). Reminder mesajı zaten "günün içinde" izlenimi veriyor — saat eklemek beklenti yönetimini bozar.

### 2.3 Interpolation mekanizması — neden Code node, neden Set node değil

**İki seçenek değerlendirildi:**

**Seçenek A — Set node'da Luxon expression** (örn. `{{ DateTime.fromISO($json.route_date, {zone: 'Europe/Brussels'}).setLocale('fr-BE').toFormat("'ce' cccc d LLLL") }}`)

- Avantaj: Code node'a dokunmadan minimal değişiklik.
- Risk: n8n self-hosted Node.js imajı **full-ICU** (tam Unicode/locale veri seti) ile derlenmiş olmayabilir. Luxon yerelleştirmeyi Node Intl.DateTimeFormat'a delege eder; ICU subset olduğunda `tr-TR` weekday adlarının `cccc` token'ı `Çarşamba` yerine boş string veya İngilizce fallback dönebilir. n8n.k-sat.tech için ICU build durumu bu spec yazıldığı an Architect tarafından doğrulanamadı.
- Ayrıca TR formatı için Luxon'un yerleşik token sırası `weekday` SONDA değil, dil-doğal sırada gelir; manuel concat veya iki ayrı `toFormat` çağrısı gerekirdi → karmaşıklık.

**Seçenek B — Code node'da `Intl.DateTimeFormat` ile pre-format** (TERCİH EDİLEN)

- Mevcut `ETA ve Mesaj Hazirla` Code node (id `8aa19e6e-c88a-434b-8727-f63118745a37`) zaten dile göre `actionLabel` üretiyor. Aynı node'a `formatted_route_date` field'ı eklemek dil koşullamasını TEK YERDE merkezi tutar.
- `Intl.DateTimeFormat` Node.js'in herhangi bir build'inde kararlı API'dır; ancak ICU subset durumda TR locale sınırlı olabilir. Çözüm: **ay ve haftanın günü için manuel array map** kullan — locale'e bağlı olma riskini sıfırla.
- Set node'lardaki değişiklik trivial: `*aujourd'hui*` → `{{ $json.formatted_route_date }}`.

**Karar:** Seçenek B. Aşağıdaki Code node patch'i ICU bağımsızdır (fallback deterministik string array map).

### 2.4 Fallback davranışı (route_date NULL/undefined)

RPC tanımı route_date'i `routes.route_date` üzerinden çekiyor; `routes` tablosunda NOT NULL. Yine de defansif yaklaşım: Code node'da `route_date` falsy ise dile göre yumuşak fallback:

| Dil | Fallback |
|---|---|
| FR | `prochainement` |
| NL | `binnenkort` |
| TR | `yakında` |
| EN | `soon` |

Bu, beklenmedik bir veri durumunda mesajın bozulmadan ("undefined" basmadan) gönderilmesini sağlar.

---

## 3. Etkilenen Node'lar — Workflow GET ile Doğrulanmış

GET `/workflows/Hzuyvr5EK6grSyY7` ile alınan snapshot'ta (response top-level `nodes[]` array'i) doğrulanan node bilgileri:

| Sıra | Node ID (n8n internal) | Node Name | Tip | JSON path (top-level `nodes[i]`) | Pretty-print line |
|---|---|---|---|---|---|
| 1 | `8aa19e6e-c88a-434b-8727-f63118745a37` | `ETA ve Mesaj Hazirla` | `n8n-nodes-base.code` (typeVersion 2) | `parameters.jsCode` | ~92 |
| 2 | `dd6be738-e50f-41f1-9ca8-145dc9150384` | `Hatirlatma FR` | `n8n-nodes-base.set` (typeVersion 3.4) | `parameters.assignments.assignments[0].value` (assignment id `dddddddd-eeee-4fff-8aaa-bbbbccccdddd`, name `whatsapp_message`) | 211 |
| 3 | `d8429f37-81d8-44a1-bef8-2693f3babf35` | `Hatirlatma NL` | `n8n-nodes-base.set` (typeVersion 3.4) | `parameters.assignments.assignments[0].value` (assignment id `ffffffff-aaaa-4bbb-8ccc-ddddeeeeffff`, name `whatsapp_message`) | 235 |
| 4 | `fe41efea-8f25-4066-8a6e-80e17c837687` | `Hatirlatma TR` | `n8n-nodes-base.set` (typeVersion 3.4) | `parameters.assignments.assignments[0].value` (assignment id `b2b2b2b2-c3c3-4d4d-8e5e-f6f6a7a7b8b8`, name `whatsapp_message`) | 259 |
| 5 | `1e2cf5ba-0fb5-4753-a995-ee0c3fab20a5` | `Hatirlatma EN` | `n8n-nodes-base.set` (typeVersion 3.4) | `parameters.assignments.assignments[0].value` (assignment id `d4d4d4d4-e5e5-4f6f-8a7a-b8b8c9c9d0d0`, name `whatsapp_message`) | 283 |

**Not (snapshot duplicate):** Workflow JSON yanıtının ayrıca `activeVersion.nodes[]` alt-koleksiyonu (line 788–1530 civarı) **aynı 4 mesaj template'inin kopyasını** taşıyor (line 990, 1014, 1038, 1062). Bu blok n8n'in versiyon snapshot'ı; PUT body'sine dahil EDİLMEZ ve doğrudan değiştirilemez. Yalnızca top-level `nodes[]` güncellenir; `activeVersion` yeni bir versionId ile sunucu tarafında otomatik üretilir.

---

## 4. Değişiklik Spesifikasyonu — Verbatim Eski/Yeni Değerler

### 4.1 Code Node — `ETA ve Mesaj Hazirla` (id `8aa19e6e-c88a-434b-8727-f63118745a37`)

**Path:** `nodes[i].parameters.jsCode` (i = bu node'un array indexi)

#### ESKİ DEĞER (verbatim, JSON-escaped olarak workflow'da tutulan kaynak; aşağıda okunabilir hâli)

```javascript
const stop = $input.first().json;

// estimated_arrival_time = "HH:MM:SS"
const timeStr = stop.estimated_arrival_time || '';
const etaFormatted = timeStr.substring(0, 5); // "HH:MM"

// route_type
const routeType = stop.route_type || 'pickup';
const lang = stop.language || 'fr';

const actionLabels = {
  fr: { pickup: 'récupérer', delivery: 'livrer' },
  nl: { pickup: 'ophalen', delivery: 'leveren' },
  tr: { pickup: 'teslim almak', delivery: 'teslim etmek' },
  en: { pickup: 'collect', delivery: 'deliver' }
};

const actionLabel = (actionLabels[lang] || actionLabels.fr)[routeType] || 'récupérer';

return [{
  json: {
    ...stop,
    eta_formatted: etaFormatted,
    action_label: actionLabel,
    language: lang
  }
}];
```

#### YENİ DEĞER (verbatim, ICU bağımsız manuel locale map)

```javascript
const stop = $input.first().json;

// estimated_arrival_time = "HH:MM:SS"
const timeStr = stop.estimated_arrival_time || '';
const etaFormatted = timeStr.substring(0, 5); // "HH:MM"

// route_type
const routeType = stop.route_type || 'pickup';
const lang = stop.language || 'fr';

const actionLabels = {
  fr: { pickup: 'récupérer', delivery: 'livrer' },
  nl: { pickup: 'ophalen', delivery: 'leveren' },
  tr: { pickup: 'teslim almak', delivery: 'teslim etmek' },
  en: { pickup: 'collect', delivery: 'deliver' }
};

const actionLabel = (actionLabels[lang] || actionLabels.fr)[routeType] || 'récupérer';

// ─── ADR-001 hot-fix: route_date'ten dile göre mutlak tarih üret ───
// Hardcoded weekday/month tabloları → ICU build'den bağımsız çalışır.
// route_date format: "YYYY-MM-DD" (Postgres date, timezone-naïf).
const weekdays = {
  fr: ['dimanche','lundi','mardi','mercredi','jeudi','vendredi','samedi'],
  nl: ['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag'],
  tr: ['Pazar','Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi'],
  en: ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
};
const months = {
  fr: ['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre'],
  nl: ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december'],
  tr: ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'],
  en: ['January','February','March','April','May','June','July','August','September','October','November','December']
};
const fallback = { fr: 'prochainement', nl: 'binnenkort', tr: 'yakında', en: 'soon' };

let formattedRouteDate = fallback[lang] || fallback.fr;
const rd = stop.route_date;
if (rd && typeof rd === 'string' && /^\d{4}-\d{2}-\d{2}/.test(rd)) {
  // UTC parse — date-only string'i timezone shift olmadan al
  const [y, m, d] = rd.substring(0, 10).split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const wd = weekdays[lang][dt.getUTCDay()];
  const mo = months[lang][dt.getUTCMonth()];
  if (lang === 'fr')      formattedRouteDate = `ce ${wd} ${d} ${mo}`;
  else if (lang === 'nl') formattedRouteDate = `deze ${wd} ${d} ${mo}`;
  else if (lang === 'tr') formattedRouteDate = `${d} ${mo} ${wd} günü`;
  else                    formattedRouteDate = `this ${wd}, ${d} ${mo}`;
}

return [{
  json: {
    ...stop,
    eta_formatted: etaFormatted,
    action_label: actionLabel,
    formatted_route_date: formattedRouteDate,
    language: lang
  }
}];
```

#### Doğrulama (route_date = `2026-05-06`, Çarşamba)

| lang | formatted_route_date |
|---|---|
| fr | `ce mercredi 6 mai` |
| nl | `deze woensdag 6 mei` |
| tr | `6 Mayıs Çarşamba günü` |
| en | `this Wednesday, 6 May` |

`new Date(Date.UTC(2026, 4, 6)).getUTCDay()` → `3` (Çarşamba). `weekdays.fr[3]` → `'mercredi'`. Doğrulandı.

### 4.2 Set Node — `Hatirlatma FR` (id `dd6be738-e50f-41f1-9ca8-145dc9150384`)

**Path:** `nodes[i].parameters.assignments.assignments[0].value`

#### ESKİ DEĞER (verbatim, single-line JSON string — newline'lar `\n` olarak kayıtlı)

```
=⏰ Rappel Ayka Tapis\n\nBonjour {{ $json.customer_name }},\n\nNotre chauffeur passera chez vous *aujourd'hui* pour {{ $json.action_label }} votre tapis. Il est en route — merci de rester disponible !\n\n📍 {{ $json.address }}\n\nAyka Tapis 🏠
```

#### YENİ DEĞER (verbatim)

```
=⏰ Rappel Ayka Tapis\n\nBonjour {{ $json.customer_name }},\n\nNotre chauffeur passera chez vous *{{ $json.formatted_route_date }}* pour {{ $json.action_label }} votre tapis. Il est en route — merci de rester disponible !\n\n📍 {{ $json.address }}\n\nAyka Tapis 🏠
```

**Diff özeti:** `*aujourd'hui*` → `*{{ $json.formatted_route_date }}*` (yıldız vurgulamayı koru — WhatsApp italik biçimlendirmesi).

### 4.3 Set Node — `Hatirlatma NL` (id `d8429f37-81d8-44a1-bef8-2693f3babf35`)

**Path:** `nodes[i].parameters.assignments.assignments[0].value`

#### ESKİ DEĞER

```
=⏰ Herinnering Ayka Tapijten\n\nHallo {{ $json.customer_name }},\n\nOnze chauffeur is onderweg en komt *vandaag* uw tapijt {{ $json.action_label }}. Gelieve beschikbaar te zijn !\n\n📍 {{ $json.address }}\n\nAyka Tapijten 🏠
```

#### YENİ DEĞER

```
=⏰ Herinnering Ayka Tapijten\n\nHallo {{ $json.customer_name }},\n\nOnze chauffeur is onderweg en komt *{{ $json.formatted_route_date }}* uw tapijt {{ $json.action_label }}. Gelieve beschikbaar te zijn !\n\n📍 {{ $json.address }}\n\nAyka Tapijten 🏠
```

**Diff özeti:** `*vandaag*` → `*{{ $json.formatted_route_date }}*`.

### 4.4 Set Node — `Hatirlatma TR` (id `fe41efea-8f25-4066-8a6e-80e17c837687`)

**Path:** `nodes[i].parameters.assignments.assignments[0].value`

#### ESKİ DEĞER

```
=⏰ Hatırlatma - Ayka Halı\n\nMerhaba {{ $json.customer_name }},\n\nSürücümüz *bugün* halınızı {{ $json.action_label }} için yola çıktı. Lütfen hazır olunuz !\n\n📍 {{ $json.address }}\n\nAyka Halı Yikama Firmasi Ekibi🏠
```

#### YENİ DEĞER

```
=⏰ Hatırlatma - Ayka Halı\n\nMerhaba {{ $json.customer_name }},\n\nSürücümüz *{{ $json.formatted_route_date }}* halınızı {{ $json.action_label }} için yola çıkacak. Lütfen hazır olunuz !\n\n📍 {{ $json.address }}\n\nAyka Halı Yikama Firmasi Ekibi🏠
```

**Diff özeti:**
- `*bugün*` → `*{{ $json.formatted_route_date }}*`
- `yola çıktı` (geçmiş zaman) → `yola çıkacak` (gelecek zaman) — TR'de tarihli ifade ile uyumlu olması için.

> **Architect notu:** TR cümlede yer alan "yola çıktı" geçmiş zaman çekimi, eski "bugün" hardcoded kelimesiyle uyumluydu (şoför halen yolda demek için). Mutlak tarihli ifadede ("6 Mayıs Çarşamba günü") "çıktı" Türkçede zaman uyumsuzluğu yaratır; "çıkacak" gelecek-anlık çekimi semantik açıdan daha doğru. Bu küçük dilbilgisel revizyon ADR-001 kapsamında uygulanmalıdır.

### 4.5 Set Node — `Hatirlatma EN` (id `1e2cf5ba-0fb5-4753-a995-ee0c3fab20a5`)

**Path:** `nodes[i].parameters.assignments.assignments[0].value`

#### ESKİ DEĞER

```
=⏰ Reminder - Ayka Carpets\n\nHello {{ $json.customer_name }},\n\nOur driver is on the way and will arrive *today* to {{ $json.action_label }} your carpet. Please stay available !\n\n📍 {{ $json.address }}\n\nAyka Carpets 🏠
```

#### YENİ DEĞER

```
=⏰ Reminder - Ayka Carpets\n\nHello {{ $json.customer_name }},\n\nOur driver is on the way and will arrive *{{ $json.formatted_route_date }}* to {{ $json.action_label }} your carpet. Please stay available !\n\n📍 {{ $json.address }}\n\nAyka Carpets 🏠
```

**Diff özeti:** `*today*` → `*{{ $json.formatted_route_date }}*`.

---

## 5. PUT Body Yapısı (Developer Operasyon Notu)

n8n public API `PUT /workflows/{id}` çağrısı **tam workflow envelope'unu** kabul eder; sadece değişen field'ları gönderemezsin. Operasyon adımları:

1. **Backup:** GET `/workflows/Hzuyvr5EK6grSyY7` → `eta_workflow_backup_2026-05-09T<HHMM>.json` (zaman damgalı). Rollback için zorunlu.
2. **Mutate:** Backup JSON'ın bir kopyasını al; aşağıdaki field'ları sadece **top-level `nodes[]`** içinde güncelle:
   - `nodes[i].parameters.jsCode` (Code node `8aa19e6e…`) → 4.1 yeni değer
   - `nodes[i].parameters.assignments.assignments[0].value` (FR/NL/TR/EN Set node'ları, her biri ayrı index) → 4.2/4.3/4.4/4.5 yeni değerleri
3. **Strip read-only fields:** PUT body'sinde **şu üst-seviye field'lar gönderilmez** (n8n public API onları yok sayar veya 400 verir):
   - `id`, `createdAt`, `updatedAt`, `versionId`, `activeVersionId`, `versionCounter`, `triggerCount`, `shared`, `tags`, `activeVersion`, `isArchived`, `meta`
   - **Gönderilen field'lar:** `name`, `nodes`, `connections`, `settings`, `staticData`, `pinData`, `active` (opsiyonel — n8n bazı sürümlerde reddedebilir; pratikte sadece `name`, `nodes`, `connections`, `settings` yeterlidir).
4. **PUT request:**
   ```
   PUT https://n8n.k-sat.tech/api/v1/workflows/Hzuyvr5EK6grSyY7
   Headers:
     X-N8N-API-KEY: <key from Workshop_app/.env>
     Content-Type: application/json
   Body: <mutated workflow envelope>
   ```
5. **Verify:** Response 200 + dönen `versionCounter` artmış olmalı (84+). Workflow `active: true` durumunu koru.

> **Architect notu (workflow active state):** Workflow şu an `active: true`. PUT sırasında ETA reminder cron'u (15 dk'da bir) çalışıyor olabilir. Riski minimize etmek için Developer PUT'u **çift çeyrek dakika dışında** (örn. xx:07–xx:13, xx:22–xx:28 pencerelerinde) yapmalı. Ya da geçici olarak `active=false` PUT et, mutate, sonra `active=true` PUT — fakat bu iki ekstra round-trip; pratikte ilk yaklaşım yeterli.

---

## 6. Test Plan (Developer için)

PUT sonrası 4 senaryoyu **n8n manual execution** ile (workflow editor → "Execute Workflow") veya RPC mock data ile doğrula. Production cron'unu beklemek zorunda değilsin — Code node ve sonrası workflow'u manuel input ile çalıştırılabilir.

### Senaryo 1 — Normal route_date (2026-05-09, Cumartesi)

**Mock RPC output (1 stop):**
```json
[{
  "stop_id": "test-1",
  "route_id": "test-r1",
  "order_id": "test-o1",
  "customer_name": "Test FR",
  "customer_phone": "+32400000001",
  "language": "fr",
  "estimated_arrival_time": "14:30:00",
  "route_date": "2026-05-09",
  "address": "Rue Test 1, 1000 Bruxelles",
  "route_type": "pickup"
}]
```

**Beklenen `formatted_route_date`:** `ce samedi 9 mai`
**Beklenen WhatsApp mesajı (FR):** `…Notre chauffeur passera chez vous *ce samedi 9 mai* pour récupérer votre tapis…`

`language` field'ını sırasıyla `nl`, `tr`, `en` yap, çıktı:
- nl → `deze zaterdag 9 mei` → `…komt *deze zaterdag 9 mei* uw tapijt ophalen…`
- tr → `9 Mayıs Cumartesi günü` → `Sürücümüz *9 Mayıs Cumartesi günü* halınızı teslim almak için yola çıkacak…`
- en → `this Saturday, 9 May` → `…will arrive *this Saturday, 9 May* to collect your carpet…`

### Senaryo 2 — Past route_date (2026-04-01, Çarşamba)

`route_date` = `2026-04-01`. Beklenen FR: `ce mercredi 1 avril`. Geçmiş tarih için Code node hata vermemeli, formatlanmış string basmalı (cron filtresi normalde geçmiş veriyi getirmez ama defansif testtir).

### Senaryo 3 — NULL/missing route_date

Mock RPC output'tan `route_date` field'ını sil (veya `null` yap). Beklenen:
- fr → `formatted_route_date = "prochainement"` → `…passera chez vous *prochainement* pour…`
- nl → `binnenkort`
- tr → `yakında`
- en → `soon`

Workflow exception fırlatmamalı; mesaj tam metinle gönderilmeli.

### Senaryo 4 — Locale farkı (aynı tarih, 4 dil)

`route_date = 2026-12-25` (Cuma):
- fr → `ce vendredi 25 décembre`
- nl → `deze vrijdag 25 december`
- tr → `25 Aralık Cuma günü`
- en → `this Friday, 25 December`

Doğrulama matrisi: gün adı + ay adı doğru dilde, gün rakamı leading-zero **olmadan**, vurgu `*…*` markdown italik korunmuş.

### Senaryo 5 — End-to-end (production smoke)

Test bittiğinde, staging için bir test order yarat (`route_date` = bugün+1 gün, `estimated_arrival` ≈ NOW + 3h), normal cron tetiklemesini bekle. Test telefonuna gerçek WhatsApp mesajı gelmeli.

---

## 7. Rollback Talimatı

Eğer test sırasında veya production'da sorun çıkarsa:

1. **Pre-fix backup zorunluydu** (Adım 5.1). Backup dosyası: `eta_workflow_backup_2026-05-09T<HHMM>.json`.
2. Backup JSON'ı, "PUT body" formatına dönüştür (read-only field'ları çıkar — Adım 5.3).
3. Aynı PUT endpoint'ine backup body'yi gönder. Workflow eski versiyonuna döner.
4. n8n'in `versionCounter` her PUT'ta artar; "rollback PUT" yeni bir versiyon yaratır (eskisini override etmez), ama içerik geri dönmüş olur.
5. Solution_Analyst'e "ADR-001 rollback yapıldı" raporu ver; kök neden tekrar incelensin.

---

## 8. Out-of-Scope (Bu Hot-fix'in DIŞI)

Bu spec **yalnızca** hardcoded `aujourd'hui/vandaag/bugün/today` ifadelerini mutlak tarih ile değiştirir. Aşağıdakiler ADR-001 kapsamı **DIŞINDA**:

- ADR-002 (pickup_date ↔ route_date tutarlılık guard) — RPC ve trigger değişikliği gerek; ayrı sprint.
- ADR-003 (pickup_date audit log) — schema migration; ayrı sprint.
- WhatsApp asistan prompt'u (`HSy9VD6eeptkf8g2`) — v9.12.1 ile zaten kapsandı, bu spec'te ek değişiklik yok.
- Diğer initial_notif workflow'ları (`OhBvaPoczlPgIJmr` Routes Planning) — Developer ek inceleme gerekirse ayrı ADR.

---

## 9. Spec doğrulama checklist (Architect imzası)

- [x] Workflow GET ile yapı doğrulandı (top-level `nodes[]` vs `activeVersion.nodes[]` ayrımı).
- [x] 4 Set node + 1 Code node id'si ve assignment id'si verbatim çıkarıldı.
- [x] RPC `route_date` field'ının çıktı şemasında olduğu migration line 53/69 ile doğrulandı.
- [x] ICU bağımsız Code node yaklaşımı seçildi (TR locale Luxon riski elimine).
- [x] Verbatim eski → yeni string'ler 4 dil için verildi.
- [x] TR cümlede `çıktı → çıkacak` zaman uyumu düzeltmesi gerekçelendirildi.
- [x] Fallback davranışı (NULL route_date) tanımlandı.
- [x] PUT body read-only field stripping listelendi.
- [x] Test plan 4+1 senaryo ile yazıldı.
- [x] Rollback talimatı verildi.

---

**Hand-off:** Developer bu spec'i alıp `Hzuyvr5EK6grSyY7` workflow'una hot-fix uygulayabilir. Pre-PUT backup zorunlu; PUT sonrası Senaryo 1–4 manuel test, Senaryo 5 staging smoke. Sorular varsa Architect'e (bana) tırmanma yap, JSON üzerinde değişiklik kararını TEK BAŞINA verme.

✅ **Spec onaylandı — Architect, 2026-05-09**
