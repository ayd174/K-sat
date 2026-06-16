#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WhatsApp assistant — live fix monitor (2026-06-17, oturum fix'leri).
Son ~14 saatlik gerçek trafiği tarar, YÜKSEK-GÜVENLİ deterministik misfire'ları raporlar:
  1. operator_escalation / operator_handoff intent ama _handoff yok  -> SILENT DROP
     (reschedule / overdue / cancelled / status-fallback / mixed-service handoff'ları)
  2. reschedule_request -> _handoff true olmalı
  3. Aktif-siparişe ÇIPLAK ack ("ok/merci") -> same-day operator_handoff = REGRESYON
Sentetik-probe JID'leri ve fix-öncesi (eski) exec'ler zaman penceresiyle dışlanır.
Çıktı: "ALL OK" veya misfire listesi (Telegram/operatör'e iletmek için).
Kullanım: python whatsapp_fix_monitor.py [LOOKBACK_HOURS]   (default 14)
"""
import sys, json, urllib.request, re
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(encoding="utf-8")

LOOKBACK_H = float(sys.argv[1]) if len(sys.argv) > 1 else 14.0
ENV = r"F:\AI AGENCY K-SAT\AYKA Transport lojistics projet\.env"
WF = "HSy9VD6eeptkf8g2"

env = {}
for line in open(ENV, encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"')
NKEY = env["N8N_API_KEY"]

def n8n(p):
    r = urllib.request.Request("https://n8n.k-sat.tech/api/v1/" + p, headers={"X-N8N-API-KEY": NKEY})
    return json.load(urllib.request.urlopen(r, timeout=90))

def parse_iso(s):
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception: return None

# Deploy floor: the final session fix (a6aad888, escalation silent-drop batch) went live
# ~2026-06-16T23:00Z. Only POST-deploy traffic is a valid regression signal — older execs
# ran on pre-fix versions and must not raise false alarms during the transition window.
DEPLOY_FLOOR = datetime(2026, 6, 16, 23, 0, tzinfo=timezone.utc)
cutoff = max(datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_H), DEPLOY_FLOOR)
PROMISE = re.compile(r"transmets|mets en relation|notre op[ée]rateur|notre responsable|vous (re)?contactera|confirmera la nouvelle|op[ée]rateur confirmera la|operat[öo]r[üu]m[üu]z|[şs]of[öo]r[üu]m[üu]ze|iletiyorum", re.I)
BAREACK = re.compile(r"^(ok|okey|oui|d'?accord|merci|mersi|tamam|evet|👍|👌|🙏)[\s!.,👍🙏👌]*$", re.I)

lst = n8n(f"executions?workflowId={WF}&limit=120").get("data", [])
misfires = []; checked = 0
for e in lst:
    st = parse_iso(e.get("startedAt", ""))
    if st and st < cutoff:
        break  # executions are newest-first; stop once older than window
    eid = e["id"]
    try:
        d = n8n(f"executions/{eid}?includeData=true")
        rd = d["data"]["resultData"]["runData"]
        nodes = list(rd.keys())
        def first(n):
            try: return rd[n][0]["data"]["main"][0][0]["json"]
            except Exception: return None
        wj = first("WhatsApp Webhook") or {}
        jid = str(((wj.get("body") or {}).get("data") or {}).get("key", {}).get("remoteJid", ""))
        if "synthetic-probe" in jid:
            continue
        nlu = first("Output Validator (v9.12.7)") or {}
        nintent = None
        try: nintent = (json.loads(nlu.get("output")) if isinstance(nlu.get("output"), str) else {}).get("intent")
        except Exception: pass
        o = (first("Code in JavaScript1") or {}).get("output") or {}
        if not isinstance(o, dict):
            continue
        checked += 1
        intent = o.get("intent"); handoff = o.get("_handoff") is True
        reply = o.get("response_message") or ""
        ao = first("Check Customer By Phone") or {}
        ao_status = (ao.get("order_status") if isinstance(ao, dict) else None)
        cb = first("Claim Buffer") or {}
        msg = (cb.get("accumulated_text") if isinstance(cb, dict) else "") or ""
        notify = any("Notify Staff" in n for n in nodes)

        # CHECK 1+2: a human-forward promise / escalation-handoff intent that did NOT fire _handoff
        if intent in ("operator_escalation", "operator_handoff") and not handoff and PROMISE.search(reply):
            misfires.append(f"#{eid} SILENT-DROP intent={intent} detail={o.get('_intent_detail')} notify={notify} | \"{msg[:55]}\" -> \"{reply[:70]}\"")
        elif nintent == "reschedule_request" and not handoff:
            misfires.append(f"#{eid} RESCHEDULE-NO-HANDOFF | \"{msg[:55]}\"")
        # CHECK 3: active-order bare ack mis-escalated to same-day
        elif BAREACK.match(msg.strip()) and ao_status and o.get("_handoff_reason") == "same_day":
            misfires.append(f"#{eid} ACK->SAME-DAY REGRESSION ao={ao_status} | \"{msg[:40]}\"")
    except Exception:
        pass

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
lines = [f"[whatsapp-fix-monitor {stamp}] lookback={LOOKBACK_H}h checked={checked} execs"]
if misfires:
    lines.append(f"*** {len(misfires)} MISFIRE(S) ***")
    lines += ["  " + m for m in misfires]
else:
    lines.append("ALL OK - no silent-drop / same-day-ack / reschedule misfires in window")
report = "\n".join(lines)
print(report)
# self-log: append to a capped log file (keep last ~400 lines) so the scheduled task has a record
import os
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")
try:
    old = open(LOG, encoding="utf-8").read().splitlines() if os.path.exists(LOG) else []
except Exception:
    old = []
new = old + report.split("\n") + [""]
open(LOG, "w", encoding="utf-8").write("\n".join(new[-400:]))
sys.exit(2 if misfires else 0)
