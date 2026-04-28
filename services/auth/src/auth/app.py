from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from threading import Lock

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from auth.admin import router as admin_router
from auth.settings import Settings
from runtime_common.db import make_engine, make_session_factory, session_scope
from runtime_common.db.models import ApiKeyRow, RefreshTokenRow, UserResourceAccessRow, UserRow
from runtime_common.logging import configure_logging
from runtime_common.schemas import Principal, ResourceRef

logger = logging.getLogger(__name__)

_ph = PasswordHasher()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    refresh_token_expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class VerifyRequest(BaseModel):
    token: str
    grace_sec: int = 0


# ---------------------------------------------------------------------------
# Simple in-memory LRU+TTL cache for user_id → access list
# ---------------------------------------------------------------------------


class _AccessCache:
    def __init__(self, ttl_sec: float, max_size: int = 1024) -> None:
        self._ttl = ttl_sec
        self._max = max_size
        self._data: OrderedDict[int, tuple[list[ResourceRef], float]] = OrderedDict()
        self._lock = Lock()

    def get(self, user_id: int) -> list[ResourceRef] | None:
        with self._lock:
            entry = self._data.get(user_id)
            if entry is None:
                return None
            access, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[user_id]
                return None
            self._data.move_to_end(user_id)
            return access

    def set(self, user_id: int, access: list[ResourceRef]) -> None:
        with self._lock:
            self._data[user_id] = (access, time.monotonic())
            self._data.move_to_end(user_id)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def invalidate(self, user_id: int) -> None:
        """Drop the cached entry so the next /verify re-reads from DB.

        Distinct from `set(user_id, [])`, which pre-fills with empty access
        for revoke-token semantics (deny everything during the TTL window).
        For grant/revoke flows we want fresh DB state, not pre-filled empty.
        """
        with self._lock:
            self._data.pop(user_id, None)


# ---------------------------------------------------------------------------
# Sliding-window rate limiter for login brute-force defense
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Sliding-window rate limiter for login attempts."""

    def __init__(self, max_attempts: int, window_sec: float) -> None:
        self._max = max_attempts
        self._window = window_sec
        self._data: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _evict_old(self, dq: deque[float], now: float) -> None:
        cutoff = now - self._window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            dq = self._data.get(key)
            if dq is None:
                return False
            self._evict_old(dq, time.monotonic())
            return len(dq) >= self._max

    def record_failure(self, key: str) -> None:
        with self._lock:
            if key not in self._data:
                self._data[key] = deque()
            dq = self._data[key]
            now = time.monotonic()
            self._evict_old(dq, now)
            dq.append(now)

    def record_success(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    engine = make_engine(settings.postgres_dsn)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.access_cache = _AccessCache(ttl_sec=settings.access_cache_ttl_sec)
    app.state.username_limiter = _RateLimiter(max_attempts=5, window_sec=300.0)
    app.state.ip_limiter = _RateLimiter(max_attempts=20, window_sec=300.0)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="auth", lifespan=lifespan)
app.include_router(admin_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    settings: Settings = app.state.settings
    if not settings.jwt_public_key:
        raise HTTPException(status_code=503, detail="jwt_public_key not configured")
    return {"status": "ok"}


@app.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    settings: Settings = app.state.settings
    if not settings.jwt_private_key:
        raise HTTPException(status_code=500, detail="jwt_private_key not configured")

    client_ip: str = request.client.host if request.client else "unknown"
    username_limiter: _RateLimiter = app.state.username_limiter
    ip_limiter: _RateLimiter = app.state.ip_limiter

    if username_limiter.is_blocked(req.username) or ip_limiter.is_blocked(client_ip):
        raise HTTPException(status_code=429, detail="too many login attempts")

    _invalid_msg = "invalid username or password"

    async with session_scope(app.state.session_factory) as session:
        stmt = select(UserRow).where(UserRow.username == req.username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if user is None or user.disabled:
        username_limiter.record_failure(req.username)
        ip_limiter.record_failure(client_ip)
        logger.warning(
            "login_failure",
            extra={"username": req.username, "ip": client_ip, "reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail=_invalid_msg)

    try:
        _ph.verify(user.password_hash, req.password)
    except VerifyMismatchError as exc:
        username_limiter.record_failure(req.username)
        ip_limiter.record_failure(client_ip)
        logger.warning(
            "login_failure",
            extra={"username": req.username, "ip": client_ip, "reason": "wrong_password"},
        )
        raise HTTPException(status_code=401, detail=_invalid_msg) from exc

    username_limiter.record_success(req.username)

    now = int(time.time())
    expires_in = 3600  # 1 hour default
    claims = {
        "sub": user.username,
        "user_id": user.id,
        "tenant": user.tenant,
        "is_admin": user.is_admin,
        "must_change_password": user.must_change_password,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + expires_in,
    }
    token = jwt.encode(claims, settings.jwt_private_key, algorithm="RS256")

    # Issue refresh token
    plain_refresh = secrets.token_hex(32)
    refresh_hash = hashlib.sha256(plain_refresh.encode()).hexdigest()
    refresh_ttl_days = settings.refresh_token_ttl_days
    refresh_expires_at = datetime.now(tz=UTC) + timedelta(days=refresh_ttl_days)
    async with session_scope(app.state.session_factory) as session:
        session.add(
            RefreshTokenRow(
                user_id=user.id,
                token_hash=refresh_hash,
                expires_at=refresh_expires_at,
            )
        )

    logger.info(
        "login_success", extra={"username": req.username, "user_id": user.id, "ip": client_ip}
    )
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        refresh_token=plain_refresh,
        refresh_token_expires_in=refresh_ttl_days * 86400,
    )


@app.post("/refresh", response_model=LoginResponse)
async def refresh(req: RefreshRequest) -> LoginResponse:
    settings: Settings = app.state.settings
    if not settings.jwt_private_key:
        raise HTTPException(status_code=500, detail="jwt_private_key not configured")

    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    async with session_scope(app.state.session_factory) as session:
        result = await session.execute(
            select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_hash)
        )
        rt_row = result.scalar_one_or_none()

    if rt_row is None or rt_row.revoked_at is not None:
        raise HTTPException(status_code=401, detail="invalid or revoked refresh token")
    expires_at = rt_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if datetime.now(tz=UTC) > expires_at:
        raise HTTPException(status_code=401, detail="refresh token expired")

    async with session_scope(app.state.session_factory) as session:
        user_result = await session.execute(select(UserRow).where(UserRow.id == rt_row.user_id))
        user = user_result.scalar_one_or_none()

    if user is None or user.disabled:
        raise HTTPException(status_code=401, detail="user not found or disabled")

    now = int(time.time())
    expires_in = 3600
    claims = {
        "sub": user.username,
        "user_id": user.id,
        "tenant": user.tenant,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + expires_in,
    }
    claims["is_admin"] = user.is_admin
    claims["must_change_password"] = user.must_change_password
    new_access_token = jwt.encode(claims, settings.jwt_private_key, algorithm="RS256")

    # Rotate refresh token: revoke old, issue new
    async with session_scope(app.state.session_factory) as session:
        result = await session.execute(
            select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_hash)
        )
        rt_row_live = result.scalar_one_or_none()
        if rt_row_live is not None:
            rt_row_live.revoked_at = datetime.now(tz=UTC)

        plain_refresh = secrets.token_hex(32)
        refresh_hash = hashlib.sha256(plain_refresh.encode()).hexdigest()
        refresh_ttl_days = settings.refresh_token_ttl_days
        refresh_expires_at = datetime.now(tz=UTC) + timedelta(days=refresh_ttl_days)
        session.add(
            RefreshTokenRow(
                user_id=user.id,
                token_hash=refresh_hash,
                expires_at=refresh_expires_at,
            )
        )

    logger.info("token_refreshed", extra={"user_id": user.id})
    return LoginResponse(
        access_token=new_access_token,
        expires_in=expires_in,
        refresh_token=plain_refresh,
        refresh_token_expires_in=refresh_ttl_days * 86400,
    )


@app.post("/logout")
async def logout(req: LogoutRequest | None = None) -> dict[str, str]:
    if req and req.refresh_token:
        token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
        async with session_scope(app.state.session_factory) as session:
            result = await session.execute(
                select(RefreshTokenRow).where(RefreshTokenRow.token_hash == token_hash)
            )
            rt_row = result.scalar_one_or_none()
            if rt_row is not None and rt_row.revoked_at is None:
                rt_row.revoked_at = datetime.now(tz=UTC)
    return {"status": "ok"}


@app.post("/verify", response_model=Principal)
async def verify(req: VerifyRequest) -> Principal:
    # API key path — format: ak_<id>_<secret>
    if req.token.startswith("ak_"):
        return await _verify_api_key(req.token)

    settings: Settings = app.state.settings
    if not settings.jwt_public_key:
        raise HTTPException(status_code=500, detail="jwt_public_key not configured")

    effective_grace = min(req.grace_sec, settings.grace_max_sec)

    try:
        claims = jwt.decode(
            req.token,
            settings.jwt_public_key,
            algorithms=["RS256", "ES256"],
            issuer=settings.jwt_issuer,
            options={
                "require": ["exp", "iat", "sub"],
                "verify_exp": False,  # we handle exp manually to support grace
            },
        )
    except jwt.exceptions.InvalidSignatureError as exc:
        logger.warning("verify_failure", extra={"sub": "unknown", "reason": "invalid_signature"})
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc

    now = time.time()
    exp = float(claims.get("exp", 0))
    if now > exp + effective_grace:
        logger.warning(
            "verify_failure", extra={"sub": claims.get("sub", "unknown"), "reason": "token_expired"}
        )
        raise HTTPException(status_code=401, detail="token expired")

    grace_applied = now > exp

    if grace_applied:
        logger.info(
            "grace_period_applied",
            extra={
                "sub": claims.get("sub"),
                "exp": exp,
                "now": now,
                "delta": now - exp,
                "grace_sec": effective_grace,
            },
        )

    user_id: int = int(claims.get("user_id", 0))

    # Look up user access list (with short TTL cache)
    cache: _AccessCache = app.state.access_cache
    access = cache.get(user_id)
    if access is None:
        access = await _fetch_access(user_id)
        cache.set(user_id, access)

    return Principal(
        sub=claims["sub"],
        user_id=user_id,
        tenant=claims.get("tenant"),
        is_admin=bool(claims.get("is_admin", False)),
        must_change_password=bool(claims.get("must_change_password", False)),
        access=access,
        grace_applied=grace_applied,
    )


async def _fetch_access(user_id: int) -> list[ResourceRef]:
    async with session_scope(app.state.session_factory) as session:
        stmt = select(UserResourceAccessRow).where(UserResourceAccessRow.user_id == user_id)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [ResourceRef(kind=r.kind, name=r.name) for r in rows]


# ---------------------------------------------------------------------------
# JWKS — public key discovery for JWT rotation
# ---------------------------------------------------------------------------


def _int_to_b64url(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


def _pem_to_jwk(pem: str) -> dict:
    key = load_pem_public_key(pem.encode())
    if not isinstance(key, RSAPublicKey):
        raise ValueError("only RSA keys supported")
    nums = key.public_numbers()
    der = key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    kid = hashlib.sha256(der).hexdigest()[:16]
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _int_to_b64url(nums.n),
        "e": _int_to_b64url(nums.e),
    }


@app.get("/.well-known/jwks.json")
async def jwks() -> dict:
    """Return the active public key as a JWK Set."""
    settings: Settings = app.state.settings
    if not settings.jwt_public_key:
        raise HTTPException(status_code=503, detail="jwt_public_key not configured")
    try:
        jwk = _pem_to_jwk(settings.jwt_public_key)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"keys": [jwk]}


# ---------------------------------------------------------------------------
# API keys — service-to-service calls without username/password flow
# ---------------------------------------------------------------------------


class CreateApiKeyRequest(BaseModel):
    name: str
    tenant: str | None = None
    expires_in_days: int | None = None


@app.post("/v1/api-keys", status_code=201)
async def create_api_key(req: CreateApiKeyRequest) -> dict:
    """Create a new API key. Returns the plain key ONCE — it is never stored."""
    secret = secrets.token_hex(32)
    key_hash = _ph.hash(secret)
    expires_at: datetime | None = None
    if req.expires_in_days is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(days=req.expires_in_days)

    async with session_scope(app.state.session_factory) as session:
        row = ApiKeyRow(
            key_hash=key_hash,
            name=req.name,
            tenant=req.tenant,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        row_id = row.id

    plain_key = f"ak_{row_id}_{secret}"
    logger.info("api_key_created", extra={"name": req.name, "id": row_id, "tenant": req.tenant})
    return {"key": plain_key, "id": row_id, "name": req.name}


async def _verify_api_key(token: str) -> Principal:
    """Parse and validate an API key token, returning a Principal on success."""
    parts = token.split("_", 2)  # "ak", "<id>", "<secret>"
    if len(parts) != 3 or parts[0] != "ak":
        raise HTTPException(status_code=401, detail="invalid api key format")
    try:
        row_id = int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid api key format") from exc
    secret = parts[2]

    async with session_scope(app.state.session_factory) as session:
        result = await session.execute(select(ApiKeyRow).where(ApiKeyRow.id == row_id))
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=401, detail="invalid api key")

    # Argon2 verification is slow — done outside the DB session (session already closed above)
    try:
        _ph.verify(row.key_hash, secret)
    except VerifyMismatchError as exc:
        raise HTTPException(status_code=401, detail="invalid api key") from exc

    if row.disabled:
        raise HTTPException(status_code=401, detail="api key disabled")

    if row.expires_at is not None:
        now_utc = datetime.now(tz=UTC)
        if now_utc > row.expires_at:
            raise HTTPException(status_code=401, detail="api key expired")

    return Principal(
        sub=f"apikey:{row.name}",
        user_id=0,
        tenant=row.tenant,
        access=[],
        grace_applied=False,
    )
