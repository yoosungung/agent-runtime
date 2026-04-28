"""HTTP endpoint tests for the auth service.

Covers /login, /verify, /readyz without a real database.
The DB session is fully mocked so no Postgres or Redis is required.

The TestRefreshToken / TestLogoutRevoke classes use a real SQLite in-memory DB
via the same patching approach as deploy-api tests.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
import pytest_asyncio
from argon2 import PasswordHasher
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import runtime_common.db.models as _models

# Patch JSONB → JSON so SQLite can create shared Base tables that include
# SourceMetaRow / UserMetaRow (which use JSONB for config).
for _tbl in _models.Base.metadata.tables.values():
    for _col in _tbl.columns:
        if isinstance(_col.type, JSONB):
            _col.type = JSON()

import auth.app as auth_module  # noqa: E402
from auth.app import _AccessCache, _RateLimiter, app  # noqa: E402
from auth.settings import Settings  # noqa: E402
from runtime_common.db.models import Base, UserRow  # noqa: E402
from runtime_common.schemas import ResourceRef  # noqa: E402

_ph = PasswordHasher()

# ---------------------------------------------------------------------------
# RSA keypair fixture (generated once per test module run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        private.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return priv_pem, pub_pem


# ---------------------------------------------------------------------------
# User fixture
# ---------------------------------------------------------------------------

CORRECT_PASSWORD = "s3cr3t!"


@pytest.fixture
def alice_user() -> MagicMock:
    """Lightweight stand-in for UserRow — avoids SQLAlchemy instrumentation issues."""
    u = MagicMock(
        spec=[
            "id",
            "username",
            "password_hash",
            "tenant",
            "disabled",
            "is_admin",
            "must_change_password",
        ]
    )
    u.id = 1
    u.username = "alice"
    u.password_hash = _ph.hash(CORRECT_PASSWORD)
    u.tenant = "acme"
    u.disabled = False
    u.is_admin = False
    u.must_change_password = False
    return u


@pytest.fixture
def alice_disabled(alice_user: MagicMock) -> MagicMock:
    alice_user.disabled = True
    return alice_user


# ---------------------------------------------------------------------------
# Helpers — inject settings + mocked session_factory into app.state
# ---------------------------------------------------------------------------


def _make_settings(priv_pem: str, pub_pem: str) -> Settings:
    """Build a minimal Settings object without reading env vars."""
    return Settings(
        jwt_private_key=priv_pem,
        jwt_public_key=pub_pem,
        jwt_issuer="test-issuer",
        postgres_dsn="postgresql+asyncpg://x:x@localhost/x",  # never contacted
        access_cache_ttl_sec=60.0,
    )


def _make_session_factory_mock(user: MagicMock | None) -> MagicMock:
    """Return a mock session_factory whose sessions return `user` on scalar_one_or_none."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session
    return mock_factory


def _inject_state(priv_pem: str, pub_pem: str, user: MagicMock | None) -> None:
    """Inject test-doubles directly into app.state, bypassing lifespan."""
    settings = _make_settings(priv_pem, pub_pem)
    app.state.settings = settings
    app.state.engine = MagicMock()
    app.state.session_factory = _make_session_factory_mock(user)
    app.state.access_cache = _AccessCache(ttl_sec=60.0)
    app.state.username_limiter = _RateLimiter(max_attempts=5, window_sec=300.0)
    app.state.ip_limiter = _RateLimiter(max_attempts=20, window_sec=300.0)


def _make_token(priv_pem: str, claims: dict) -> str:
    return jwt.encode(claims, priv_pem, algorithm="RS256")


# ---------------------------------------------------------------------------
# Helper: patch _fetch_access to return a fixed access list
# ---------------------------------------------------------------------------


def _patch_fetch_access(monkeypatch, access: list[ResourceRef]) -> None:
    async def _fake_fetch(_user_id: int) -> list[ResourceRef]:
        return access

    monkeypatch.setattr(auth_module, "_fetch_access", _fake_fetch)


# ---------------------------------------------------------------------------
# /login tests
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.fixture(autouse=True)
    def _setup(self, rsa_keypair, alice_user):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, alice_user)

    async def test_login_success_returns_access_token(self, rsa_keypair):
        priv, pub = rsa_keypair
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/login", json={"username": "alice", "password": CORRECT_PASSWORD}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        # Token must be verifiable with the public key
        claims = jwt.decode(
            body["access_token"],
            pub,
            algorithms=["RS256"],
            issuer="test-issuer",
            options={"require": ["exp", "iat", "sub"]},
        )
        assert claims["sub"] == "alice"
        assert claims["user_id"] == 1

    async def test_login_wrong_password_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/login", json={"username": "alice", "password": "wrongpassword"}
            )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    async def test_login_user_not_found_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)  # no user in DB
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/login", json={"username": "ghost", "password": "whatever"})
        assert resp.status_code == 401
        # Same message as wrong password — enumeration protection
        assert "invalid" in resp.json()["detail"].lower()

    async def test_login_disabled_user_returns_401(self, rsa_keypair, alice_disabled):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, alice_disabled)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/login", json={"username": "alice", "password": CORRECT_PASSWORD}
            )
        assert resp.status_code == 401

    async def test_login_rate_limit_hit_returns_429(self, rsa_keypair, alice_user):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, alice_user)
        # Exhaust the username limiter manually
        limiter: _RateLimiter = app.state.username_limiter
        for _ in range(5):
            limiter.record_failure("alice")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/login", json={"username": "alice", "password": CORRECT_PASSWORD}
            )
        assert resp.status_code == 429
        assert "too many" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /verify tests
# ---------------------------------------------------------------------------


class TestVerify:
    @pytest.fixture(autouse=True)
    def _setup(self, rsa_keypair, monkeypatch):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)  # session_factory not used by verify directly
        _patch_fetch_access(monkeypatch, [ResourceRef(kind="agent", name="chat-bot")])

    def _valid_claims(self, issuer: str = "test-issuer", offset: int = 3600) -> dict:
        now = int(time.time())
        return {
            "sub": "alice",
            "user_id": 1,
            "tenant": "acme",
            "iss": issuer,
            "iat": now,
            "exp": now + offset,
        }

    async def test_verify_valid_token_returns_principal(self, rsa_keypair):
        priv, pub = rsa_keypair
        token = _make_token(priv, self._valid_claims())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["sub"] == "alice"
        assert body["user_id"] == 1
        assert body["grace_applied"] is False
        assert any(r["name"] == "chat-bot" for r in body["access"])

    async def test_verify_expired_no_grace_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Token expired 10 seconds ago
        claims = self._valid_claims(offset=-10)
        token = _make_token(priv, claims)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_verify_expired_within_grace_returns_200(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Token expired 5 seconds ago, grace is 30 seconds
        claims = self._valid_claims(offset=-5)
        token = _make_token(priv, claims)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 30})
        assert resp.status_code == 200
        body = resp.json()
        assert body["grace_applied"] is True

    async def test_verify_grace_clamped_to_grace_max_sec(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Token expired 700 seconds ago — beyond GRACE_MAX_SEC (600)
        claims = self._valid_claims(offset=-700)
        token = _make_token(priv, claims)
        # grace_sec=9999 is clamped to 600 by settings.grace_max_sec
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 9999})
        # 700 > 600 (grace_max) so it should still be rejected
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_verify_grace_clamped_allows_within_max(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Token expired 500 seconds ago — within GRACE_MAX_SEC (600) even after clamping
        claims = self._valid_claims(offset=-500)
        token = _make_token(priv, claims)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 9999})
        assert resp.status_code == 200
        assert resp.json()["grace_applied"] is True

    async def test_verify_invalid_signature_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Generate a second keypair — token signed with different private key
        other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_priv_pem = other_private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        token = _make_token(other_priv_pem, self._valid_claims())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 401

    async def test_verify_missing_required_claims_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Build a token without the required "sub" claim
        now = int(time.time())
        claims = {
            "user_id": 1,
            "iss": "test-issuer",
            "iat": now,
            "exp": now + 3600,
            # "sub" intentionally missing
        }
        token = jwt.encode(claims, priv, algorithm="RS256")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /readyz test
# ---------------------------------------------------------------------------


class TestReadyz:
    async def test_readyz_returns_200_when_configured(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 200

    async def test_readyz_returns_503_when_no_public_key(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)
        app.state.settings.jwt_public_key = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/readyz")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /.well-known/jwks.json tests
# ---------------------------------------------------------------------------


class TestJwks:
    async def test_jwks_returns_rsa_key_fields(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/.well-known/jwks.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "keys" in body
        assert len(body["keys"]) == 1
        key = body["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert "n" in key and "e" in key and "kid" in key

    async def test_jwks_returns_503_when_no_public_key(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)
        app.state.settings.jwt_public_key = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/.well-known/jwks.json")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /v1/api-keys and API key /verify tests
# ---------------------------------------------------------------------------


class TestApiKeys:
    def _make_api_key_row(self, key_hash: str, name: str = "ci-bot", disabled: bool = False):
        row = MagicMock()
        row.key_hash = key_hash
        row.name = name
        row.tenant = "acme"
        row.disabled = disabled
        row.expires_at = None
        return row

    def _inject_state_with_api_row(self, priv: str, pub: str, api_row) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = api_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.return_value = mock_session
        settings = _make_settings(priv, pub)
        app.state.settings = settings
        app.state.engine = MagicMock()
        app.state.session_factory = mock_factory
        app.state.access_cache = _AccessCache(ttl_sec=60.0)
        app.state.username_limiter = _RateLimiter(max_attempts=5, window_sec=300.0)
        app.state.ip_limiter = _RateLimiter(max_attempts=20, window_sec=300.0)

    async def test_create_api_key_returns_ak_prefixed_key(self, rsa_keypair):
        priv, pub = rsa_keypair
        # Mock session where flush() sets row.id
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        async def fake_flush():
            # Simulate DB auto-increment assigning an id
            mock_session._added_row.id = 42

        mock_session.flush = fake_flush

        def capture_add(row):
            mock_session._added_row = row
            row.id = 42  # set id immediately so flush can use it

        mock_session.add = capture_add
        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        settings = _make_settings(priv, pub)
        app.state.settings = settings
        app.state.engine = MagicMock()
        app.state.session_factory = mock_factory
        app.state.access_cache = _AccessCache(ttl_sec=60.0)
        app.state.username_limiter = _RateLimiter(max_attempts=5, window_sec=300.0)
        app.state.ip_limiter = _RateLimiter(max_attempts=20, window_sec=300.0)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/api-keys", json={"name": "ci-bot", "tenant": "acme"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["key"].startswith("ak_")
        assert body["name"] == "ci-bot"

    async def test_verify_with_api_key_returns_principal(self, rsa_keypair):
        from argon2 import PasswordHasher as _PasswordHasher

        priv, pub = rsa_keypair
        ph = _PasswordHasher()
        secret = "a" * 64
        key_hash = ph.hash(secret)
        token = f"ak_7_{secret}"
        api_row = self._make_api_key_row(key_hash, name="ci-bot")
        self._inject_state_with_api_row(priv, pub, api_row)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["sub"] == "apikey:ci-bot"

    async def test_verify_with_disabled_api_key_returns_401(self, rsa_keypair):
        from argon2 import PasswordHasher as _PasswordHasher

        priv, pub = rsa_keypair
        ph = _PasswordHasher()
        secret = "b" * 64
        key_hash = ph.hash(secret)
        token = f"ak_8_{secret}"
        api_row = self._make_api_key_row(key_hash, name="old-bot", disabled=True)
        self._inject_state_with_api_row(priv, pub, api_row)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/verify", json={"token": token, "grace_sec": 0})
        assert resp.status_code == 401
        assert "disabled" in resp.json()["detail"]

    async def test_verify_with_invalid_api_key_format_returns_401(self, rsa_keypair):
        priv, pub = rsa_keypair
        _inject_state(priv, pub, None)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/verify", json={"token": "ak_notanumber_secret", "grace_sec": 0}
            )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /refresh + /logout (refresh-token revocation) — SQLite integration tests
# ---------------------------------------------------------------------------

TEST_DSN = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def db_client(rsa_keypair):
    """Full SQLite-backed client for testing refresh token flows."""
    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    priv, pub = rsa_keypair
    settings = Settings(
        jwt_private_key=priv,
        jwt_public_key=pub,
        jwt_issuer="test-issuer",
        postgres_dsn="sqlite+aiosqlite:///:memory:",  # dummy — engine already created
        access_cache_ttl_sec=60.0,
        refresh_token_ttl_days=30,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.access_cache = _AccessCache(ttl_sec=60.0)
    app.state.username_limiter = _RateLimiter(max_attempts=5, window_sec=300.0)
    app.state.ip_limiter = _RateLimiter(max_attempts=20, window_sec=300.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory

    await engine.dispose()


async def _create_user_in_db(session_factory, username: str, password: str) -> None:
    ph = PasswordHasher()
    async with session_factory() as session:
        session.add(UserRow(username=username, password_hash=ph.hash(password), tenant="test"))
        await session.commit()


class TestRefreshToken:
    async def test_login_returns_refresh_token(self, db_client):
        client, sf = db_client
        await _create_user_in_db(sf, "bob", "pass1234!")
        resp = await client.post("/login", json={"username": "bob", "password": "pass1234!"})
        assert resp.status_code == 200
        body = resp.json()
        assert "refresh_token" in body
        assert len(body["refresh_token"]) == 64  # 32 bytes hex
        assert body["refresh_token_expires_in"] == 30 * 86400

    async def test_refresh_issues_new_tokens(self, db_client):
        client, sf = db_client
        await _create_user_in_db(sf, "carol", "pass1234!")
        login = await client.post("/login", json={"username": "carol", "password": "pass1234!"})
        old_rt = login.json()["refresh_token"]

        resp = await client.post("/refresh", json={"refresh_token": old_rt})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["refresh_token"] != old_rt  # rotated

    async def test_refresh_revokes_old_token(self, db_client):
        client, sf = db_client
        await _create_user_in_db(sf, "dave", "pass1234!")
        login = await client.post("/login", json={"username": "dave", "password": "pass1234!"})
        old_rt = login.json()["refresh_token"]

        await client.post("/refresh", json={"refresh_token": old_rt})

        # Old token must now be rejected
        resp2 = await client.post("/refresh", json={"refresh_token": old_rt})
        assert resp2.status_code == 401

    async def test_refresh_with_invalid_token_returns_401(self, db_client):
        client, _ = db_client
        resp = await client.post("/refresh", json={"refresh_token": "a" * 64})
        assert resp.status_code == 401


class TestLogoutRevoke:
    async def test_logout_without_body_returns_ok(self, db_client):
        client, _ = db_client
        resp = await client.post("/logout")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_logout_revokes_refresh_token(self, db_client):
        client, sf = db_client
        await _create_user_in_db(sf, "eve", "pass1234!")
        login = await client.post("/login", json={"username": "eve", "password": "pass1234!"})
        rt = login.json()["refresh_token"]

        logout_resp = await client.post("/logout", json={"refresh_token": rt})
        assert logout_resp.status_code == 200

        # Token must now be rejected
        resp = await client.post("/refresh", json={"refresh_token": rt})
        assert resp.status_code == 401
