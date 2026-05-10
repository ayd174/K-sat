# DEGISIKLIKLER - 1 ASISTAN ve YENI SIPARIS v2

**Tarih:** 2026-03-22
**Kaynak dosya:** `1 ASISTAN ve YENI SIPARIS.json`
**Hedef dosya:** `1_ASISTAN_ve_YENI_SIPARIS_v2.json`

---

## 1. HATA DÜZELTMELERİ

### 1.1 Simple Memory — Sabit Session Key Hatası
- **Node:** Simple Memory (id: `abca5283`)
- **Problem:** `sessionKey: "=whatsapp_session"` sabit bir string olarak tanımlanmıştı. Bu, tüm müşterilerin aynı bellek oturumunu paylaşmasına neden oluyordu — farklı müşterilerin mesajları birbirine karışıyordu.
- **Yapılan Değişiklik:** `"=whatsapp_session"` → `"={{ $('Webhook').item.json.session_key }}"`
- **Neden:** Her müşteri kendi benzersiz `session_key`'ini (telefon numarası / JID) taşımalı, böylece AI agent her müşteri için ayrı bir bağlam saklar.

---

### 1.2 Code in JavaScript1 — JSON.parse Hata Toleransı
- **Node:** Code in JavaScript1 (id: `1f630322`)
- **Problem:** `JSON.parse(raw)` ifadesi try/catch olmadan kullanılıyordu. AI agent geçersiz JSON döndürdüğünde tüm workflow çöküyordu.
- **Yapılan Değişiklik:** JSON.parse etrafına try/catch eklendi. Hata durumunda güvenli bir varsayılan output döndürülüyor (`has_customer_info: false`, Fransızca hata mesajı).
- **Neden:** Üretim ortamında AI çıktısı her zaman geçerli JSON olmayabilir; workflow'un düşmesi yerine zarif bir hata yönetimi gereklidir.

---

### 1.3 Parse Customer Data — daysUntil Mantık Hatası + try/catch
- **Node:** Parse Customer Data (id: `fed74344`)
- **Problem 1:** `if (daysUntil <= 0) daysUntil += 7;` — Müşterinin bugünkü günü seçmesi durumunda (örn. Pazartesi günü "lundi" derse) daysUntil=0 olup 7 gün ekleniyor, böylece bir hafta sonraki güne kayıyordu.
- **Problem 2:** `JSON.parse(cleaned)` etrafında try/catch yoktu.
- **Yapılan Değişiklik:** `<= 0` → `< 0` (bugün de geçerli gün olarak kabul edilsin); JSON.parse etrafına try/catch eklendi.
- **Neden:** Müşteri bugünkü toplama gününü söylediğinde sistem onu reddetmemeli. Ayrıca parse hatalarında workflow çökmemeli.

---

### 1.4 Parse Missing Field — Aynı Düzeltmeler
- **Node:** Parse Missing Field (id: `92f4fab4`)
- **Problem:** Parse Customer Data ile aynı iki sorun: `daysUntil <= 0` mantık hatası ve JSON.parse'da try/catch yokluğu.
- **Yapılan Değişiklik:** `<= 0` → `< 0`; JSON.parse etrafına try/catch eklendi.
- **Neden:** Parse Customer Data ile tutarlı davranış için aynı düzeltmeler uygulandı.

---

### 1.5 Code in JavaScript2 — Sabit Sipariş Numarası
- **Node:** Code in JavaScript2 (id: `688b8818`)
- **Problem:** `const orderNo = 'ORD-0023';` — Tüm siparişler "ORD-0023" numarasını alıyordu, sipariş numaraları çakışıyordu.
- **Yapılan Değişiklik:** `'ORD-0023'` → `'ORD-' + Date.now()`
- **Neden:** Her siparişin benzersiz bir numara alması gerekir.

---

### 1.6 Extract Text Message — Set Node'dan Code Node'a Dönüştürme
- **Node:** Extract Text Message (id: `b3826746`)
- **Problem:** Eski Set node sadece `message` alanını set ediyordu, ancak downstream node'ların ihtiyaç duyduğu `channel` ve `session_key` bilgileri kayboluyordu.
- **Yapılan Değişiklik:** Set node → Code node. Tüm kaynak alanları korunuyor, `message`, `channel: 'whatsapp'` ve `session_key` ekleniyor.
- **Neden:** Passthrough "Webhook" node'una ulaşan verinin standart formatta olması gerekiyor.

---

### 1.7 Get Audio Base64 — Kırık Webhook Referansı
- **Node:** Get Audio Base64 (id: `004c44e2`)
- **Problem:** `$('Webhook')` referansları var, ancak orijinal Webhook node "WhatsApp Webhook" olarak yeniden adlandırıldığında bu referanslar kırılıyordu.
- **Yapılan Değişiklik:** Tüm `$('Webhook')` referansları → `$('WhatsApp Webhook')`
- **Neden:** Node adı değiştiğinde referansların da güncellenmesi gerekir.

---

### 1.8 Extract Missing Field — Kırık Node Referansı
- **Node:** Extract Missing Field (id: `18e548c9`)
- **Problem:** `$('WhatsApp Order Intake1').item.json.messages[0].text.body` — Bu node artık workflow'da mevcut değil, referans kırık.
- **Yapılan Değişiklik:** `$('WhatsApp Order Intake1')...` → `$('Webhook').item.json.body.data.message.conversation`
- **Neden:** Mevcut olmayan node'a yapılan referans çalışma zamanı hatasına yol açar.

---

### 1.9 Edit Fields — Trailing Space Hatası
- **Node:** Edit Fields (id: `f7b91fe9`)
- **Problem:** Alan adı `"pickup_address "` (sonda boşluk var) — bu, Supabase sütun adıyla eşleşmiyordu ve veri kayıt edilemiyordu.
- **Yapılan Değişiklik:** `"pickup_address "` → `"pickup_address"` (boşluk kaldırıldı)
- **Neden:** Supabase sütun adlarında boşluk olmamalı; eşleşmezlik sessiz veri kaybına yol açar.

---

### 1.10 Save Confirmed Order — Birden Fazla Hata
- **Node:** Save Confirmed Order (id: `8b4528c5`)
- **Problem 1:** `"fieldId": "=customer_name"` — `=` prefix'i alan adını expression olarak yorumluyor, Supabase sütun adı olarak değil.
- **Problem 2:** `$('WhatsApp Order Intake1')` referansı — bu node artık yok.
- **Problem 3:** `channel` alanı eksikti, SMS kanalından gelen siparişler hangi kanaldan geldiği bilinmeden kaydediliyordu.
- **Yapılan Değişiklik:** `"=customer_name"` → `"customer_name"`; kırık referans → `$('Edit Fields').item.json.phone_number`; `channel` alanı eklendi.
- **Neden:** Alan adlarına expression prefix eklenmemeli; kırık referanslar düzeltilmeli; çok kanallı destek için `channel` alanı zorunlu.

---

### 1.11 Save Pending Order — Eksik Alanlar ve Kırık Referans
- **Node:** Save Pending Order (id: `f8a53f6c`)
- **Problem 1:** `$('WhatsApp Order Intake1')` kırık referansı.
- **Problem 2:** `pickup_date` alanı eksikti — pending siparişlerde tarih kaydedilmiyordu.
- **Problem 3:** `channel` alanı eksikti.
- **Yapılan Değişiklik:** Kırık referans → `$('Edit Fields').item.json.phone_number`; `pickup_date` alanı eklendi; `channel` alanı eklendi.
- **Neden:** Pending siparişler de toplama tarihini kaydetmeli; çok kanallı izleme için channel bilgisi gerekli.

---

### 1.12 Check Confirmed Order — Duplicate Tespiti Pencere Sorunu
- **Node:** Check Confirmed Order (id: `31c2b469`)
- **Problem:** `created_at > today midnight` — Gece 00:00'dan önce verilen siparişler aynı gün duplicate olarak tespit edilemiyordu. Bir müşteri dün gece 23:58'de sipariş verse, bugün sabah aynı siparişi tekrar vermeye çalışsa sistem duplicate görmüyordu.
- **Yapılan Değişiklik:** `new Date(new Date().setHours(0,0,0,0)).toISOString()` → `new Date(Date.now() - 24*60*60*1000).toISOString()` (son 24 saat)
- **Neden:** Gün sınırına değil, kayan 24 saatlik pencereye göre duplicate tespiti daha güvenilirdir.

---

### 1.13 AI Agent — Yanlış Input Referansı
- **Node:** Akıllı WhatsApp Asistanı (id: `d2fe11b6`)
- **Problem:** `"text": "={{ $json.text || $('Extract Text Message').item.json.message }}"` — Whisper çıktısı için `$json.text` kullanılıyordu; ancak artık her kaynaktan normalize edilmiş `message` alanı kullanılmalı.
- **Yapılan Değişiklik:** `$json.text || $('Extract Text Message').item.json.message` → `$json.message`
- **Neden:** Tüm kaynaklar (metin, ses, SMS) artık "Webhook" passthrough üzerinden standart `message` alanıyla geliyor.

---

### 1.14 Transcribe a recording Whisper STT — Hata Toleransı
- **Node:** Transcribe a recording Whisper STT (id: `a3ea6ec6`)
- **Problem:** Whisper STT başarısız olduğunda (bozuk ses, bağlantı hatası vb.) tüm workflow duruyordu.
- **Yapılan Değişiklik:** `"onError": "continueRegularOutput"` eklendi.
- **Neden:** Whisper hatası workflow'u durdurmamalı; sonraki Check Whisper Error node'u hatayı yakalayıp kullanıcıya bilgi verebilmeli.

---

## 2. GÜVENLİK İYİLEŞTİRMELERİ

### 2.1 Session İzolasyonu
- **Kategori:** Güvenlik / Veri İzolasyonu
- **Problem:** Tüm müşteriler `"whatsapp_session"` adıyla tek bir shared memory session'da çalışıyordu. Müşteri A'nın konuşması Müşteri B'nin bağlamını kirletebilirdi.
- **Yapılan Değişiklik:** Session key artık dinamik: `$('Webhook').item.json.session_key` — her müşterinin telefon numarası/JID'i benzersiz session oluşturuyor.
- **Neden:** Müşteri verilerinin başka müşterilere sızmaması için oturum izolasyonu zorunludur.

---

## 3. SMS KANAL DESTEĞİ

### 3.1 SMS Webhook — Yeni Giriş Noktası
- **Node:** SMS Webhook (id: `b2c3d4e5`, yeni)
- **Problem:** Yalnızca WhatsApp mesajları destekleniyordu.
- **Yapılan Değişiklik:** `path: "sms-intake"` ile yeni bir webhook node eklendi.
- **Neden:** Twilio SMS kanalından gelen mesajları sisteme kabul etmek için ayrı bir giriş noktası gerekli.

---

### 3.2 Normalize SMS — Twilio Formatı Dönüşümü
- **Node:** Normalize SMS (id: `c4d5e6f7`, yeni)
- **Problem:** Twilio'dan gelen SMS payload'u (`From`, `Body` alanları) WhatsApp formatıyla uyumlu değildi.
- **Yapılan Değişiklik:** Code node ile Twilio formatı → WhatsApp-compatible format dönüşümü. `channel: "sms"`, `session_key: from` alanları ekleniyor.
- **Neden:** Downstream node'lar tek bir standart formatta veri beklediğinden format normalizasyonu gerekli.

---

### 3.3 Format Whisper Output — Ses Yolundan Normalize Çıktı
- **Node:** Format Whisper Output (id: `a1b2c3d4...92`, yeni)
- **Problem:** Whisper STT çıktısı (`text` alanı) downstream için standart formatta değildi; `channel` ve `session_key` bilgileri eksikti.
- **Yapılan Değişiklik:** Code node ile Whisper çıktısı normalize ediliyor: kaynak WhatsApp webhook verisi korunuyor, `message`, `channel: 'whatsapp'`, `session_key` ekleniyor.
- **Neden:** Tüm yolların (metin, ses, SMS) aynı formatta veri üretmesi gerekiyor.

---

### 3.4 Webhook Passthrough — Birleştirici Node
- **Node:** Webhook (id: `d5e6f7a8`, yeni, isim kritik!)
- **Problem:** 3 farklı kaynak (Extract Text Message, Format Whisper Output, Normalize SMS) Akıllı WhatsApp Asistanı'na ayrı ayrı bağlanıyordu; downstream node'lar `$('Webhook')` referansıyla standart veri bekliyor.
- **Yapılan Değişiklik:** `return [$input.item];` yapan bir Code passthrough node eklendi. Bu node "Webhook" adını taşıyor, böylece mevcut tüm `$('Webhook')` referansları otomatik olarak bu normalize edilmiş veriye işaret ediyor.
- **Neden:** Tek bir standart veri akışı noktası olmadan SMS, ses ve metin mesajlarını aynı downstream logic'te işlemek mümkün değil.

---

### 3.5 Check Whisper Error — Ses Hata Yönetimi
- **Node:** Check Whisper Error (id: `f1e2d3c4`, yeni)
- **Problem:** Whisper hata verdiğinde kullanıcıya bilgi verilmiyordu.
- **Yapılan Değişiklik:** IF node ile `$json.error` varlığı kontrol ediliyor. TRUE (hata var) → kullanıcıya Fransızca hata mesajı; FALSE → Format Whisper Output.
- **Neden:** Kullanıcı deneyimi için ses transkripsiyonu başarısız olduğunda kullanıcı bilgilendirilmeli.

---

### 3.6 Send Whisper Error WA — Ses Hata Bildirimi
- **Node:** Send Whisper Error WA (id: `a1b2c3d4...91`, yeni)
- **Problem:** Whisper hatası durumunda kullanıcıya mesaj gönderilmiyordu.
- **Yapılan Değişiklik:** Evolution API node ile "Je n'ai pas pu comprendre votre message vocal, veuillez écrire votre message." mesajı gönderiliyor.
- **Neden:** Kullanıcı neden cevap almadığını anlamadan beklememeli.

---

### 3.7 Channel Router + Twilio Nodes — SMS Yanıt Yönlendirme
- **Nodes:** 5 adet Channel Router IF node + 5 adet Twilio HTTP Request node (toplam 10 yeni node)
- **Problem:** Tüm yanıtlar yalnızca Evolution API (WhatsApp) üzerinden gönderiliyordu. SMS kanalından gelen mesajlara SMS ile yanıt verilmesi gerekirken WhatsApp üzerinden gönderim deneniyor ve başarısız oluyordu.
- **Yapılan Değişiklik:** Her "Send" node'u öncesine bir `Channel Router` IF node eklendi:
  - `$('Webhook').item.json.channel === 'sms'` → TRUE: Twilio HTTP Request
  - FALSE: Mevcut Evolution API node
  - Etkilenen 5 send noktası: rependre message, Send Pending Confirmation, Send Duplicate Message, Send Confirmation Message, Send Missing Info Message
- **Neden:** Müşteri hangi kanaldan yazdıysa, yanıt aynı kanaldan gönderilmeli (WhatsApp → WhatsApp, SMS → SMS).

---

## 4. MODEL GÜNCELLEMELERİ

### 4.1 OpenAI Chat Model1
- **Node:** OpenAI Chat Model1 (id: `de3652ab`)
- **Değişiklik:** `gpt-4o-mini` → `gpt-4.1-mini`
- **Neden:** gpt-4.1-mini daha iyi performans ve güncel model.

### 4.2 Extract Missing Field
- **Node:** Extract Missing Field (id: `18e548c9`)
- **Değişiklik:** `gpt-4o-mini` → `gpt-4.1-mini`
- **Neden:** Model standardizasyonu.

### 4.3 Generate Missing Info Message
- **Node:** Generate Missing Info Message (id: `740b7eef`)
- **Değişiklik:** `gpt-4o-mini` → `gpt-4.1-mini`
- **Neden:** Model standardizasyonu.

### 4.4 Generate Pending Confirmation
- **Node:** Generate Pending Confirmation (id: `c7a1a113`)
- **Değişiklik:** `gpt-4o-mini` → `gpt-4.1-mini`
- **Neden:** Model standardizasyonu.

### 4.5 Generate Duplicate Message
- **Node:** Generate Duplicate Message (id: `8ed80bf4`)
- **Değişiklik:** `gpt-4o-mini` → `gpt-4.1-mini`
- **Neden:** Model standardizasyonu.

---

---

## 5. DUPLICATE SIPARIŞ HATASI — KÖK NEDEN VE DÜZELTME

### 5.1 Sorun: İki Ayrı INSERT → Çift Sipariş

**Tarih:** 2026-04-11

**Belirtiler:**
- Aynı müşteri için iki ayrı sipariş görünüyor (ör. ORD-1775923065760 ve ORD-1775923119863)
- Biri status = "new" (pending), diğeri status = "confirmed"
- Telefon alanı "AUTOMATIC" — WhatsApp n8n akışından geliyor
- Sipariş numaraları `ORD-${Date.now()}` formatında (13 haneli timestamp)

**Kök Neden:**
n8n akışında iki ayrı Supabase INSERT node bulunuyor:
1. **"Save Pending Order"** → Müşteri bilgisi eksikken INSERT (status: "new")
2. **"Save Confirmed Order"** → Tüm bilgi tamamlanınca tekrar INSERT (status: "confirmed")

"Check Confirmed Order" node'u (1.12 düzeltmesi) yalnızca "confirmed" statüsündeki siparişleri kontrol ediyor.
"new" statüsündeki mevcut sipariş "confirmed" değil, bu yüzden duplicate tespiti çalışmıyor.

**Çözüm — upsert-order Edge Function:**

Yeni Supabase Edge Function oluşturuldu:
`Dashboard_SaaS/supabase/functions/upsert-order/index.ts`

Bu fonksiyon:
1. Gelen `company_id + customer_name + pickup_date` için "new", "pending" veya "confirmed" statüsünde mevcut sipariş arar
2. **Bulursa → UPDATE** (yeni sipariş oluşturmaz)
3. **Bulamazsa → INSERT** (yeni sipariş oluşturur)

**n8n'de Yapılması Gereken Değişiklik:**

"Save Confirmed Order" ve "Save Pending Order" node'larını Supabase'e doğrudan INSERT yerine bu Edge Function'a HTTP POST olarak yönlendirin:

```
URL: https://<SUPABASE_PROJECT>.supabase.co/functions/v1/upsert-order
Method: POST
Headers:
  Authorization: Bearer <SUPABASE_ANON_KEY>
  Content-Type: application/json
Body: {
  "company_id": "...",
  "customer_name": "...",
  "customer_phone": "AUTOMATIC",
  "pickup_address": "...",
  "pickup_date": "...",
  "order_status": "confirmed",   // veya "new"
  "channel": "whatsapp"
}
```

Fonksiyon yanıtı:
- `action: "updated"` → mevcut sipariş güncellendi (duplicate önlendi)
- `action: "inserted"` → yeni sipariş oluşturuldu

---

## 6. ARKİTEKTÜR DEĞİŞİKLİKLERİ ÖZET

### Eski Mimari
```
WhatsApp Webhook → Language Detection → fromMe Filter → Message Type Router
  [audio] → Get Audio Base64 → Convert B64 → Whisper STT → AI Agent
  [text]  → Extract Text Message → AI Agent
```

### Yeni Mimari
```
WhatsApp Webhook → Language Detection → fromMe Filter → Message Type Router
  [audio] → Get Audio Base64 → Convert B64 → Whisper STT → Check Whisper Error
             → [hata] → Send Whisper Error WA
             → [ok]   → Format Whisper Output → Webhook (passthrough)
  [text]  → Extract Text Message → Webhook (passthrough)

SMS Webhook → Normalize SMS → Webhook (passthrough)

Webhook (passthrough) → AI Agent → ... → Channel Router → [SMS] Twilio
                                                         → [WA]  Evolution API
```

### Kritik Notlar (Deployment için)
1. **Twilio credentials:** Her Twilio node'unda `TWILIO_CRED_PLACEHOLDER` yer tutucu ID var — gerçek Twilio kimlik bilgileriyle değiştirilmeli.
2. **Twilio Account SID:** URL'deki `{{YOUR_ACCOUNT_SID}}` gerçek hesap SID'i ile değiştirilmeli.
3. **Twilio From numarası:** `+32XXXXXXXXX` gerçek Twilio numarasıyla değiştirilmeli.
4. **SMS Webhook URL:** `sms-intake` path'i Twilio webhook ayarlarında tanımlanmalı.
