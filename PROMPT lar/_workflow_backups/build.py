#!/usr/bin/env python3
"""
AYKA WhatsApp workflow — unified build/sync tool.

Single entry point that consolidates v9.12.13.{4,5,6,7} build scripts into
one pipeline. Source-of-truth is `whitelist_constants.py`.

Pipeline (all idempotent — no-op when already in sync):
  P1  WHITELIST          Bölüm 9.0 + classifier JS + Confirmation subprompt
  P2  FEATURED examples  α-2 POZİTİF + B9 ÖZEL DİKKAT
  P3  LEGEND             α-2 step 2 group-min legend
  P4  CONFUSION          B9 peripheral-Grup-C block
  P5  DRIFT VERIFIER     full-prompt scan for `(Grup X min N€)` mismatches

Usage:
    python build.py STAGING          # fetch LIVE staging, sync, deploy + verify
    python build.py PROD             # same for prod
    python build.py STAGING --dry    # patch+verify, NO deploy (saves PUT file)
    python build.py verify STAGING   # drift verifier only, no patches
    python build.py verify PROD
    python build.py seed             # render Supabase postal seed SQL (site 4)
    python build.py seed --out X.sql # ...to a specific path

Snapshots written to: {env}_v9.12.13.7_LIVE_pre-build_<ts>.json
PUT payload written to: {env}_v9.12.13.7_PUT_slim.json
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from whitelist_constants import (  # noqa: E402
    POSTAL_GROUPS, POSTAL_CITIES, total_codes,
    render_js_whitelist, render_js_group_min,
    render_confirmation_block, render_postal_seed_sql,
    verify_postal_group_drift,
)
# shared version-gate guard (scripts/) — refuses to overwrite an externally
# drifted workflow and records the deployed baseline after each PUT.
sys.path.insert(0, str(ROOT.parent.parent / 'scripts'))
from n8n_deploy_guard import assert_baseline, record_baseline, DriftError  # noqa: E402

# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------
N8N_BASE = 'https://n8n.k-sat.tech/api/v1'
WORKFLOW_IDS = {
    'STAGING': 'sHGEWgEtgXEcfAWO',
    'PROD':    'HSy9VD6eeptkf8g2',
}
SETTINGS_WHITELIST = {
    'saveExecutionProgress', 'saveManualExecutions', 'saveDataErrorExecution',
    'saveDataSuccessExecution', 'executionTimeout', 'errorWorkflow',
    'timezone', 'executionOrder',
}


def _load_api_key() -> str:
    env_path = ROOT.parent.parent / '.env'
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line.startswith('N8N_API_KEY='):
            return line.split('=', 1)[1].strip()
    raise RuntimeError('N8N_API_KEY not found in master .env')


# ---------------------------------------------------------------------
# Patch functions — each returns (changed: bool, message: str)
# ---------------------------------------------------------------------

def _replace_unique(text: str, anchor_re: re.Pattern, replacement: str, capture_group: int = 1) -> tuple[str, bool, str]:
    """Find anchor_re in text; replace capture_group with replacement.
    Returns (new_text, changed_bool, msg)."""
    m = anchor_re.search(text)
    if not m:
        return text, False, 'anchor NOT FOUND'
    old = m.group(capture_group)
    new_text = text[:m.start(capture_group)] + replacement + text[m.end(capture_group):]
    if new_text == text:
        return text, False, 'already in sync (no-op)'
    return new_text, True, f'replaced ({len(old)} → {len(replacement)} chars)'


def patch_classifier_js(wf: dict) -> tuple[bool, str]:
    new_wl = render_js_whitelist()
    new_gm = render_js_group_min()
    for n in wf['nodes']:
        if n['name'] != '_postal_classifier':
            continue
        js = n['parameters']['jsCode']
        changed_any = False
        m_wl = re.search(r"var WHITELIST = \{[^}]*\};", js)
        if not m_wl:
            return False, 'FATAL: WHITELIST anchor not found'
        if js[m_wl.start():m_wl.end()] != new_wl:
            js = js[:m_wl.start()] + new_wl + js[m_wl.end():]
            changed_any = True
        m_gm = re.search(r"var GROUP_MIN = \{[^}]*\};", js)
        if not m_gm:
            return False, 'FATAL: GROUP_MIN anchor not found'
        if js[m_gm.start():m_gm.end()] != new_gm:
            js = js[:m_gm.start()] + new_gm + js[m_gm.end():]
            changed_any = True
        n['parameters']['jsCode'] = js
        return changed_any, ('replaced WHITELIST/GROUP_MIN' if changed_any else 'already in sync')
    return False, 'FATAL: _postal_classifier node not found'


def patch_confirmation_subprompt(wf: dict) -> tuple[bool, str]:
    new_block = render_confirmation_block()
    for n in wf['nodes']:
        if n['name'] != 'Generate Confirmation Message':
            continue
        vals = (n['parameters'].get('responses') or {}).get('values') or []
        if not vals:
            return False, 'FATAL: Confirmation Message responses.values empty'
        s = vals[0]['content']
        pat = re.compile(
            r"Service area whitelist \(canonical — synced with Bölüm 9\.0 v9\.12\.7\):\n"
            r"(     Group A:.*\n     Group B:.*\n     Group C:.*\n     Group D:.*)\n"
        )
        m = pat.search(s)
        if not m:
            return False, 'FATAL: Confirmation anchor not found'
        old_block = m.group(1)
        s_new = s.replace(old_block, new_block, 1)
        changed = s_new != s
        vals[0]['content'] = s_new
        return changed, ('replaced' if changed else 'already in sync')
    return False, 'FATAL: Generate Confirmation Message node not found'


PATCHES: list[tuple[str, Callable[[dict], tuple[bool, str]]]] = [
    # RETIRED 2026-06-08: the monolithic Asistani prompt blocks (Bolum 9.0 /
    # alpha-2 / OZEL DIKKAT / legend / confusion) were removed when the bot moved
    # to the lightweight NLU + DB + state-machine architecture, so P1b/P2a/P2b/
    # P3/P4 no longer have anchors. Postal codes now also sync to the DB via
    # `build.py seed`. Only the two still-live prompt-sync sites remain:
    ('P1a  whitelist:classifier-js',     patch_classifier_js),
    ('P1c  whitelist:confirmation-sub',  patch_confirmation_subprompt),
]


# ---------------------------------------------------------------------
# Drift verifier
# ---------------------------------------------------------------------

def run_drift_verifier(wf: dict) -> tuple[bool, list[str]]:
    """Returns (clean: bool, issues: list[str])."""
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        issues = verify_postal_group_drift(sm)
        return (len(issues) == 0), issues
    return False, ['Asistani node not found']


# ---------------------------------------------------------------------
# Self-consistency check (cross-validate live sites: classifier + confirmation)
# ---------------------------------------------------------------------

def run_self_consistency(wf: dict) -> tuple[bool, list[str]]:
    fails: list[str] = []
    src_by_grp = {g: set(d['codes']) for g, d in POSTAL_GROUPS.items()}

    for n in wf['nodes']:
        if n['name'] == '_postal_classifier':
            js = n['parameters']['jsCode']
            by_grp: dict[str, set] = {}
            for c, g in re.findall(r"'([0-9]{4})'\s*:\s*'([A-D])'", js):
                by_grp.setdefault(g, set()).add(c)
            for g, src_set in src_by_grp.items():
                if by_grp.get(g, set()) != src_set:
                    fails.append(f'  P1a Classifier Group {g} drift')
        elif n['name'] == 'Generate Confirmation Message':
            s = n['parameters']['responses']['values'][0]['content']
            for g in 'ABCD':
                m = re.search(rf"     Group {g}:\s*([0-9 ]+)\n", s)
                if not m:
                    fails.append(f'  P1c Confirmation Group {g} not found')
                    continue
                if set(m.group(1).split()) != src_by_grp[g]:
                    fails.append(f'  P1c Confirmation Group {g} drift')
    return (len(fails) == 0), fails


# ---------------------------------------------------------------------
# n8n IO
# ---------------------------------------------------------------------

def n8n_get(path: str, key: str) -> dict:
    req = urllib.request.Request(f'{N8N_BASE}{path}',
                                  headers={'X-N8N-API-KEY': key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def n8n_put(wf_id: str, payload: dict, key: str) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        f'{N8N_BASE}/workflows/{wf_id}',
        data=data, method='PUT',
        headers={'X-N8N-API-KEY': key, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def n8n_activate(wf_id: str, key: str) -> None:
    req = urllib.request.Request(
        f'{N8N_BASE}/workflows/{wf_id}/activate',
        data=b'{}', method='POST',
        headers={'X-N8N-API-KEY': key, 'Content-Type': 'application/json'},
    )
    urllib.request.urlopen(req, timeout=30)


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------

def run(env: str, deploy: bool, verify_only: bool) -> int:
    key = _load_api_key()
    wf_id = WORKFLOW_IDS[env]
    env_lc = env.lower()

    print(f"=== build.py — env={env}  deploy={deploy}  verify_only={verify_only} ===")
    print(f"source-of-truth: {total_codes()} codes across "
          f"{len(POSTAL_GROUPS)} groups (sites: P1a classifier, P1c confirmation, DB seed)\n")

    # 1) Fetch LIVE
    print(f"[fetch] GET workflow {wf_id}")
    wf = n8n_get(f'/workflows/{wf_id}', key)
    live_name = wf.get('name')
    live_active = wf.get('active')
    live_updated = wf.get('updatedAt')
    print(f"  live: {live_name!r}  active={live_active}  updated={live_updated}")

    # 2) Snapshot
    ts = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    snap = ROOT / f'{env_lc}_LIVE_pre-build_{ts}.json'
    snap.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  snapshot → {snap.name}\n")

    if verify_only:
        print("[verify-only] skipping patches\n")
    else:
        # 3) Apply patches
        print("[patch]")
        any_failed = False
        changed_count = 0
        noop_count = 0
        for label, fn in PATCHES:
            changed, msg = fn(wf)
            tag = '✅' if not msg.startswith('FATAL') else '❌'
            mark = ' (changed)' if changed else ''
            print(f"  {tag} {label:<36} {msg}{mark}")
            if msg.startswith('FATAL'):
                any_failed = True
            elif changed:
                changed_count += 1
            else:
                noop_count += 1
        if any_failed:
            print("\n[patch] FAILED — aborting")
            return 1
        print(f"\n  total: {changed_count} changed, {noop_count} no-op\n")

    # 4) Drift verifier (always runs)
    print("[drift]")
    clean, issues = run_drift_verifier(wf)
    if clean:
        print("  ✅ no drift detected in calculation examples\n")
    else:
        print(f"  ❌ {len(issues)} drift issues:")
        for i in issues:
            print(i)
        print("\n[drift] FAILED — aborting deploy")
        return 1

    # 5) Self-consistency (always runs)
    print("[self-consistency]")
    consistent, fails = run_self_consistency(wf)
    if consistent:
        print("  ✅ live sites (P1a classifier + P1c confirmation) match POSTAL_GROUPS source\n")
    else:
        print("  ❌ inconsistencies:")
        for f in fails:
            print(f)
        return 1

    # 6) Save PUT payload (always — useful for inspection)
    payload = {
        'name': wf.get('name', live_name),
        'nodes': wf['nodes'],
        'connections': wf['connections'],
        'settings': {k: v for k, v in (wf.get('settings') or {}).items() if k in SETTINGS_WHITELIST},
    }
    out = ROOT / f'{env_lc}_PUT_slim.json'
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[save] {out.name}  ({out.stat().st_size:,} bytes)\n")

    # 7) Deploy
    if not deploy:
        print("[deploy] --dry skipped\n")
        return 0
    if verify_only:
        print("[deploy] verify-only skipped\n")
        return 0

    print(f"[deploy] PUT → {env}")
    # VERSION GATE — abort if the live workflow drifted from our last deploy
    # (e.g. a stale editor tab re-saved over it). Override with GUARD_FORCE=1.
    try:
        assert_baseline(wf_id)
    except DriftError as e:
        print(str(e), file=sys.stderr)
        print("\n[deploy] ABORTED — review the external change, then re-run "
              "(GUARD_FORCE=1 to overwrite).", file=sys.stderr)
        return 3
    resp = n8n_put(wf_id, payload, key)
    print(f"  PUT 200 — name={resp.get('name')}  active={resp.get('active')}  updated={resp.get('updatedAt')}")

    # Ensure active
    time.sleep(2)
    v = n8n_get(f'/workflows/{wf_id}', key)
    if not v.get('active'):
        n8n_activate(wf_id, key)
        print(f"  re-activated")
        time.sleep(2)
        v = n8n_get(f'/workflows/{wf_id}', key)
    print(f"  final: name={v.get('name')!r}  active={v.get('active')}\n")
    record_baseline(wf_id, v.get('versionId'), v.get('name', ''))
    print(f"  [guard] ledger baseline updated -> {v.get('versionId')}\n")
    return 0


# ---------------------------------------------------------------------
# Seed generation (site 4 — Supabase postal_codes_whitelist)
# ---------------------------------------------------------------------

def run_seed(out_path: Path | None) -> int:
    """Render the Supabase postal seed SQL from POSTAL_GROUPS/POSTAL_CITIES.

    Importing whitelist_constants already ran _validate_cities() (fails fast if
    the code/city sets diverge), so reaching here means the source is internally
    consistent. Writes the generated INSERT to out_path and prints a summary.
    """
    sql = render_postal_seed_sql()
    n_codes = total_codes()
    # Sanity: rendered row count must equal source code count (no silent loss).
    rendered_rows = sql.count('\n    (NULL,')
    if rendered_rows != n_codes:
        print(f"❌ seed render mismatch: {rendered_rows} rows vs {n_codes} source codes",
              file=sys.stderr)
        return 1

    if out_path is None:
        out_path = ROOT / 'generated_postal_seed.sql'
    banner = (
        "-- GENERATED by build.py seed — DO NOT EDIT BY HAND.\n"
        "-- Source of truth: whitelist_constants.py (POSTAL_GROUPS + POSTAL_CITIES).\n"
        "-- Requires partial unique index uniq_global_postal_code "
        "(migration 20260608120000).\n\n"
    )
    out_path.write_text(banner + sql + "\n", encoding='utf-8')

    print(f"=== build.py seed ===")
    print(f"source-of-truth: {n_codes} codes across "
          f"{len(POSTAL_GROUPS)} groups / {len(POSTAL_CITIES)} city labels")
    print(f"  rendered rows : {rendered_rows} (matches source ✅)")
    print(f"  written → {out_path}")
    print("\nApply to Supabase as a forward migration (or copy into one). "
          "Idempotent upsert; safe to re-run.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog='build.py', description='AYKA workflow sync')
    ap.add_argument('action', nargs='?', help='STAGING | PROD | verify | seed')
    ap.add_argument('env', nargs='?', help='env when action=verify (STAGING|PROD)')
    ap.add_argument('--dry', action='store_true', help='skip the PUT step')
    ap.add_argument('--out', help='output path for seed SQL (action=seed)')
    args = ap.parse_args()

    if not args.action:
        ap.print_help()
        return 2

    action = args.action.upper()
    if action in WORKFLOW_IDS:
        return run(env=action, deploy=not args.dry, verify_only=False)
    if action == 'VERIFY':
        if not args.env:
            print("ERR: verify needs env (STAGING|PROD)", file=sys.stderr); return 2
        env = args.env.upper()
        if env not in WORKFLOW_IDS:
            print(f"ERR: unknown env {env}", file=sys.stderr); return 2
        return run(env=env, deploy=False, verify_only=True)
    if action == 'SEED':
        return run_seed(Path(args.out) if args.out else None)
    print(f"ERR: unknown action {action!r} (expected STAGING|PROD|verify|seed)", file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
