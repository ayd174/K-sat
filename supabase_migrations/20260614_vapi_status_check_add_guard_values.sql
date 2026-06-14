-- Migration: extend vapi_prompt_history.status CHECK to cover guard terminal values
-- Context: the self-healing optimizer pipeline writes status='no_op' (WIPE-GUARD:
--   prompt unchanged) and status='hallucinated' (LLM invented a non-existent change).
--   These were added to the live pipeline 2026-06-08 but the original CHECK constraint
--   only allowed pending/approved/deployed/rejected/failed -> inserts violated the
--   constraint. It was patched live via ALTER (per project memory 2026-05-29 status fix),
--   but no SQL file captured the ALTER, so re-running supabase_schema.sql would recreate
--   the old constraint and re-break the pipeline. This migration is the durable record.
-- Idempotent: safe to re-run.

ALTER TABLE public.vapi_prompt_history
  DROP CONSTRAINT IF EXISTS vapi_prompt_history_status_check;

ALTER TABLE public.vapi_prompt_history
  ADD  CONSTRAINT vapi_prompt_history_status_check
  CHECK (status IN ('pending','approved','deployed','rejected','failed','no_op','hallucinated'));

COMMENT ON COLUMN public.vapi_prompt_history.status IS
  'pending → approved → deployed | rejected | failed | no_op (guard: prompt unchanged) | hallucinated (guard: LLM invented change).';
