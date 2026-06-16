# ADR-004 — Staging/Prod Data Plane Isolation

**Status:** ACCEPTED — Phase 1 (deactivation) applied 2026-05-24 16:30 UTC. **Phase 2 D3 applied 2026-05-24 19:55 UTC.**

**Context:**
Pre-2026-05-24 setup had two n8n workflows labeled "staging" (`sHGEWgEtgXEcfAWO`) and "prod" (`HSy9VD6eeptkf8g2`). The "staging" label suggested data plane isolation, but credentials and tableIds were shared:

| Resource | Staging | Prod | Isolated? |
|---|---|---|---|
| n8n webhook URL | `staging-v9129-…` | `whatsapp-…` | ✅ Yes |
| Supabase credential | `hFObQzrX6bkf1WCi` | `hFObQzrX6bkf1WCi` | ❌ Shared |
| Supabase host | `thnsfqjcwtodgfrujbyc.supabase.co` | same | ❌ Shared |
| `orders` tableId | `orders` | `orders` | ❌ Shared |
| Other write tables | `bot_pause_state`, `bot_global_rules`, `buffer_message` (RPC) | same | ❌ Shared |
| Evolution credential (Whatsapp_aydin) | shared | shared | ❌ Shared |
| Twilio credential | shared | shared | ❌ Shared |

**Incident (2026-05-24):** Director's synthetic UAT POST to staging webhook (exec 17813, "pazartesi" baseline) executed `Save Confirmed Order` → wrote ORD-0385 into prod `orders` table with NULL carpet/total/geocoding. Real WhatsApp confirmation was sent to the test customer via shared Evolution credential. The phantom order then blocked the user's real test via duplicate-guard (`Send Duplicate Message`). 36 write-capable nodes in staging workflow shared all production resources.

**Decision:** Three-phase remediation.

### Phase 1 — IMMEDIATE (applied 2026-05-24 16:30 UTC)

Deactivate the staging workflow entirely (`active=false`). No staging webhook accepts requests. Trade-off: lose synthetic UAT capability. Mitigation: synthetic UAT pattern (`[[feedback_synthetic_uat_pattern]]`) is itself risky per `[[feedback_sentetic_uat_quota_burn]]` — temporary loss is acceptable.

### Phase 2 D3 — APPLIED 2026-05-24 19:55 UTC

Implemented `_apply_phase2_staging_isolation_20260524.py`:
- Set `disabled: true` on 35 write-capable nodes in staging workflow
- Re-enabled `Buffer Upsert` + `Claim Buffer` (2 nodes) after first smoke test
  failed at `If Is Owner` gate (passthrough lost `is_owner` flag); these write
  to transient `buffer_message` table (auto-claimed within 12s, low risk)
- Final state: **33 write-capable nodes disabled** in staging
- Staging workflow re-activated (`active: true`)

Disabled categories (33 nodes):
- Supabase orders writes (4): Save Pending/Confirmed Order, Update/Cancel
- Supabase HTTP writes (6): Set Bot Pause, bot_global_rules (4), Evolution delete
- Evolution WhatsApp send (16): all 16 send nodes
- Twilio SMS (6): all 6 send nodes
- Telegram (1): Send a text message

Still enabled (read-only / agent input):
- All READ nodes (Check Customer/Pending/Confirmed Order, Check Bot Pause,
  Fetch Active Rules, _postal_classifier)
- Agent pipeline (Akilli WhatsApp Asistani, Output Validator, Slot Guard,
  Validate Customer Data2, Parse Customer Data, Check Data Complete,
  Validate Required Fields)
- Buffer Upsert + Claim Buffer (writes to transient buffer_message,
  required for flow completeness)

**Smoke test results (2026-05-24 19:54 + 19:55 UTC):**

| Test | Result | Side-effects |
|---|---|---|
| Smoke 1 (all 35 disabled) | Agent didn't run (If Is Owner gate failed due to passthrough schema) | 0 prod writes ✅ |
| Smoke 2 (33 disabled, Buffer+Claim re-enabled) | Agent ran, response generated correctly | 0 prod writes ✅ |

DB verification post-smoke: `orders` no new rows for test phone,
`bot_pause_state` unchanged, no WhatsApp delivered to test customer.

**Remaining limitations:**
- Buffer_message table receives staging UAT entries (transient, low risk)
- Save Confirmed Order disabled = staging can't fully test save path
- Send_X disabled = staging response never reaches customer (visible only
  in n8n exec log)
- NAME PLACEHOLDER GUARD (v9.12.13.13) not consistently honored by LLM —
  needs prompt reinforcement (future sprint)

### Phase 2 — ORIGINAL OPTIONS (kept for reference)

When staging UAT capability is needed again, implement one of:

**Option D1 — Separate Supabase project** (cleanest)
- Provision new Supabase project for staging
- Migrate schema (orders, customers, bot_pause_state, bot_global_rules, conversation_history, buffer_message + RPC functions)
- Create new `supabaseApi` n8n credential bound to staging project
- Update staging workflow's all 4 Supabase nodes + 9 HTTP write nodes
- Set up DB seed scripts so staging has realistic test customers

**Option D2 — Same project, separate schema** (mid-tier)
- `CREATE SCHEMA staging`
- Mirror all write tables (`staging.orders`, `staging.bot_pause_state`, …)
- Create staging-only Postgres role with `USAGE` on `staging` schema only
- New n8n credential with that role
- Update staging workflow's `tableId` values to schema-prefixed (PostgREST: header `Accept-Profile: staging`)

**Option D3 — Terminal-guard pattern + log-only outbound** (preserves existing infra)
- Pattern from `[[feedback_workflow_terminal_guard]]`: Code node before each write throws if `$workflow.id !== EXPECTED_PROD_ID`
- For staging workflow: Code node short-circuits to mock-success
- Evolution send nodes redirect `remoteJid` to a sandbox JID or skip outright
- Twilio nodes disabled
- Most pragmatic but most touch points (36 nodes)

**Option D4 — Sandbox WhatsApp number** (orthogonal)
- Provision a separate WhatsApp business number for staging
- Different Evolution instance (e.g., `Whatsapp_aydin_staging`)
- Different credential
- Combined with D2 or D3 for DB

### Phase 3 — DEFENSIVE GUARDS (any future workflow)

For ALL future write-capable workflows (production or staging), require:
1. Workflow ID guard Code node at entry: log `$workflow.id` + assert against allowlist
2. Per-write-node guard with terminal-throw pattern
3. Naming convention: workflow name MUST include `[PROD]` or `[STAGING]` suffix
4. Credential graph audit before every UAT (`[[feedback_staging_is_not_isolated]]`)

**Consequences:**

- ✅ No more synthetic UAT side-effects to prod data
- ✅ No more accidental WhatsApp sends to real customers from "staging"
- ❌ Lose ability to run synthetic UAT until Phase 2 is implemented
- ❌ Future regressions must be validated either (a) locally via prompt-only inspection, (b) by user manually testing in prod with bot pause active, or (c) by Phase 2 work

**Cross-refs:**
- `project_ayka_phantom_ord0385_incident_2026_05_24.md` — incident timeline
- `feedback_staging_is_not_isolated.md` — pre-UAT credential audit rule
- `feedback_workflow_terminal_guard.md` — terminal-guard pattern from earlier work
- `reference_supabase_branching_pro_plan.md` — Pro plan branching deferred (related)
- `reference_ayka_repo_ecosystem.md` — overall AYKA architecture
