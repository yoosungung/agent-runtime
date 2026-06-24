from backend.pipeline_oauth import sign_oauth_state, verify_oauth_state
from backend.settings import Settings


def test_oauth_state_roundtrip():
    settings = Settings(POSTGRES_DSN="sqlite://test", PIPELINE_OAUTH_STATE_KEY="test-key")
    state = sign_oauth_state(
        {"tenant": "dev", "credential_id": "abc", "driver": "gdrive", "ts": 1_700_000_000},
        settings,
    )
    payload = verify_oauth_state(state, settings, max_age_sec=999_999_999)
    assert payload["tenant"] == "dev"
    assert payload["credential_id"] == "abc"
