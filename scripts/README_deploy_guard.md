# n8n deploy version-gate guard

`n8n_deploy_guard.py` stops the recurring drift incident where an n8n workflow
deployed via the API gets silently overwritten by a stale editor tab — and the
*next* blind PUT then clobbers whatever drifted in.

## What it does

1. **Version gate (pre-PUT):** compares the live `versionId` against the last
   version *we* deployed (a local ledger). If they differ → someone changed the
   workflow outside this tooling → **abort** and surface it. Override with
   `GUARD_FORCE=1`.
2. **Stick check (post-PUT):** polls the live `versionId` for ~12s and fails
   loudly if it reverts (immediate editor-tab re-save).
3. **Ledger:** `scripts/.n8n_deploy_versions.json` maps `workflow_id → last
   deployed versionId`. Updated automatically after every guarded deploy.

## CLI

```bash
python scripts/n8n_deploy_guard.py check  <wf_id>      # live vs ledger (read-only)
python scripts/n8n_deploy_guard.py record <wf_id> [ver]# arm/reset baseline = live (or ver)
python scripts/n8n_deploy_guard.py list                # dump the whole ledger
```

`check` status: `✅ MATCH` (safe to deploy) · `❌ DRIFT` (review first) ·
`NO BASELINE` (run `record` once to arm).

## Adopting it in a deploy script

**Single-PUT scripts** (most `scripts/deploy_*.py`, `workflows/deploy_*.py`) —
replace the raw `api("PUT", ...)` / `n8n_put(...)` call:

```python
from n8n_deploy_guard import guarded_put, DriftError, StickError
try:
    res = guarded_put(WORKFLOW_ID, body)          # gate + slim + PUT + stick + ledger
except DriftError as e:
    print(e, file=sys.stderr); sys.exit(3)        # live drifted — review, or GUARD_FORCE=1
except StickError as e:
    print(e, file=sys.stderr); sys.exit(4)        # PUT didn't stick (revert)
```

`guarded_put` slims the body to the API whitelist (`name/nodes/connections/
settings` + 8 settings keys) by default — pass `slim=False` to opt out.

**Scripts with custom activate/verify logic** (e.g. `build.py`) — keep your own
PUT and bracket it with the two helpers:

```python
from n8n_deploy_guard import assert_baseline, record_baseline, DriftError
assert_baseline(wf_id)                 # raises DriftError on drift
... your existing PUT + activate ...
record_baseline(wf_id, live_version, name)
```

## Currently integrated

- `scripts/deploy_financial_report_v2.py` — full `guarded_put`
- `PROMPT lar/_workflow_backups/build.py` — `assert_baseline` + `record_baseline`
  around its existing PUT (WhatsApp STAGING/PROD)

Baselines are armed for `vBdbn1c9YW3s4iWP` (financial), `HSy9VD6eeptkf8g2`
(WhatsApp PROD), `sHGEWgEtgXEcfAWO` (WhatsApp STAGING).

> Commit `.n8n_deploy_versions.json` to share baselines across machines; leave it
> untracked to gate per-working-copy only (a fresh checkout starts with no
> baseline and arms on first deploy).
