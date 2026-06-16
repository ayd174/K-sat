# VAPI Self-Healing & Continuous Optimization Pipeline

> Closed-loop quality system for the AYKA Transport voice assistant.
> Every VAPI call is auto-analyzed → errors logged → if critical, the system
> prompt is rewritten and queued for one-click admin approval over WhatsApp.

```
VAPI EOC ──► IVR (iCOSU74VPQLNpr00) ──fan-out──► self-healing intake (YR0w6ZS7KA65fY1A)
                  │                                       │
                  ├─► voice-agent-callback (existing)      ▼
                  └─► vapi-intake (existing)         analyzer LLM (gpt-4o-mini)
                                                           │
                                              ┌────────────┴───────────┐
                                              ▼                        ▼
                                       vapi_call_logs          is_critical?
                                                                       │
                                                                   yes │
                                                                       ▼
                                                       optimizer LLM (gpt-4o, 16k)
                                                                       │
                                                                       ▼
                                                          vapi_prompt_history
                                                            (status=pending)
                                                                       │
                                                                       ▼
                                                       Evolution → +32476528577
                                                          ✅ APPROVE  ❌ REJECT
                                                                       │ click
                                                                       ▼
                                                          GET assistant → PATCH
                                                            status=deployed
```

---

## 1. Live deployment state (AYKA — 2026-05-10)

| Component | Live value |
|---|---|
| Supabase project | `thnsfqjcwtodgfrujbyc` |
| Tables | `public.vapi_call_logs`, `public.vapi_prompt_history`, view `public.vapi_recent_error_patterns` |
| RLS | enabled, `anon` + `authenticated` deny-all; only `service_role` writes |
| n8n self-healing workflow | `YR0w6ZS7KA65fY1A` — *active* |
| Intake webhook | `https://n8n.k-sat.tech/webhook/vapi-self-healing-intake` |
| Approval webhook | `https://n8n.k-sat.tech/webhook/vapi-self-healing-approve` |
| Analyzer LLM | OpenAI `gpt-4o-mini`, max_tokens 2048, JSON mode |
| Optimizer LLM | OpenAI `gpt-4o`, max_tokens 16384, JSON mode |
| n8n credential reused | `openAiApi` id `ouQwdbKfx8YVSm8Q` (same one the WhatsApp `1 ASISTAN` workflow uses) |
| Evolution endpoint | `https://evolutionapi.k-sat.tech`, instance `Whatsapp_aydin` |
| Admin WhatsApp | `32476528577` (AYKA operator) |
| VAPI traffic source | fan-out in workflow `iCOSU74VPQLNpr00` ("3 VAPI — IVR Dil Seçimi ve Eskalasyon"), node `Forward EOC → vapi-self-healing` |
| Edit URL | https://n8n.k-sat.tech/workflow/YR0w6ZS7KA65fY1A |

> **Why hardcoded values, not `$env.*`:** this n8n instance has
> `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. Expressions like `{{ $env.X }}` and
> `$env.X` in Code nodes silently resolve to empty. The deployment script
> inlined every secret as a literal in the workflow JSON, matching the
> existing `1 ASISTAN` workflow's pattern.

---

## 2. Files in this folder

| File | What it is |
|------|------------|
| `supabase_schema.sql` | Tables + indexes + RLS + audit view. Already applied; kept for DR / new tenants. |
| `n8n_vapi_self_healing_workflow.json` | The original *design* — Anthropic + `$env.*`. The live workflow drifted from this during deploy (OpenAI + literals). Keep this as the spec; recreate the live mutations from §6 if you ever need to redeploy. |
| `README.md` | This file. |

---

## 3. How a real call flows in

1. Customer calls AYKA → VAPI assistant (FR/NL/EN/TR) takes the call.
2. End-of-call → VAPI POSTs `end-of-call-report` to its `serverUrl`, which is `https://n8n.k-sat.tech/webhook/vapi-ivr` (workflow `iCOSU74VPQLNpr00`).
3. The IVR workflow ACKs VAPI immediately, then fans out the EOC payload **in parallel** to:
   - `Forward EOC → voice-agent-callback` *(existing — writes to `voice_call_logs`)*
   - `inbound call?` → `Forward EOC → vapi-intake` *(existing — runs the intake pipeline)*
   - `Forward EOC → vapi-self-healing` *(this pipeline; `neverError:true` so a self-healing failure can never break the IVR ack chain)*
4. The intake webhook here triggers the analyzer LLM with the transcript + tool calls.
5. Analyzer returns strict JSON — errors, severity, success_score.
6. Row is written to `vapi_call_logs`. If `severity ≥ high` or `success_score < 0.5` or `errors.length ≥ 2` → enter the optimizer branch.
7. Optimizer fetches the live VAPI assistant prompt, asks `gpt-4o` for a *surgical* rewrite (max_tokens 16384), generates a UUID approval token, writes to `vapi_prompt_history` (status=pending), then sends a WhatsApp to the operator with two URLs.
8. Operator clicks **APPROVE** → approval webhook re-fetches the assistant, replaces only `model.messages[role=system].content`, PATCHes VAPI, marks history `deployed`.
9. Click **REJECT** → marks history `rejected`. VAPI is not touched.

---

## 4. Verifying it's healthy

### Recent executions

```bash
# in n8n UI: workflow YR0w6ZS7KA65fY1A → Executions tab
# or via API:
curl -s -H "X-N8N-API-KEY: $N8N_KEY" \
  "https://n8n.k-sat.tech/api/v1/executions?workflowId=YR0w6ZS7KA65fY1A&limit=10" \
  | jq '.data[] | {id, status, stoppedAt}'
```

### Recent error patterns (last 7 days)

```sql
SELECT * FROM public.vapi_recent_error_patterns;
```

### Pending proposals waiting for approval

```sql
SELECT id, assistant_id, length(new_prompt) AS new_len, reason_for_update, created_at
FROM   public.vapi_prompt_history
WHERE  status = 'pending'
ORDER  BY created_at DESC;
```

### Synthetic re-test (anytime)

```bash
curl -X POST "https://n8n.k-sat.tech/webhook/vapi-self-healing-intake" \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "call":      { "id": "smoke-XYZ" },
      "assistant": { "id": "915d3a42-9fc7-4887-bc8c-4f4a3fdff806" },
      "transcript": "Bot: c est Redeka de IKA. 2x2 ? 57 euros.",
      "summary":   "test",
      "durationSeconds": 30,
      "endedReason": "customer-ended-call"
    }
  }'
```

Then clean up:

```sql
DELETE FROM public.vapi_prompt_history
WHERE  triggering_call_id LIKE 'smoke-%' OR triggering_call_id IS NULL;
DELETE FROM public.vapi_call_logs WHERE call_id LIKE 'smoke-%';
```

---

## 5. Critical / repeating decision

In the `Parse Analysis` Code node:

```js
hasHigh        = errors.some(e => severity in ('critical','high'))
lowScore       = success_score < 0.5
many           = errors.length >= 2
isCritical     = hasHigh || lowScore
shouldOptimize = isCritical || many
```

The `vapi_recent_error_patterns` view shows error types that occurred 2+
times in the last 7 days, grouped by `assistant_id`. The workflow does
*not* yet auto-trigger on this view — every call already drives a per-call
decision. Wire the view in if you want a "pattern drift" alert.

---

## 6. Re-deploying from scratch (DR / new tenant)

### 6a. Apply the SQL

Direct DB endpoint is IPv6-only; pooler tenant lookup fails on this
network. Two reliable paths:

- **Dashboard SQL Editor** — one-click: https://supabase.com/dashboard/project/thnsfqjcwtodgfrujbyc/sql/new — paste, Run.
- **Management API + PAT** — generate a PAT at https://supabase.com/dashboard/account/tokens, then:

  ```python
  import json, urllib.request
  PAT = 'sbp_...'
  REF = 'thnsfqjcwtodgfrujbyc'
  SQL = open('supabase_schema.sql').read()
  req = urllib.request.Request(
      f'https://api.supabase.com/v1/projects/{REF}/database/query',
      data=json.dumps({'query': SQL}).encode(),
      method='POST',
      headers={
          'Authorization': f'Bearer {PAT}',
          'Content-Type':  'application/json',
          'User-Agent':    'curl/8.0.0',   # CF 1010 fix
      },
  )
  print(urllib.request.urlopen(req, timeout=120).read().decode())
  ```

  **Revoke the PAT** in the Dashboard right after.

### 6b. Import the workflow

```bash
curl -X POST "https://n8n.k-sat.tech/api/v1/workflows" \
  -H "X-N8N-API-KEY: $N8N_KEY" \
  -H "Content-Type: application/json" \
  --data @n8n_vapi_self_healing_workflow.json
```

> n8n public API rejects unknown `settings` keys with a 400 ("must NOT have
> additional properties"). Whitelist `settings` to: `executionOrder`,
> `errorWorkflow`, `timezone`, `callerPolicy`, `saveExecutionProgress`,
> `saveManualExecutions`, `saveDataErrorExecution`, `saveDataSuccessExecution`,
> `executionTimeout`. Strip `meta`, `pinData`, `tags`, `triggerCount`,
> `versionId`, `active`, `staticData (if null)` from the body.

### 6c. Mutate Anthropic → OpenAI + inline secrets

This n8n blocks `$env` access in nodes. After import, mutate every node
that uses `$env.*` to use literal values, and switch the LLM HTTP nodes
from `api.anthropic.com` to `api.openai.com/v1/chat/completions` with:

- `authentication: "predefinedCredentialType"`,
- `nodeCredentialType: "openAiApi"`,
- `credentials: { openAiApi: { id: "ouQwdbKfx8YVSm8Q", name: "OpenAi account" } }`.

The two `Build * Body` Code nodes must produce OpenAI shape:

```js
analyzer_body: {
  model: 'gpt-4o-mini',  max_tokens: 2048,
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user',   content: userMessage }
  ],
  response_format: { type: 'json_object' }
}
// optimizer: model 'gpt-4o', max_tokens 16384  (lower limits truncate the
// FR prompt rewrite mid-JSON; the parser then fail-softs to a warning)
```

The two `Parse *` Code nodes need to read `resp.choices[0].message.content`
(OpenAI) instead of (or in addition to) `resp.content[0].text` (Anthropic).

### 6d. Activate

```bash
curl -X POST "https://n8n.k-sat.tech/api/v1/workflows/$WF_ID/activate" \
  -H "X-N8N-API-KEY: $N8N_KEY"
```

### 6e. Wire VAPI in (fan-out, not overwrite)

The 5 AYKA assistants share `serverUrl=https://n8n.k-sat.tech/webhook/vapi-ivr`
which routes to workflow `iCOSU74VPQLNpr00`. Do **not** PATCH the assistant
`serverUrl` — that breaks IVR routing. Instead, in `iCOSU74VPQLNpr00`, add
a 3rd parallel branch from `Respond: ACK (End of Call)`:

```jsonc
// New HTTP Request node
{
  "name": "Forward EOC → vapi-self-healing",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2,
  "parameters": {
    "method":         "POST",
    "url":            "https://n8n.k-sat.tech/webhook/vapi-self-healing-intake",
    "sendBody":       true,
    "contentType":    "raw",
    "rawContentType": "application/json",
    "body":           "={{ JSON.stringify($('VAPI IVR Webhook').item.json.body) }}",
    "options": {
      "response": { "response": { "neverError": true, "responseFormat": "json" } },
      "timeout":  30000
    }
  }
}
```

`neverError: true` is required — a downstream self-healing failure must not
flip the IVR ack chain into an error state.

---

## 7. Safety properties

- **Service-role only** writes. RLS deny policies on both tables.
- **Single-use approval tokens.** UUID v4, unique-indexed. Replay = no-op page.
- **No silent prompt swaps.** PATCH only happens after an explicit click on the approval URL.
- **Surgical patch.** `Build VAPI Patch` re-fetches the assistant and swaps only `model.messages[role=system].content`. Provider, model, temperature, tools, voice are preserved.
- **Fail-soft optimizer.** If the LLM returns truncated/empty/unparseable JSON, the row is still written with a `parse_error` and the WhatsApp surfaces the warning. Admin sees nothing was actually changed.
- **`neverError` on the fan-out.** The IVR workflow's existing transfer / voice-callback / intake forwards continue working even if this pipeline is down.

---

## 8. Rolling back a deployed prompt

Every prior version lives in `vapi_prompt_history.old_prompt`:

```sql
SELECT id, assistant_id, deployed_at,
       length(old_prompt) AS old_len, length(new_prompt) AS new_len,
       reason_for_update
FROM   public.vapi_prompt_history
WHERE  assistant_id = '915d3a42-9fc7-4887-bc8c-4f4a3fdff806'
  AND  status = 'deployed'
ORDER  BY deployed_at DESC;
```

To restore the prompt from row `<id>`:

```python
import json, os, urllib.request, urllib.parse
PAT  = os.environ['SUPABASE_SERVICE_ROLE_KEY']
VAPI = os.environ['VAPI_PRIVATE_KEY']  # source from master .env; never hardcode
ROW  = 7

# 1. fetch old prompt
old = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"https://thnsfqjcwtodgfrujbyc.supabase.co/rest/v1/vapi_prompt_history?id=eq.{ROW}&select=assistant_id,old_prompt",
    headers={'apikey': PAT, 'Authorization': f'Bearer {PAT}', 'User-Agent':'curl/8.0.0'},
)).read())[0]

# 2. fetch live model object, swap only the system message
live = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"https://api.vapi.ai/assistant/{old['assistant_id']}",
    headers={'Authorization': f'Bearer {VAPI}', 'User-Agent':'curl/8.0.0'},
)).read())
model = live['model']
model['messages'] = [({'role':'system','content':old['old_prompt']} if m.get('role')=='system' else m)
                     for m in model.get('messages',[])]

# 3. PATCH
req = urllib.request.Request(
    f"https://api.vapi.ai/assistant/{old['assistant_id']}",
    data=json.dumps({'model': model}).encode(),
    method='PATCH',
    headers={'Authorization': f'Bearer {VAPI}', 'Content-Type':'application/json', 'User-Agent':'curl/8.0.0'},
)
print(urllib.request.urlopen(req, timeout=60).status)
```

---

## 9. Known limits / next steps

- **Per-assistant only.** The optimizer rewrites the prompt of whichever assistant produced the failed call. Cross-language consistency (FR fix → NL/EN/TR back-port) is not automatic — propose a sibling workflow if needed.
- **No rate limit.** A flood of bad calls will yield a flood of WhatsApp approval messages. Add a debounce in `Optimize?` (skip if a `pending` row with overlapping `detected_errors` exists in the last hour).
- **Repeating-pattern view unused by workflow.** `vapi_recent_error_patterns` is populated but the workflow doesn't OR it into `should_optimize`. One-node addition if you want it.
- **Optimizer is gpt-4o.** Quality > cost choice. The Ayka FR prompt is ~26k chars; rewriting at lower max_tokens truncates mid-JSON and fail-softs to "warning, no change applied".
- **Live workflow drifted from the JSON in this folder.** If you `git diff` the file vs. the n8n live state, you'll see Anthropic vs. OpenAI + `$env.*` vs. literals. Section 6 documents how to reapply the drift after a re-import.
