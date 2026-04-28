"""Integration tests for auth admin endpoints and refresh/logout.

Uses SQLite in-memory so no real Postgres is needed.  Auth models only use
standard SQLAlchemy column types (no JSONB), so no patching is required.

Note: POST /v1/admin/users, DELETE /v1/admin/users/{id}, POST /v1/admin/access,
DELETE /v1/admin/access have been removed from auth (write ownership moved to
admin backend). Tests for those routes are removed accordingly.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import runtime_common.db.models as _models

# Patch JSONB → JSON so SQLite can create the shared Base tables that include
# SourceMetaRow / UserMetaRow (which use JSONB for config).  Auth-specific
# tables don't use JSONB, but they share the same Base.metadata.
for _tbl in _models.Base.metadata.tables.values():
    for _col in _tbl.columns:
        if isinstance(_col.type, JSONB):
            _col.type = JSON()

from auth.app import _AccessCache, _RateLimiter, app  # noqa: E402
from auth.settings import Settings  # noqa: E402
from runtime_common.db.models import Base, RefreshTokenRow, UserRow  # noqa: E402

_TEST_DSN = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def db_client():
    """Fixture: SQLite in-memory DB + ASGI client, bypassing lifespan."""
    engine = create_async_engine(
        _TEST_DSN,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

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

    settings = Settings(
        jwt_private_key=priv_pem,
        jwt_public_key=pub_pem,
        jwt_issuer="test",
        postgres_dsn=_TEST_DSN,
        access_cache_ttl_sec=60.0,
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.access_cache = _AccessCache(ttl_sec=60.0)
    app.state.username_limiter = _RateLimiter(max_attempts=50, window_sec=300.0)
    app.state.ip_limiter = _RateLimiter(max_attempts=200, window_sec=300.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory

    await engine.dispose()


async def _create_user_db(session_factory, username: str = "alice", password: str = "pass") -> int:
    """Insert a user directly into the DB; returns user id."""
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    async with session_factory() as session:
        row = UserRow(username=username, password_hash=ph.hash(password), tenant="acme")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


# ---------------------------------------------------------------------------
# Admin — user management (read-only)
# ---------------------------------------------------------------------------


class TestAdminUsers:
    async def test_list_users_returns_users(self, db_client):
        client, session_factory = db_client
        await _create_user_db(session_factory, "u1", "pw")
        await _create_user_db(session_factory, "u2", "pw")
        resp = await client.get("/v1/admin/users")
        assert resp.status_code == 200
        names = {u["username"] for u in resp.json()}
        assert "u1" in names
        assert "u2" in names


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------


class TestRefreshToken:
    async def _login(
        self, client, session_factory, username="rfuser", password="pw"
    ) -> tuple[str, str]:
        """Create user via DB helper, then login to get tokens."""
        await _create_user_db(session_factory, username, password)
        resp = await client.post("/login", json={"username": username, "password": password})
        assert resp.status_code == 200
        body = resp.json()
        return body["access_token"], body["refresh_token"]

    async def test_refresh_returns_new_tokens(self, db_client):
        client, session_factory = db_client
        _, refresh = await self._login(client, session_factory, "rf1", "pw")
        resp = await client.post("/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["refresh_token"] != refresh  # rotated

    async def test_refresh_rotates_token(self, db_client):
        """Old refresh token is revoked after rotation."""
        client, session_factory = db_client
        _, refresh = await self._login(client, session_factory, "rf2", "pw")
        await client.post("/refresh", json={"refresh_token": refresh})
        # Using old token should fail
        resp = await client.post("/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 401

    async def test_refresh_invalid_token_returns_401(self, db_client):
        client, _ = db_client
        resp = await client.post("/refresh", json={"refresh_token": "notavalidtoken"})
        assert resp.status_code == 401

    async def test_refresh_expired_token_returns_401(self, db_client):
        """Insert an already-expired refresh token and verify 401."""
        client, session_factory = db_client
        uid = await _create_user_db(session_factory, "rf3", "pw")
        plain = secrets.token_hex(32)
        token_hash = hashlib.sha256(plain.encode()).hexdigest()
        async with session_factory() as session:
            session.add(
                RefreshTokenRow(
                    user_id=uid,
                    token_hash=token_hash,
                    expires_at=datetime.now(tz=UTC) - timedelta(days=1),
                )
            )
            await session.commit()
        resp = await client.post("/refresh", json={"refresh_token": plain})
        assert resp.status_code == 401

    async def test_refresh_revoked_token_returns_401(self, db_client):
        """Insert a revoked refresh token and verify 401."""
        client, session_factory = db_client
        uid = await _create_user_db(session_factory, "rf4", "pw")
        plain = secrets.token_hex(32)
        token_hash = hashlib.sha256(plain.encode()).hexdigest()
        async with session_factory() as session:
            session.add(
                RefreshTokenRow(
                    user_id=uid,
                    token_hash=token_hash,
                    expires_at=datetime.now(tz=UTC) + timedelta(days=30),
                    revoked_at=datetime.now(tz=UTC),
                )
            )
            await session.commit()
        resp = await client.post("/refresh", json={"refresh_token": plain})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    async def test_logout_without_token_returns_ok(self, db_client):
        client, _ = db_client
        resp = await client.post("/logout", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_logout_revokes_refresh_token(self, db_client):
        client, session_factory = db_client
        uid = await _create_user_db(session_factory, "lo1", "pw")
        plain = secrets.token_hex(32)
        token_hash = hashlib.sha256(plain.encode()).hexdigest()
        async with session_factory() as session:
            session.add(
                RefreshTokenRow(
                    user_id=uid,
                    token_hash=token_hash,
                    expires_at=datetime.now(tz=UTC) + timedelta(days=30),
                )
            )
            await session.commit()

        resp = await client.post("/logout", json={"refresh_token": plain})
        assert resp.status_code == 200

        # Token should now be revoked — refresh fails
        resp2 = await client.post("/refresh", json={"refresh_token": plain})
        assert resp2.status_code == 401
