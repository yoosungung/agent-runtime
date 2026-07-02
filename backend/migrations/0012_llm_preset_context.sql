-- LLM preset context window limits (model/runtime capacity)

ALTER TABLE llm_presets
    ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS max_output_tokens INTEGER;

-- Backfill existing presets before NOT NULL constraint
UPDATE llm_presets
SET context_window_tokens = CASE
    WHEN mode = 'openai_compatible' AND slm_runtime = 'sglang' THEN 16384
    ELSE 131072
END
WHERE context_window_tokens IS NULL;

ALTER TABLE llm_presets
    ALTER COLUMN context_window_tokens SET NOT NULL;

ALTER TABLE llm_presets
    ADD CONSTRAINT chk_llm_presets_context_window_tokens
        CHECK (context_window_tokens > 0);

ALTER TABLE llm_presets
    ADD CONSTRAINT chk_llm_presets_max_output_tokens
        CHECK (max_output_tokens IS NULL OR max_output_tokens > 0);
