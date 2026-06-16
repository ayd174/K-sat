#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify the latest DAILY_FINANCIAL_REPORT_AND_CLEANUP run.

Run this AFTER the 21:30 Europe/Brussels fire (>= 19:30 UTC). It pulls recent
executions for the workflow, finds the most recent trigger-mode run, and reports
status + which nodes ran + whether a report was sent. Loud flag on error / no run.

    python scripts/check_dfrc_execution.py
"""
import sys, json, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
WID = "vBdbn1c9YW3s4iWP"
N8N = "https://n8n.k-sat.tech/api/v1"


def _key():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("N8N_API_KEY not found in .env")


def _get(path):
    req = urllib.request.Request(N8N + path, headers={"X-N8N-API-KEY": _key()})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    data = _get(f"/executions?workflowId={WID}&limit=12&includeData=false").get("data", [])
    triggers = [e for e in data if e.get("mode") == "trigger"]
    if not triggers:
        print("⚠️  NO trigger-mode execution found in the last 12 runs — schedule may not have fired.")
        for e in data[:5]:
            print("   ", e.get("id"), e.get("startedAt"), e.get("mode"), e.get("status"))
        return 1
    latest = triggers[0]
    eid, started, status = latest["id"], latest.get("startedAt"), latest.get("status")
    print(f"latest trigger exec: {eid} | started {started} | status {status}")
    full = _get(f"/executions/{eid}?includeData=true")
    rd = (full.get("data", {}).get("resultData", {}) or {}).get("runData", {}) or {}
    ran = list(rd.keys())
    print("nodes ran:", ran)
    sent = "Send Telegram" in ran and "Send Email" in ran
    wiped = "Mark Wiped" in ran
    if status == "error":
        print("❌ EXECUTION ERRORED — check n8n + expect a Telegram error alert.")
        err = (full.get("data", {}).get("resultData", {}) or {}).get("error")
        if err:
            print("   error:", json.dumps(err, ensure_ascii=False)[:400])
        return 1
    print(f"report sent (email+telegram): {sent}")
    print(f"wipe ran this cycle: {wiped}  (first real wipe due 2026-06-21)")
    if not sent and "Build Report" in ran:
        print("ℹ️  no document sent — Build Report likely returned 0 unreported orders (expected if backlog already reported).")
    print("✅ trigger fired and completed without error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
