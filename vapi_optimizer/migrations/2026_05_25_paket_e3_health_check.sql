-- ============================================================================
-- Paket E §3 — VAPI Self-Health-Check dedup table + RPC
-- 2026-05-25 / Solution_Analyst
-- ----------------------------------------------------------------------------
-- SCOPE: Yalnız VAPI_HEALTH_GUARDIAN workflow'unun alert dedup ihtiyacı için.
-- SPEC §3c'deki self-learning extension'ları (vapi_optimizer_dedup,
-- vapi_prompt_efficacy, vapi_optimizer_hints, prompt_history backport sütunları)
-- BU PAKETIN scope'unda DEĞIL — Paket F/G'de uygulanacak.
--
-- Idempotent — güvenli re-run.
-- Apply via Supabase Studio SQL Editor (project thnsfqjcwtodgfrujbyc).
-- Referans:
--   - reference_n8n_alert_pipeline.md (mevcut should_send_alert deseni)
--   - feedback_supabase_function_revoke_public.md (PUBLIC REVOKE şart)
--   - feedback_supabase_function_replace_verify.md (prosrc fingerprint assert)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. DEDUP TABLE
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.vapi_health_alert_log (
  id                    BIGSERIAL    PRIMARY KEY,
  alert_type            TEXT         NOT NULL,          -- e.g. silent_period_workhours, workflow_exec_starvation
  first_seen_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  last_seen_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  hit_count             INT          NOT NULL DEFAULT 1,
  suppressed_since      TIMESTAMPTZ,
  CONSTRAINT uq_vapi_health_alert_log_type UNIQUE (alert_type)
);

CREATE INDEX IF NOT EXISTS idx_vapi_health_alert_log_last_seen
  ON public.vapi_health_alert_log (last_seen_at DESC);

COMMENT ON TABLE public.vapi_health_alert_log IS
  'Dedup ledger for VAPI_HEALTH_GUARDIAN alerts; one row per alert_type. Updated by should_send_vapi_health_alert RPC.';
COMMENT ON COLUMN public.vapi_health_alert_log.suppressed_since IS
  'Timestamp of the last alert actually sent for this type. New alerts suppressed until window_min elapses.';

-- ----------------------------------------------------------------------------
-- 2. RLS (deny anon + authenticated; service_role bypasses)
-- ----------------------------------------------------------------------------
ALTER TABLE public.vapi_health_alert_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "deny_anon_vapi_health_alert_log"           ON public.vapi_health_alert_log;
DROP POLICY IF EXISTS "deny_authenticated_vapi_health_alert_log"  ON public.vapi_health_alert_log;

CREATE POLICY "deny_anon_vapi_health_alert_log"
  ON public.vapi_health_alert_log
  FOR ALL TO anon
  USING (FALSE) WITH CHECK (FALSE);

CREATE POLICY "deny_authenticated_vapi_health_alert_log"
  ON public.vapi_health_alert_log
  FOR ALL TO authenticated
  USING (FALSE) WITH CHECK (FALSE);

-- Direct DML grant cleanup (defense in depth — RLS deny is primary)
REVOKE ALL ON TABLE public.vapi_health_alert_log FROM PUBLIC, anon, authenticated;
GRANT  ALL ON TABLE public.vapi_health_alert_log TO   service_role;
GRANT  USAGE, SELECT ON SEQUENCE public.vapi_health_alert_log_id_seq TO service_role;

-- ----------------------------------------------------------------------------
-- 3. RPC: should_send_vapi_health_alert(alert_type, window_min)
-- ----------------------------------------------------------------------------
-- Returns (out_should_send, out_hit_count, out_first_seen_at, out_suppressed_since).
-- - First time alert_type seen: insert, return TRUE, suppressed_since = NOW().
-- - Already exists, last suppressed_since older than window: UPDATE suppressed_since, return TRUE.
-- - Already exists, within suppression window: increment hit_count, return FALSE.
--
-- SECURITY DEFINER + search_path lock (Supabase advisor compliance).
CREATE OR REPLACE FUNCTION public.should_send_vapi_health_alert(
  p_alert_type  TEXT,
  p_window_min  INT  DEFAULT 60
) RETURNS TABLE (
  out_should_send      BOOLEAN,
  out_hit_count        INT,
  out_first_seen_at    TIMESTAMPTZ,
  out_suppressed_since TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_row    public.vapi_health_alert_log%ROWTYPE;
  v_window INTERVAL := make_interval(mins => GREATEST(p_window_min, 1));
BEGIN
  INSERT INTO public.vapi_health_alert_log (alert_type, suppressed_since)
  VALUES (p_alert_type, NOW())
  ON CONFLICT (alert_type) DO UPDATE
    SET last_seen_at = NOW(),
        hit_count    = public.vapi_health_alert_log.hit_count + 1
  RETURNING * INTO v_row;

  -- Brand new row (hit_count=1 AND just inserted) — fire
  IF v_row.hit_count = 1 THEN
    RETURN QUERY SELECT TRUE, v_row.hit_count, v_row.first_seen_at, v_row.suppressed_since;
    RETURN;
  END IF;

  -- Existing row: fire only if outside suppression window
  IF v_row.suppressed_since IS NULL
     OR NOW() - v_row.suppressed_since > v_window THEN
    UPDATE public.vapi_health_alert_log
       SET suppressed_since = NOW()
     WHERE alert_type = p_alert_type
    RETURNING * INTO v_row;
    RETURN QUERY SELECT TRUE, v_row.hit_count, v_row.first_seen_at, v_row.suppressed_since;
  ELSE
    RETURN QUERY SELECT FALSE, v_row.hit_count, v_row.first_seen_at, v_row.suppressed_since;
  END IF;
END;
$$;

COMMENT ON FUNCTION public.should_send_vapi_health_alert(TEXT, INT) IS
  'Dedup gate for VAPI_HEALTH_GUARDIAN. Returns out_should_send=TRUE only when alert_type has not fired within window_min minutes.';

-- ----------------------------------------------------------------------------
-- 4. EXECUTE grants — PUBLIC/anon/authenticated revoke; service_role only
-- ----------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.should_send_vapi_health_alert(TEXT, INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.should_send_vapi_health_alert(TEXT, INT) FROM anon;
REVOKE ALL ON FUNCTION public.should_send_vapi_health_alert(TEXT, INT) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.should_send_vapi_health_alert(TEXT, INT) TO service_role;

COMMIT;

-- ============================================================================
-- POST-DEPLOY VERIFY (run separately, do NOT include in TX)
-- ============================================================================
-- A) RPC body fingerprint assert (feedback_supabase_function_replace_verify):
--    SELECT md5(prosrc) FROM pg_proc
--      WHERE proname='should_send_vapi_health_alert';
--    Expected non-empty hash; pgrcd test below also verifies it returns rows.
--
-- B) RLS deny test (anon should NOT be able to SELECT):
--    Use anon key:
--      curl -X GET "$SUPABASE_URL/rest/v1/vapi_health_alert_log?select=*" \
--           -H "apikey: $ANON_KEY" -H "Authorization: Bearer $ANON_KEY"
--    Expected: [] (RLS denies) — NOT 200 with rows.
--
-- C) RPC happy-path service_role:
--    curl -X POST "$SUPABASE_URL/rest/v1/rpc/should_send_vapi_health_alert" \
--         -H "apikey: $SERVICE_ROLE" -H "Authorization: Bearer $SERVICE_ROLE" \
--         -H "Content-Type: application/json" \
--         --data '{"p_alert_type":"verify_test","p_window_min":1}'
--    Expected first call: out_should_send=true, out_hit_count=1.
--    Expected immediate second call: out_should_send=false, out_hit_count=2.
--
-- D) RPC anon DENY test:
--    Same POST with anon key — expected 403/permission denied (not 200).
--
-- E) Cleanup verify row:
--    DELETE FROM public.vapi_health_alert_log WHERE alert_type = 'verify_test';
--
-- ============================================================================
-- ROLLBACK (manual, only if needed)
-- ============================================================================
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.should_send_vapi_health_alert(TEXT, INT);
-- DROP TABLE    IF EXISTS public.vapi_health_alert_log CASCADE;
-- COMMIT;
