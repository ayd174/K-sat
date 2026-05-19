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

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from whitelist_constants import (  # noqa: E402
    POSTAL_GROUPS, total_codes,
    FEATURED_ALPHA2, FEATURED_B9, CONFUSING_GROUPC_CODES,
    render_js_whitelist, render_js_group_min,
    render_prompt_block_b9, render_confirmation_block,
    render_alpha2_positives, render_b9_special_attention,
    render_group_min_legend, render_confusion_groupc_block,
    verify_postal_group_drift,
)

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


def patch_prompt_b9_whitelist(wf: dict) -> tuple[bool, str]:
    new_block = render_prompt_block_b9()
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        pat = re.compile(
            r"WHITELIST \(Belçika - Brüksel ve çevresi\) — v9\.12\.4 TEK SATIR FORMAT:\n"
            r"(    Grup A.*\n    Grup B.*\n    Grup C.*\n    Grup D.*)\n"
        )
        m = pat.search(sm)
        if not m:
            return False, 'FATAL: B9 whitelist anchor not found'
        old_block = m.group(1)
        sm_new = sm.replace(old_block, new_block, 1)
        changed = sm_new != sm
        n['parameters']['options']['systemMessage'] = sm_new
        return changed, ('replaced' if changed else 'already in sync')
    return False, 'FATAL: Asistani node not found'


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


def patch_alpha2_positives(wf: dict) -> tuple[bool, str]:
    new_block = render_alpha2_positives()
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        pat = re.compile(
            r"(POZİTİF ÖRNEKLER \(Bölüm 9\.0'dan alıntı, doğrudan kullan\):\n)"
            r"((?:  - \d{4} \([^)]+\)\s*→ Grup [A-D] →\s*\d+€ min → KAPSAMDA\n){4,8})"
        )
        m = pat.search(sm)
        if not m:
            return False, 'FATAL: α-2 positives anchor not found'
        old_block = m.group(2).rstrip('\n')
        sm_new = sm.replace(old_block, new_block, 1)
        changed = sm_new != sm
        n['parameters']['options']['systemMessage'] = sm_new
        return changed, ('replaced' if changed else 'already in sync')
    return False, 'FATAL: Asistani node not found'


def patch_b9_special_attention(wf: dict) -> tuple[bool, str]:
    new_block = render_b9_special_attention()
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        pat = re.compile(
            r"(ÖZEL DİKKAT — SIK İHLAL EDİLEN POSTA KODLARI:\n)"
            r"((?:  \d{4} \([^)]+\)\s*→ Grup [A-D] →\s*\d+€ min\s*→ ✅ KAPSAMDA\n){4,8})"
        )
        m = pat.search(sm)
        if not m:
            return False, 'FATAL: B9 special attention anchor not found'
        old_block = m.group(2).rstrip('\n')
        sm_new = sm.replace(old_block, new_block, 1)
        changed = sm_new != sm
        n['parameters']['options']['systemMessage'] = sm_new
        return changed, ('replaced' if changed else 'already in sync')
    return False, 'FATAL: Asistani node not found'


def patch_alpha2_step2_legend(wf: dict) -> tuple[bool, str]:
    new_legend = render_group_min_legend()
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        pat = re.compile(r"(  2\. Grup minimum tutarını ÖĞREN \()([^)]+)(\)\.)")
        m = pat.search(sm)
        if not m:
            return False, 'FATAL: α-2 step 2 legend anchor not found'
        if m.group(2) == new_legend:
            return False, 'already in sync'
        sm_new = sm[:m.start(2)] + new_legend + sm[m.end(2):]
        n['parameters']['options']['systemMessage'] = sm_new
        return True, f'replaced ({m.group(2)!r} → {new_legend!r})'
    return False, 'FATAL: Asistani node not found'


def patch_confusion_block(wf: dict) -> tuple[bool, str]:
    new_block = render_confusion_groupc_block()
    for n in wf['nodes']:
        if n['name'] != 'Akilli WhatsApp Asistani':
            continue
        sm = n['parameters']['options']['systemMessage']
        pat = re.compile(
            r"(  ⚠️ ÖZEL DİKKAT — [^\n:]+,\n"
            r"    [^\n:]+:\n"
            r"    Bu kodlar GRUP C'dir \(\d+€\), Grup A DEĞİL\.\n"
            r"    Müşteri \"vous venez à partir de \d+€ chez moi\" derse, bu kodlar\n"
            r"    için DOĞRUDUR\.)"
        )
        m = pat.search(sm)
        if not m:
            return False, 'FATAL: confusion block anchor not found'
        old_block = m.group(1)
        sm_new = sm.replace(old_block, new_block, 1)
        changed = sm_new != sm
        n['parameters']['options']['systemMessage'] = sm_new
        return changed, ('replaced' if changed else 'already in sync')
    return False, 'FATAL: Asistani node not found'


PATCHES: list[tuple[str, Callable[[dict], tuple[bool, str]]]] = [
    ('P1a  whitelist:classifier-js',     patch_classifier_js),
    ('P1b  whitelist:b9-prompt',         patch_prompt_b9_whitelist),
    ('P1c  whitelist:confirmation-sub',  patch_confirmation_subprompt),
    ('P2a  featured:alpha2-positives',   patch_alpha2_positives),
    ('P2b  featured:b9-special',         patch_b9_special_attention),
    ('P3   legend:alpha2-step2',         patch_alpha2_step2_legend),
    ('P4   confusion:groupc',            patch_confusion_block),
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
# Self-consistency check (cross-validate all 7 sites against source)
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
        elif n['name'] == 'Akilli WhatsApp Asistani':
            sm = n['parameters']['options']['systemMessage']
            for g in 'ABCD':
                m = re.search(rf"    Grup {g} \([^)]+\)\s*:\s*([0-9 ]+)\n", sm)
                if not m:
                    fails.append(f'  P1b B9 Group {g} not found')
                    continue
                if set(m.group(1).split()) != src_by_grp[g]:
                    fails.append(f'  P1b B9 Group {g} drift')
            # Featured
            for code, lbl in FEATURED_ALPHA2:
                grp = next(g for g, d in POSTAL_GROUPS.items() if code in d['codes'])
                min_eur = POSTAL_GROUPS[grp]['min_eur']
                if f"{code} ({lbl})" not in sm:
                    fails.append(f'  P2a α-2 missing {code} ({lbl})')
            for code, lbl in FEATURED_B9:
                if f"{code} ({lbl})" not in sm:
                    fails.append(f'  P2b B9 special missing {code} ({lbl})')
            # Legend
            if f"({render_group_min_legend()})" not in sm:
                fails.append('  P3 legend not in α-2 step 2')
            # Confusion
            for code, lbl in CONFUSING_GROUPC_CODES:
                if f"{lbl} ({code})" not in sm:
                    fails.append(f'  P4 confusion missing {lbl} ({code})')
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
    print(f"source-of-truth: {total_codes()} codes / "
          f"FEATURED_ALPHA2={len(FEATURED_ALPHA2)} / "
          f"FEATURED_B9={len(FEATURED_B9)} / "
          f"CONFUSING_GROUPC={len(CONFUSING_GROUPC_CODES)}")
    print(f"legend: {render_group_min_legend()}\n")

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
        print("  ✅ all 7 sites match POSTAL_GROUPS source\n")
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
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog='build.py', description='AYKA workflow sync')
    ap.add_argument('action', nargs='?', help='STAGING | PROD | verify')
    ap.add_argument('env', nargs='?', help='env when action=verify (STAGING|PROD)')
    ap.add_argument('--dry', action='store_true', help='skip the PUT step')
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
    print(f"ERR: unknown action {action!r} (expected STAGING|PROD|verify)", file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
