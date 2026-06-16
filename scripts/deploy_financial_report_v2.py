#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Transform DAILY_FINANCIAL_REPORT_AND_CLEANUP (vBdbn1c9YW3s4iWP) into a safe
report -> wait 7 days -> wipe system.

Design:
  Schedule 23:59 Europe/Brussels -> TWO parallel branches
  Phase A (report): delivered+revenue orders NOT yet in revenue_report_log
      -> CSV -> Email + Telegram -> (only after both) log them (+amount snapshot)
  Phase B (deferred wipe): log rows reported_at <= now-7d & not wiped
      -> PATCH amounts=0 ONLY where order_status='delivered' (inline guard) -> mark wiped

Never touches non-delivered (in-flight) orders -> driver collection safe.
Wipe is reversible via amounts_snapshot in the log.

Deploys via PUT (in place), preserving Email/Telegram credentials.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import urllib.request
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        ENV[k] = v.strip().strip('"')

N8N_KEY = ENV["N8N_API_KEY"]
N8N_BASE = "https://n8n.k-sat.tech/api/v1"
WID = "vBdbn1c9YW3s4iWP"
SB_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
REST = ENV["SUPABASE_URL"].rstrip("/") + "/rest/v1"

SB_HEADERS_BASE = [
    {"name": "apikey", "value": SB_KEY},
    {"name": "Authorization", "value": "Bearer " + SB_KEY},
    # force a fresh socket per request: avoids stale keep-alive hang on the 2nd
    # sequential Supabase call (observed: "Get Reported IDs" connection timeout)
    {"name": "Connection", "value": "close"},
]


# transient network blips must not kill an unattended nightly financial job
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 3000}


def get(name, url, x, y):
    return {
        "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
        "position": [x, y], "alwaysOutputData": True, **RETRY,
        "parameters": {"url": url, "sendHeaders": True,
                       "headerParameters": {"parameters": list(SB_HEADERS_BASE)}, "options": {"timeout": 30000}},
    }


def patch(name, url, body_json, x, y):
    return {
        "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
        "position": [x, y], "alwaysOutputData": True, **RETRY,
        "parameters": {
            "method": "PATCH", "url": url,
            "sendHeaders": True,
            "headerParameters": {"parameters": SB_HEADERS_BASE + [
                {"name": "Content-Type", "value": "application/json"},
                {"name": "Prefer", "value": "return=minimal"}]},
            "sendBody": True, "specifyBody": "json", "jsonBody": body_json, "options": {"timeout": 30000},
        },
    }


def code(name, js, x, y):
    return {"name": name, "type": "n8n-nodes-base.code", "typeVersion": 2,
            "position": [x, y], "parameters": {"jsCode": js}}


# ---- Trigger ----
trigger = {
    "name": "Schedule (21:30 Brussels)", "type": "n8n-nodes-base.scheduleTrigger",
    "typeVersion": 1.3, "position": [-1100, 200],
    "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "30 21 * * *"}]}},
}

# ===== PHASE A =====
# Single RPC call does the dedup server-side (delivered + revenue + NOT already-reported).
# Replaces two sequential Supabase reads -> the 2nd sequential read reliably timed out
# from this n8n instance (keep-alive hang). One call = the pattern that always succeeded.
get_orders = {
    "name": "Get Unreported Orders", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
    "position": [-700, 0], "alwaysOutputData": True, **RETRY,
    "parameters": {
        "method": "POST", "url": REST + "/rpc/get_unreported_revenue_orders",
        "sendHeaders": True,
        "headerParameters": {"parameters": SB_HEADERS_BASE + [{"name": "Content-Type", "value": "application/json"}]},
        "sendBody": True, "specifyBody": "json", "jsonBody": "{}", "options": {"timeout": 30000},
    },
}

build_report = code("Build Report", r"""
const fresh=$('Get Unreported Orders').all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).filter(x=>x&&x.id);
if(fresh.length===0) return [];
const num=v=>v!=null?Number(v):0;
const rows=fresh.map(o=>({json:{
  'Siparis No':o.order_no||'',
  'Musteri':o.customer_name||'',
  'Telefon':o.customer_phone||'',
  'Durum':o.order_status||'',
  'Odeme Durumu':o.payment_status||'',
  'Toplam Tutar':num(o.total_amount),
  'Depozito':num(o.deposit_amount),
  'Tahsil Edilen':num(o.collected_amount),
  'Tarih':o.created_at?String(o.created_at).split('T')[0]:''
}}));
const sum=k=>fresh.reduce((a,o)=>a+num(o[k]),0);
const r2=n=>Math.round(n*100)/100;
// totals row at the end
rows.push({json:{
  'Siparis No':'TOPLAM ('+fresh.length+' siparis)',
  'Musteri':'',
  'Telefon':'',
  'Durum':'',
  'Odeme Durumu':'',
  'Toplam Tutar':r2(sum('total_amount')),
  'Depozito':r2(sum('deposit_amount')),
  'Tahsil Edilen':r2(sum('collected_amount')),
  'Tarih':''
}});
return rows;
""".strip(), -350, 0)

to_csv = {
    "name": "Convert to CSV", "type": "n8n-nodes-base.spreadsheetFile", "typeVersion": 2,
    "position": [-100, 0],
    "parameters": {"operation": "toFile", "fileFormat": "csv",
                   "options": {"fileName": "=Finansal_Rapor_{{ $now.format('yyyy-MM-dd') }}.csv"}},
}

send_email = {
    "name": "Send Email", "type": "n8n-nodes-base.emailSend", "typeVersion": 1,
    "position": [150, 0],
    "parameters": {
        "fromEmail": "reports@aykatransport.com",
        "toEmail": "=ksat.ozd@gmail.com",
        "subject": "=Günlük Finansal Rapor - {{ $now.format('yyyy-MM-dd') }}",
        "html": "Merhaba,<br><br>Günlük finansal ciro raporunuz ekte yer almaktadır.<br>"
                "Rapordaki siparişlerin ciro verileri, bu başarılı gönderimden <b>1 hafta sonra</b> "
                "otomatik olarak temizlenecektir (teslim edilmiş siparişler; akıştaki siparişlere dokunulmaz).<br><br>İyi çalışmalar.",
        "attachments": "data", "options": {},
    },
    "credentials": {"smtp": {"id": "o0cSzuVdRm6gjzSu", "name": "SMTP account"}},
}

send_tg = {
    "name": "Send Telegram", "type": "n8n-nodes-base.telegram", "typeVersion": 1,
    "position": [400, 0],
    # sendDocument needs the binary toggle + property name; a bare `file: "data"` is
    # treated as a file_id/URL -> Telegram "Bad request - please check your parameters"
    "parameters": {"operation": "sendDocument", "chatId": "5841852274",
                   "binaryData": True, "binaryPropertyName": "data", "additionalFields": {}},
    "credentials": {"telegramApi": {"id": "CuNAjXFMgVToiCu0", "name": "Telegram account"}},
}

# emailSend does NOT forward the input binary, so Email and Telegram each branch
# directly off Convert to CSV (both receive the CSV binary). Merge waits for BOTH to
# finish before logging -> honours "log only after mail AND telegram succeed".
merge_sent = {
    "name": "Wait Both Sent", "type": "n8n-nodes-base.merge", "typeVersion": 3,
    "position": [500, 130], "parameters": {"mode": "append", "numberInputs": 2},
}

build_log = code("Build Log Rows", r"""
// order_id no longer in the CSV; source the reported orders straight from the RPC result
// (the RPC already did the dedup, so every returned order is exactly what was reported).
const src=$('Get Unreported Orders').all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).filter(x=>x&&x.id);
const rows=src.map(o=>({
  order_id:o.id, company_id:o.company_id||null,
  amounts_snapshot:{total_amount:o.total_amount!=null?o.total_amount:0,deposit_amount:o.deposit_amount!=null?o.deposit_amount:0,collected_amount:o.collected_amount!=null?o.collected_amount:0}
}));
if(rows.length===0) return [];
return [{json:{rows:rows}}];
""".strip(), 650, 0)

insert_log = {
    "name": "Insert Report Log", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
    "position": [900, 0], "alwaysOutputData": True, **RETRY,
    "parameters": {
        "method": "POST", "url": REST + "/revenue_report_log",
        "sendHeaders": True,
        "headerParameters": {"parameters": SB_HEADERS_BASE + [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "Prefer", "value": "resolution=merge-duplicates,return=minimal"}]},
        "sendBody": True, "specifyBody": "json", "jsonBody": "={{ $json.rows }}", "options": {"timeout": 30000},
    },
}

# ===== PHASE B (deferred wipe) =====
get_due = get(
    "Get Wipe-Due Log",
    # date-only cutoff (no tz offset) keeps the value URL-safe; n8n does not encode URL
    # expressions, so a full ISO with '+00:00' would break the query. lt <today-7d> means
    # "reported strictly before 7 days ago" => wiped ~7 days after the successful send.
    "=" + REST + "/revenue_report_log?wiped_at=is.null&reported_at=lt."
    "{{ $now.minus({days:7}).toFormat('yyyy-MM-dd') }}&select=order_id",
    -850, 350)

build_wipe = code("Build Wipe Set", r"""
const due=$('Get Wipe-Due Log').all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).filter(x=>x&&x.order_id);
const ids=due.map(x=>x.order_id);
if(ids.length===0) return [];
return [{json:{ids:ids, idsString:ids.join(',')}}];
""".strip(), -600, 350)

wipe_amounts = patch(
    "Wipe Amounts (delivered only)",
    "=" + REST + "/orders?id=in.({{ $json.idsString }})&order_status=eq.delivered",
    '{\n  "total_amount": 0,\n  "deposit_amount": 0,\n  "collected_amount": 0\n}',
    -350, 350)

mark_wiped = patch(
    "Mark Wiped",
    "=" + REST + "/revenue_report_log?order_id=in.({{ $('Build Wipe Set').first().json.idsString }})",
    '={{ {"wiped_at": $now.toISO()} }}',
    -100, 350)

nodes = [trigger, get_orders, build_report, to_csv, send_email, send_tg, merge_sent,
         build_log, insert_log, get_due, build_wipe, wipe_amounts, mark_wiped]

connections = {
    "Schedule (21:30 Brussels)": {"main": [[
        {"node": "Get Unreported Orders", "type": "main", "index": 0},
        {"node": "Get Wipe-Due Log", "type": "main", "index": 0}]]},
    # Phase A
    "Get Unreported Orders": {"main": [[{"node": "Build Report", "type": "main", "index": 0}]]},
    "Build Report": {"main": [[{"node": "Convert to CSV", "type": "main", "index": 0}]]},
    # fan out: Email and Telegram BOTH get the CSV binary directly from Convert to CSV
    "Convert to CSV": {"main": [[
        {"node": "Send Email", "type": "main", "index": 0},
        {"node": "Send Telegram", "type": "main", "index": 0}]]},
    "Send Email": {"main": [[{"node": "Wait Both Sent", "type": "main", "index": 0}]]},
    "Send Telegram": {"main": [[{"node": "Wait Both Sent", "type": "main", "index": 1}]]},
    "Wait Both Sent": {"main": [[{"node": "Build Log Rows", "type": "main", "index": 0}]]},
    "Build Log Rows": {"main": [[{"node": "Insert Report Log", "type": "main", "index": 0}]]},
    # Phase B
    "Get Wipe-Due Log": {"main": [[{"node": "Build Wipe Set", "type": "main", "index": 0}]]},
    "Build Wipe Set": {"main": [[{"node": "Wipe Amounts (delivered only)", "type": "main", "index": 0}]]},
    "Wipe Amounts (delivered only)": {"main": [[{"node": "Mark Wiped", "type": "main", "index": 0}]]},
}

body = {
    "name": "DAILY_FINANCIAL_REPORT_AND_CLEANUP",
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "timezone": "Europe/Brussels",
                 "callerPolicy": "workflowsFromSameOwner", "errorWorkflow": "pkiUdvFhm4gvAnZZ"},
}


# Deploy through the shared version-gate guard: aborts if the live workflow
# drifted from our last-deployed version (manual editor save), then stick-checks
# the PUT so an immediate revert is caught. Override a known drift with
# GUARD_FORCE=1. (scripts/ is sys.path[0] when this file is run directly.)
from n8n_deploy_guard import guarded_put, DriftError, StickError  # noqa: E402


if __name__ == "__main__":
    try:
        res = guarded_put(WID, body)
    except DriftError as e:
        print(str(e), file=sys.stderr)
        print("\n[deploy] ABORTED — review the external change, then re-run "
              "(GUARD_FORCE=1 to overwrite).", file=sys.stderr)
        sys.exit(3)
    except StickError as e:
        print(str(e), file=sys.stderr)
        sys.exit(4)
    print("PUT ok. name=", res.get("name"), "nodes=", len(res.get("nodes", [])), "active=", res.get("active"))
