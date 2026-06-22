-- LLM Presets table to store multiple named LLM configurations

CREATE TABLE IF NOT EXISTS llm_presets (
    id                  BIGSERIAL PRIMARY KEY,
    name                VARCHAR(128) NOT NULL UNIQUE,
    description         VARCHAR(256),
    mode                VARCHAR(32) NOT NULL,
    frontier_provider   VARCHAR(32),
    model_id            VARCHAR(128) NOT NULL,
    openai_api_base     VARCHAR(512),
    slm_runtime         VARCHAR(32),
    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    api_key_configured  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT chk_llm_presets_name CHECK (name ~ '^[A-Z][A-Z0-9_]*$'),
    CONSTRAINT chk_llm_presets_mode CHECK (mode IN ('frontier', 'openai_compatible')),
    CONSTRAINT chk_llm_presets_frontier_provider CHECK (frontier_provider IN ('openai', 'anthropic', 'google')),
    CONSTRAINT chk_llm_presets_slm_runtime CHECK (slm_runtime IN ('vllm', 'sglang'))
);

-- Ensure only one preset can be set as default
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_presets_default 
    ON llm_presets (is_default) 
    WHERE (is_default = TRUE);

-- Data Migration: Migrate legacy global LLM settings to DEFAULT_PRESET
DO $$
DECLARE
    v_env JSONB;
    v_model_spec VARCHAR(128);
    v_mode VARCHAR(32);
    v_provider VARCHAR(32);
    v_model_id VARCHAR(128);
    v_api_base VARCHAR(512);
    v_runtime VARCHAR(32);
    v_idx INT;
    v_api_key_configured BOOLEAN := FALSE;
    v_secret_keys JSONB;
BEGIN
    -- Check if global infra_meta exists and has LLM model
    SELECT env, secret_keys INTO v_env, v_secret_keys
    FROM infra_meta
    WHERE scope = 'global' AND scope_key = ''
    LIMIT 1;

    IF v_env IS NOT NULL AND v_env ? 'DEFAULT_LLM_MODEL' AND (v_env->>'DEFAULT_LLM_MODEL') <> '' THEN
        v_model_spec := v_env->>'DEFAULT_LLM_MODEL';
        v_api_base := v_env->>'OPENAI_API_BASE';
        v_runtime := v_env->>'LLM_RUNTIME';

        -- Parse model_spec e.g., "openai:gpt-4o-mini"
        v_idx := position(':' in v_model_spec);
        IF v_idx > 0 THEN
            v_provider := substring(v_model_spec from 1 for v_idx - 1);
            v_model_id := substring(v_model_spec from v_idx + 1);
        ELSE
            v_provider := 'openai';
            v_model_id := v_model_spec;
        END IF;

        -- Determine mode
        IF v_api_base IS NOT NULL AND v_api_base <> '' THEN
            v_mode := 'openai_compatible';
            v_provider := 'openai';
        ELSE
            v_mode := 'frontier';
        END IF;

        -- Check configured secrets
        IF v_secret_keys ? 'OPENAI_API_KEY' OR v_secret_keys ? 'ANTHROPIC_API_KEY' OR v_secret_keys ? 'GOOGLE_API_KEY' THEN
            v_api_key_configured := TRUE;
        END IF;

        -- Create default preset
        INSERT INTO llm_presets (
            name, description, mode, frontier_provider, model_id, openai_api_base, slm_runtime, is_default, api_key_configured
        ) VALUES (
            'DEFAULT_PRESET',
            'Migrated platform default preset',
            v_mode,
            v_provider,
            v_model_id,
            v_api_base,
            v_runtime,
            TRUE,
            v_api_key_configured
        ) ON CONFLICT (name) DO NOTHING;

        -- Cleanup legacy env keys from global infra_meta
        UPDATE infra_meta
        SET env = env - 'DEFAULT_LLM_MODEL' - 'OPENAI_API_BASE' - 'LLM_RUNTIME'
        WHERE scope = 'global' AND scope_key = '';
    END IF;
END $$;
