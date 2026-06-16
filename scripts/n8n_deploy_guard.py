#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
n8n deploy version-gate guard (shared, reusable).

WHY THIS EXISTS
---------------
An n8n workflow deployed via the public API (PUT) can be silently overwritten
by a stale editor tab that auto-saves the OLD content back over it. A PUT
returning 200 does NOT mean the change is permanent, and the next blind PUT
will happily overwrite whatever drifted in. This module closes both holes:

  1. VERSION GATE (pre-PUT): before overwriting, GET the live workflow and
     compare its `versionId` against the last version *we* deployed (recorded
     in a local ledger). If they differ, someone changed the workflow outside
     this tooling since our last deploy -> ABORT and surface it, so the human
     reviews the external change instead of clobbering it. `force=True` (or
     env GUARD_FORCE=1) overrides intentionally.

  2. STICK CHECK (post-PUT): after the PUT, poll the live versionId a few times
     over ~12s and assert it still equals the versionId the PUT returned. A
     revert (editor tab re-save) flips it back -> raised as a loud failure.

The ledger (scripts/.n8n_deploy_versions.json) maps workflow_id -> last version
WE deployed. First deploy of an unknown workflow records a baseline and warns
(nothing to compare against yet).

USAGE — as a library (preferred for deploy scripts)
---------------------------------------------------
    from n8n_deploy_guard import guarded_put
    live = guarded_put(WORKFLOW_ID, body)          # gate + PUT + stick-check + ledger
    # raises DriftError if the live workflow drifted from our last deploy
    # raises StickError if the PUT did not stick (immediate revert)

USAGE — as a CLI
----------------
    python n8n_deploy_guard.py check  <wf_id>      # live vs ledger (no write)
    python n8n_deploy_guard.py record <wf_id> [ver]# set baseline = live (or ver)
    python n8n_deploy_guard.py list                # show whole ledger
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 guard

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
LEDGER_PATH = SCRIPTS_DIR / ".n8n_deploy_versions.json"

N8N_BASE = "https://n8n.k-sat.tech/api/v1"

# n8n public API rejects extra top-level / settings keys with 400 "additional
# properties". These are the only keys allowed through a PUT.
SETTINGS_WHITELIST = {
    "saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
    "saveDataSuccessExecution", "executionTimeout", "errorWorkflow",
    "timezone", "executionOrder",
}
TOP_WHITELIST = ("name", "nodes", "connections", "settings")


class DriftError(RuntimeError):
    """Live workflow changed externally since our last deploy."""


class StickError(RuntimeError):
    """PUT did not stick — versionId reverted after deploy."""


# --------------------------------------------------------------------------- #
# env / http
# --------------------------------------------------------------------------- #
def _api_key() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("N8N_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"N8N_API_KEY not found in {ENV_PATH}")


def _req(method: str, path: str, payload=None):
    key = _api_key()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        N8N_BASE + path, data=data, method=method,
        headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get_workflow(wf_id: str) -> dict:
    return _req("GET", f"/workflows/{wf_id}")


# --------------------------------------------------------------------------- #
# ledger
# --------------------------------------------------------------------------- #
def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ledger(d: dict) -> None:
    LEDGER_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def record_baseline(wf_id: str, version: str | None = None, name: str = "") -> str:
    """Set the ledger baseline for wf_id. If version is None, read it live."""
    if version is None:
        live = get_workflow(wf_id)
        version, name = live.get("versionId"), live.get("name", "")
    led = load_ledger()
    led[wf_id] = {"versionId": version, "name": name}
    save_ledger(led)
    return version


# back-compat alias
_record = record_baseline


def assert_baseline(wf_id: str, *, force: bool = False) -> dict:
    """Pre-PUT version gate. GET live, compare to ledger baseline.

    Raises DriftError if the live versionId differs from our last-deployed
    baseline (someone changed it outside this tooling). Returns the live dict
    so the caller can reuse it. force=True / GUARD_FORCE=1 downgrades to a warn.
    """
    force = force or os.environ.get("GUARD_FORCE") == "1"
    baseline = (load_ledger().get(wf_id) or {}).get("versionId")
    live = get_workflow(wf_id)
    live_ver = live.get("versionId")
    print(f"[guard] live versionId={live_ver}  nodes={len(live.get('nodes', []))}  active={live.get('active')}")
    if baseline is None:
        print(f"[guard] no ledger baseline for {wf_id} — first guarded deploy, will record after PUT")
    elif live_ver != baseline:
        msg = (f"[guard] DRIFT: live versionId ({live_ver}) != last-deployed baseline ({baseline}).\n"
               f"        The workflow was changed OUTSIDE this tooling since our last deploy.\n"
               f"        Review the external change before overwriting. Override: GUARD_FORCE=1.")
        if not force:
            raise DriftError(msg)
        print(msg + "\n[guard] force=True -> proceeding anyway")
    else:
        print(f"[guard] gate OK: live matches baseline {baseline}")
    return live


# --------------------------------------------------------------------------- #
# body slimming
# --------------------------------------------------------------------------- #
def slim_body(body: dict) -> dict:
    """Filter a workflow body to exactly what the public API accepts."""
    out = {k: body[k] for k in TOP_WHITELIST if k in body}
    out["settings"] = {k: v for k, v in (body.get("settings") or {}).items() if k in SETTINGS_WHITELIST}
    return out


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
def guarded_put(wf_id: str, body: dict, *, force: bool = False,
                stick_polls=(2, 4, 6), slim: bool = True) -> dict:
    """Version-gated, stick-checked PUT.

    1. GET live; compare live.versionId vs ledger baseline (DriftError if drifted).
    2. PUT (settings/top-level slimmed unless slim=False).
    3. Poll live versionId; assert it equals the PUT response version (StickError).
    4. Update the ledger to the new live versionId.
    Returns the final live workflow dict.
    """
    # --- VERSION GATE ---
    live = assert_baseline(wf_id, force=force)
    live_ver = live.get("versionId")

    payload = slim_body(body) if slim else body

    # --- PUT ---
    resp = _req("PUT", f"/workflows/{wf_id}", payload)
    new_ver = resp.get("versionId")
    print(f"[guard] PUT ok -> new versionId={new_ver}  nodes={len(resp.get('nodes', []))}")
    if new_ver == live_ver:
        raise StickError(f"[guard] PUT returned the same versionId ({new_ver}) — change not applied")

    # --- STICK CHECK ---
    for i, wait in enumerate(stick_polls, 1):
        time.sleep(wait)
        chk = get_workflow(wf_id)
        cur = chk.get("versionId")
        if cur != new_ver:
            raise StickError(
                f"[guard] REVERTED: after {sum(stick_polls[:i])}s live versionId is {cur}, "
                f"expected {new_ver}. A stale editor tab likely re-saved over the deploy.")
        print(f"[guard] stick poll {i}/{len(stick_polls)} (+{sum(stick_polls[:i])}s): OK ({cur})")

    _record(wf_id, new_ver, resp.get("name", ""))
    print(f"[guard] ledger updated: {wf_id} -> {new_ver}")
    return chk


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "list":
        print(json.dumps(load_ledger(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "check":
        wf_id = argv[1]
        live = get_workflow(wf_id)
        base = (load_ledger().get(wf_id) or {}).get("versionId")
        lv = live.get("versionId")
        print(f"workflow : {live.get('name')!r}  ({wf_id})")
        print(f"live ver : {lv}  nodes={len(live.get('nodes', []))}  active={live.get('active')}")
        print(f"baseline : {base}")
        if base is None:
            print("status   : NO BASELINE (run `record` to arm the gate)")
        elif base == lv:
            print("status   : ✅ MATCH — no external drift")
        else:
            print("status   : ❌ DRIFT — live changed outside this tooling")
        return 0
    if cmd == "record":
        wf_id = argv[1]
        if len(argv) > 2:
            ver, name = argv[2], ""
        else:
            live = get_workflow(wf_id)
            ver, name = live.get("versionId"), live.get("name", "")
        _record(wf_id, ver, name)
        print(f"recorded baseline {wf_id} -> {ver}")
        return 0
    print(f"unknown command {cmd!r} (expected: check | record | list)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
