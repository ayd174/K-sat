-- ─────────────────────────────────────────────────────────────────────
-- 2026-05-27  conversation_state: per-JID slot persistence backbone
-- ─────────────────────────────────────────────────────────────────────
-- Purpose: solve prompt-only slot CARRY-FORWARD insufficiency proven by
-- the 2026-05-26 Alicia Diaz case (project_ayka_alicia_diaz_2026_05_27_uat_failed
-- + project_ayka_simple_memory_volatile_2026_05_25, 4th validation).
--
-- Reads: n8n WhatsApp workflow Akıllı agent — pre-Akıllı "Load State"
-- node SELECTs by jid and injects `[ÖNCEKİ SLOT DURUMU]` into agent
-- text template; post-Akıllı "Save State" node UPSERTs the new slots.
--
-- Idempotent: re-running this script is a no-op (IF NOT EXISTS,
-- CREATE OR REPLACE).
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.conversation_state (
    whatsapp_jid    text         PRIMARY KEY,
    customer_id     uuid         REFERENCES public.customers(id) ON DELETE SET NULL,
    company_id      uuid         REFERENCES public.companies(id) ON DELETE CASCADE,
    slots           jsonb        NOT NULL DEFAULT '{}'::jsonb,
    language_lock   text,
    last_exec_id    bigint,
    turn_count      integer      NOT NULL DEFAULT 0,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  public.conversation_state IS
  'Per-JID slot snapshot. Pre/Post-Akıllı bridge for slot carry-forward across executions.';
COMMENT ON COLUMN public.conversation_state.whatsapp_jid IS
  'Evolution session key, e.g. 32499157786@s.whatsapp.net.';
COMMENT ON COLUMN public.conversation_state.slots IS
  'Latest Akıllı `internal_analysis.slot_extraction_pass` snapshot + flat slot values.';
COMMENT ON COLUMN public.conversation_state.language_lock IS
  'Cached language_lock for fast persistent-mode resolution (french|turkish|dutch|english).';
COMMENT ON COLUMN public.conversation_state.last_exec_id IS
  'Last n8n executionId that wrote this row (debug audit trail).';
COMMENT ON COLUMN public.conversation_state.turn_count IS
  'Auto-incremented by trigger when slots JSONB changes.';

-- Indexes
CREATE INDEX IF NOT EXISTS conversation_state_updated_at_idx
    ON public.conversation_state (updated_at DESC);
CREATE INDEX IF NOT EXISTS conversation_state_customer_id_idx
    ON public.conversation_state (customer_id)
    WHERE customer_id IS NOT NULL;

-- updated_at + turn_count auto-update trigger
CREATE OR REPLACE FUNCTION public.tg_conversation_state_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    IF NEW.slots IS DISTINCT FROM OLD.slots THEN
        NEW.turn_count := COALESCE(OLD.turn_count, 0) + 1;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.tg_conversation_state_set_updated_at() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.tg_conversation_state_set_updated_at() FROM anon, authenticated;

DROP TRIGGER IF EXISTS conversation_state_set_updated_at ON public.conversation_state;
CREATE TRIGGER conversation_state_set_updated_at
    BEFORE UPDATE ON public.conversation_state
    FOR EACH ROW
    EXECUTE FUNCTION public.tg_conversation_state_set_updated_at();

-- RLS
ALTER TABLE public.conversation_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "conversation_state_service_role_all"
    ON public.conversation_state;
CREATE POLICY "conversation_state_service_role_all"
    ON public.conversation_state
    AS PERMISSIVE
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Hard revokes — anon, authenticated, PUBLIC all blocked
-- (n8n uses inline service_role JWT pattern; no anon access path.)
REVOKE ALL ON public.conversation_state FROM PUBLIC;
REVOKE ALL ON public.conversation_state FROM anon;
REVOKE ALL ON public.conversation_state FROM authenticated;
GRANT  ALL ON public.conversation_state TO service_role;
