#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AYKA Akilli WhatsApp — Betül oturumu post-deploy izleme + Bulgu1 dil shadow-log.
2026-06-09 kuruldu. Salt-OKUMA: prod workflow'a hiçbir mutasyon yapmaz.

Her çalıştığında:
  - prod WF HSy9VD6eeptkf8g2 execution'larını cursor'dan (son işlenen id) sonrası tarar.
  - Bulgu2: _ghost_order_guard_blocked fire'larını + Save Confirmed Order oranını sayar
            (over-correction = save'in dibe vurması).
  - Bulgu3: intent=operator_escalation & _intent_detail=status_check_overdue fire'larını sayar.
  - Bulgu1 SHADOW: her müşteri turn'ünde aday dil-heuristiği uygular; lock!=algılanan
            ve güçlü tek-dil sinyali (ack/kısa hariç) → would_override aday'ı kaydeder.
            HİÇBİR ŞEY DEĞİŞTİRMEZ; sadece gerçek false-positive oranını ölçmek için loglar.
  - Sonuçları report.md (insan-okur) + raw.jsonl (inceleme) dosyalarına ekler.
"""
import sys, os, json, urllib.request, datetime, re
sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://n8n.k-sat.tech/api/v1"
WF = "HSy9VD6eeptkf8g2"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "betul_monitor_state.json")
REPORT = os.path.join(HERE, "betul_monitor_report.md")
RAW = os.path.join(HERE, "betul_monitor_raw.jsonl")
MAX_NEW = 500              # bir çalışmada işlenecek azami yeni execution
BACKFILL_FIRST = 300       # ilk çalıştırmada bakılacak son execution sayısı

KEY = None
with open(r"F:\AI AGENCY K-SAT\AYKA Transport lojistics projet\.env", encoding="utf-8") as f:
    for line in f:
        if line.startswith("N8N_API_KEY="):
            KEY = line.split("=", 1)[1].strip(); break

def get(path):
    req = urllib.request.Request(BASE + path, headers={"X-N8N-API-KEY": KEY, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

def fj(rd, name):
    try: return rd[name][0]["data"]["main"][0][0]["json"]
    except Exception: return None

def node_ran(rd, name):
    return name in rd

# ---------- Bulgu1 aday dil-heuristiği (MUHAFAZAKÂR; yalnız ölçüm için) ----------
CUES = {
 "tr": [r"\bmerhaba\b", r"selam", r"te[sş]ekk[uü]r", r"\bhal[iı]", r"gelmedi", r"de[gğ]il",
        r"\bevde\b", r"l[uü]tfen", r"\bvar m[iı]\b", r"ne zaman", r"\bg[uü]n[uü]?\b",
        r"sal[iı]", r"pazartesi", r"per[sş]embe", r"yar[iı]n", r"\byok\b", r"istiyorum", r"\bbu g[uü]n"],
 "fr": [r"\bbonjour\b", r"\bmerci\b", r"livraison", r"demain", r"aujourd'?hui", r"\btapis\b",
        r"\bje\b", r"\bvous\b", r"est-ce", r"\bpas\b", r"\bcommande\b", r"\bjour\b", r"\bn'?ai\b"],
 "nl": [r"goedemiddag", r"goedemorgen", r"bedankt", r"\btapijt", r"morgen", r"\bniet\b",
        r"ophalen", r"\bkan ik\b", r"\bvandaag\b", r"\bbestelling\b", r"\bgekomen\b"],
 "en": [r"\bhello\b", r"\bthank", r"\bcarpet", r"delivery", r"tomorrow", r"didn'?t",
        r"\bplease\b", r"\bwhen\b", r"\btoday\b", r"\border\b", r"\bnot\b\b"],
}
ACK_ONLY = re.compile(r"^[\s\W]*(ok(ey|ay)?|tamam|merci|thanks?|thx|bedankt|👍|🙏|👌|evet|oui|yes|ja)[\s\W]*$", re.I)

def detect_lang(text):
    """Returns (detected_lang_or_None, strong_bool, cue_hits_dict)."""
    if not text: return (None, False, {})
    t = text.lower()
    hits = {}
    for lang, pats in CUES.items():
        c = sum(1 for p in pats if re.search(p, t))
        if c: hits[lang] = c
    if not hits: return (None, False, hits)
    # en çok cue alan dil
    best = max(hits, key=hits.get)
    best_c = hits[best]
    others = sum(v for k, v in hits.items() if k != best)
    # güçlü = >=2 cue tek dilde VE diğer diller toplam 0
    strong = best_c >= 2 and others == 0
    return (best, strong, hits)

LANG_NORM = {"english": "en", "turkish": "tr", "french": "fr", "dutch": "nl", "flemish": "nl",
             "en": "en", "tr": "tr", "fr": "fr", "nl": "nl"}
def norm_lang(v):
    if not v: return None
    return LANG_NORM.get(str(v).strip().lower())

def parse_agent_lang(rd):
    """lock-in-play = Akilli Load Prev State.language_lock (full word, modüler NLU şemasında
    agent çıktısı language_lock emit etmiyor); reply = agent.language."""
    lock = reply = None
    lp = fj(rd, "Akilli Load Prev State")
    if isinstance(lp, dict):
        lock = lp.get("language_lock") or (lp.get("slots") or {}).get("language") if isinstance(lp.get("slots"), dict) else lp.get("language_lock")
    ag = fj(rd, "Restore Agent Output") or fj(rd, "Akilli WhatsApp Asistani")
    if ag and isinstance(ag.get("output"), str):
        try:
            o = json.loads(ag["output"])
            reply = o.get("language")
            if not lock:
                ia = o.get("internal_analysis") or {}
                lock = ia.get("language_lock") or o.get("language_lock")
        except Exception: pass
    return norm_lang(lock), norm_lang(reply)

def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f: return json.load(f)
    return {"cursor_id": 0, "runs": 0}

def save_state(s):
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)

def main():
    if not KEY:
        print("ERROR: N8N_API_KEY yok"); sys.exit(1)
    st = load_state()
    first = st["runs"] == 0
    cursor = st.get("cursor_id", 0)

    # execution id listesini topla (yeni->eski). cursor'a ulaşınca veya limit'te dur.
    ids = []
    nxt = None; pages = 0
    while pages < 8:
        p = f"/executions?workflowId={WF}&limit=100&includeData=false" + (f"&cursor={nxt}" if nxt else "")
        d = get(p)
        for e in d.get("data", []):
            eid = int(e["id"])
            if not first and eid <= cursor:
                nxt = None; break
            ids.append(eid)
            if first and len(ids) >= BACKFILL_FIRST:
                nxt = None; break
        else:
            nxt = d.get("nextCursor")
            pages += 1
            if nxt: continue
        break
    ids = sorted(set(ids))
    if len(ids) > MAX_NEW: ids = ids[-MAX_NEW:]

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    tally = {"new": 0, "save_confirmed": 0, "ghost_blocked": 0, "ghost_error": 0,
             "overdue_fired": 0, "shadow_candidates": 0}
    ghost_rows, overdue_rows, shadow_rows = [], [], []
    raw_lines = []

    for eid in ids:
        try:
            det = get(f"/executions/{eid}?includeData=true")
        except Exception as ex:
            continue
        rd = det.get("data", {}).get("resultData", {}).get("runData", {})
        if not rd: continue
        tally["new"] += 1
        ext = fj(rd, "Extract Text Message")
        jid = inbound = pushname = None
        if ext:
            b = ext.get("body", {}).get("data", {})
            jid = b.get("key", {}).get("remoteJid")
            pushname = b.get("pushName")
            m = b.get("message", {})
            inbound = m.get("conversation") or (m.get("extendedTextMessage") or {}).get("text")
        save_fired = node_ran(rd, "Save Confirmed Order")
        if save_fired: tally["save_confirmed"] += 1

        sdo = fj(rd, "Slot DB-Override (v9.12.13.14)") or fj(rd, "Slot DB-Override")
        gb = None
        if isinstance(sdo, dict) and "_ghost_order_guard_blocked" in sdo:
            gb = sdo.get("_ghost_order_guard_blocked")
            if sdo.get("_ghost_order_guard_error"): tally["ghost_error"] += 1
            if gb is True:
                tally["ghost_blocked"] += 1
                ghost_rows.append({"id": eid, "jid": jid, "inbound": inbound,
                                   "fresh": sdo.get("_ghost_order_guard_fresh"),
                                   "date_ok": sdo.get("_ghost_order_guard_date_ok")})
        cj = fj(rd, "Code in JavaScript1")
        if isinstance(cj, dict) and cj.get("_intent_detail") == "status_check_overdue":
            tally["overdue_fired"] += 1
            overdue_rows.append({"id": eid, "jid": jid, "inbound": inbound})

        lock, reply = parse_agent_lang(rd)
        det_lang, strong, hits = detect_lang(inbound)
        ack = bool(inbound and ACK_ONLY.match(inbound))
        would = bool(strong and not ack and lock and det_lang and det_lang != lock)
        if would:
            tally["shadow_candidates"] += 1
            shadow_rows.append({"id": eid, "jid": jid, "inbound": inbound,
                                "detected": det_lang, "lock": lock, "reply": reply, "cues": hits})

        raw_lines.append(json.dumps({"run": now, "id": eid, "jid": jid, "push": pushname,
                                     "inbound": inbound, "save": save_fired, "ghost_blocked": gb,
                                     "overdue": cj.get("_intent_detail") if isinstance(cj, dict) else None,
                                     "lock": lock, "reply": reply, "detect": det_lang,
                                     "strong": strong, "ack": ack, "would_override": would},
                                    ensure_ascii=False))
        if eid > cursor: cursor = eid

    # ---- yaz ----
    with open(RAW, "a", encoding="utf-8") as f:
        for l in raw_lines: f.write(l + "\n")

    sec = [f"\n## Run {now} (run #{st['runs']+1}{' BASELINE' if first else ''})",
           f"- Yeni execution işlendi: **{tally['new']}**",
           f"- Save Confirmed Order fire: **{tally['save_confirmed']}**  (over-correction göstergesi: trafiğe rağmen 0'a düşerse ALARM)",
           f"- Bulgu2 ghost-gate BLOCK: **{tally['ghost_blocked']}**  | gate error: {tally['ghost_error']}",
           f"- Bulgu3 overdue eskalasyon fire: **{tally['overdue_fired']}**",
           f"- Bulgu1 SHADOW would-override aday: **{tally['shadow_candidates']}**"]
    if ghost_rows:
        sec.append("\n### Bulgu2 BLOCK vakaları (her birini incele — meşru sipariş yanlış bloke edildi mi?)")
        for r in ghost_rows[:40]:
            sec.append(f"  - exec {r['id']} | fresh={r['fresh']} date_ok={r['date_ok']} | {r['jid']} | {str(r['inbound'])[:120]!r}")
    if overdue_rows:
        sec.append("\n### Bulgu3 overdue fire vakaları (operatör Telegram ulaştı mı canlı teyit)")
        for r in overdue_rows[:40]:
            sec.append(f"  - exec {r['id']} | {r['jid']} | {str(r['inbound'])[:120]!r}")
    if shadow_rows:
        sec.append("\n### Bulgu1 SHADOW would-override adayları (FALSE-POSITIVE incelemesi)")
        for r in shadow_rows[:60]:
            sec.append(f"  - exec {r['id']} | detected={r['detected']} lock={r['lock']} reply={r['reply']} cues={r['cues']} | {str(r['inbound'])[:120]!r}")
    block = "\n".join(sec) + "\n"

    header_needed = not os.path.exists(REPORT)
    with open(REPORT, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("# AYKA Betül-oturumu post-deploy izleme + Bulgu1 dil shadow-log\n"
                    "Salt-okuma. Bulgu2 ghost-gate + Bulgu3 overdue + Bulgu1 dil-uyumsuzluğu aday-override ölçümü.\n"
                    "Yorum: ghost BLOCK vakalarında inbound gerçek sipariş/onaysa = false-block (over-correction). "
                    "shadow would-override adaylarında inbound kısa/karışıksa = override yapılırsa false-positive.\n")
        f.write(block)

    st["cursor_id"] = cursor
    st["runs"] += 1
    st["last_run"] = now
    save_state(st)

    print(block)
    print(f"# cursor={cursor} runs={st['runs']} report={REPORT}")

if __name__ == "__main__":
    main()
