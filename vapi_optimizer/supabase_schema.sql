-- ============================================================================
-- VAPI Self-Healing & Continuous Optimization Pipeline
-- Schema for AYKA Transport — generated 2026-05-10
-- ----------------------------------------------------------------------------
-- Run as service_role (e.g. via Supabase SQL Editor or `supabase db execute`).
-- Idempotent: safe to re-run.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Call analysis log (one row per VAPI end-of-call-report)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.vapi_call_logs (
  id                 BIGSERIAL PRIMARY KEY,
  call_id            TEXT        NOT NULL UNIQUE,
  assistant_id       TEXT,
  transcript         TEXT,
  summary            TEXT,
  duration           NUMERIC,
  ended_reason       TEXT,
  tool_calls         JSONB       NOT NULL DEFAULT '[]'::jsonb,
  success_score      NUMERIC,
  detected_errors    JSONB       NOT NULL DEFAULT '[]'::jsonb,
  is_critical        BOOLEAN     NOT NULL DEFAULT FALSE,
  analysis_summary   TEXT,
  raw_payload        JSONB,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  public.vapi_call_logs IS 'Per-call analysis output from the self-healing pipeline.';
COMMENT ON COLUMN public.vapi_call_logs.detected_errors IS 'Array of {type, severity, description} objects from the Analyzer LLM.';
COMMENT ON COLUMN public.vapi_call_logs.success_score   IS 'Float 0..1 from Analyzer LLM. NULL when not parseable.';
COMMENT ON COLUMN public.vapi_call_logs.is_critical     IS 'TRUE when severity>=high or success_score<0.5; drives optimizer trigger.';

CREATE INDEX IF NOT EXISTS idx_vapi_call_logs_assistant_created
  ON public.vapi_call_logs (assistant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vapi_call_logs_critical
  ON public.vapi_call_logs (created_at DESC)
  WHERE is_critical = TRUE;

CREATE INDEX IF NOT EXISTS idx_vapi_call_logs_errors_gin
  ON public.vapi_call_logs USING gin (detected_errors);

-- ----------------------------------------------------------------------------
-- 2. Prompt history (one row per proposed optimization)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.vapi_prompt_history (
  id                  BIGSERIAL PRIMARY KEY,
  assistant_id        TEXT        NOT NULL,
  old_prompt          TEXT,
  new_prompt          TEXT        NOT NULL,
  reason_for_update   TEXT,
  detected_errors     JSONB       NOT NULL DEFAULT '[]'::jsonb,
  triggering_call_id  TEXT,
  approval_token      TEXT        NOT NULL UNIQUE,
  status              TEXT        NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending','approved','deployed','rejected','failed','no_op','hallucinated')),
  approved_at         TIMESTAMPTZ,
  deployed_at         TIMESTAMPTZ,
  rejected_at         TIMESTAMPTZ,
  error_message       TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Soft FK to call_logs (set null on delete to preserve history if a call is purged)
ALTER TABLE public.vapi_prompt_history
  DROP CONSTRAINT IF EXISTS vapi_prompt_history_triggering_call_id_fkey;
ALTER TABLE public.vapi_prompt_history
  ADD  CONSTRAINT vapi_prompt_history_triggering_call_id_fkey
  FOREIGN KEY (triggering_call_id)
  REFERENCES public.vapi_call_logs(call_id)
  ON DELETE SET NULL;

COMMENT ON TABLE  public.vapi_prompt_history IS 'Audit trail of every proposed and deployed system-prompt change.';
COMMENT ON COLUMN public.vapi_prompt_history.approval_token IS 'Opaque single-use token emitted to the admin via WhatsApp.';
COMMENT ON COLUMN public.vapi_prompt_history.status         IS 'pending → approved → deployed | rejected | failed | no_op (guard: prompt unchanged) | hallucinated (guard: LLM invented change).';

CREATE INDEX IF NOT EXISTS idx_vapi_prompt_history_assistant
  ON public.vapi_prompt_history (assistant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_vapi_prompt_history_token
  ON public.vapi_prompt_history (approval_token);

CREATE INDEX IF NOT EXISTS idx_vapi_prompt_history_pending
  ON public.vapi_prompt_history (created_at DESC)
  WHERE status = 'pending';

-- ----------------------------------------------------------------------------
-- 3. updated_at trigger
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.vapi_optimizer_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_vapi_prompt_history_updated_at
  ON public.vapi_prompt_history;
CREATE TRIGGER trg_vapi_prompt_history_updated_at
  BEFORE UPDATE ON public.vapi_prompt_history
  FOR EACH ROW
  EXECUTE FUNCTION public.vapi_optimizer_set_updated_at();

-- ----------------------------------------------------------------------------
-- 4. Row Level Security
-- service_role bypasses RLS by default; we explicitly deny anon / authenticated
-- so that a leaked anon key cannot read transcripts or prompt diffs.
-- ----------------------------------------------------------------------------
ALTER TABLE public.vapi_call_logs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vapi_prompt_history  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "deny_anon_call_logs"            ON public.vapi_call_logs;
DROP POLICY IF EXISTS "deny_authenticated_call_logs"   ON public.vapi_call_logs;
DROP POLICY IF EXISTS "deny_anon_prompt_history"       ON public.vapi_prompt_history;
DROP POLICY IF EXISTS "deny_authenticated_prompt_hist" ON public.vapi_prompt_history;

CREATE POLICY "deny_anon_call_logs"
  ON public.vapi_call_logs            FOR ALL TO anon          USING (FALSE);
CREATE POLICY "deny_authenticated_call_logs"
  ON public.vapi_call_logs            FOR ALL TO authenticated USING (FALSE);
CREATE POLICY "deny_anon_prompt_history"
  ON public.vapi_prompt_history       FOR ALL TO anon          USING (FALSE);
CREATE POLICY "deny_authenticated_prompt_hist"
  ON public.vapi_prompt_history       FOR ALL TO authenticated USING (FALSE);

-- ----------------------------------------------------------------------------
-- 5. Convenience view: recurring error patterns over the last 7 days
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.vapi_recent_error_patterns AS
SELECT
  assistant_id,
  err->>'type'      AS error_type,
  err->>'severity'  AS severity,
  COUNT(*)          AS occurrences,
  MAX(created_at)   AS last_seen
FROM public.vapi_call_logs,
     LATERAL jsonb_array_elements(detected_errors) AS err
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY assistant_id, err->>'type', err->>'severity'
HAVING COUNT(*) >= 2
ORDER BY occurrences DESC, last_seen DESC;

COMMENT ON VIEW public.vapi_recent_error_patterns IS
  'Errors that occurred 2+ times in the last 7 days — used to flag "repeating" issues.';
