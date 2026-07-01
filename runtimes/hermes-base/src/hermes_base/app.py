"""hermes-base FastAPI — agents-runtime pool /invoke contract."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from hermes_base.context import reset_current_token, set_current_token
from hermes_base.hermes_cache import get_or_build_hermes_agent
from hermes_base.hermes_stream import stream_run_conversation
from hermes_base.http_client import close_mcp_http_client
from hermes_base.profile_lock import ProfileLockContended, build_profile_lock
from hermes_base.profile_materializer import ProfileMaterializer, config_needs_reconcile
from hermes_base.settings import Settings
from hermes_base.vfs_errors import ProfileVfsConflictError
from hermes_base.vfs_profile import ProfileVfsSync, PullManifest
from runtime_common.deploy_client import DeployApiClient
from runtime_common.factory import merge_configs
from runtime_common.instance_builder import build_secrets_resolver
from runtime_common.instance_cache import InstanceCache
from runtime_common.logging import configure_logging
from runtime_common.opik_tracing import configure_opik, opik_trace_context
from runtime_common.pool_resolve import ResolveHeaderMismatchError, resolve_for_invoke
from runtime_common.registry import ActiveCounter
from runtime_common.schemas import Principal, ResolveResponse
from runtime_common.vfs.store import AgentVfsStore, AsyncpgAgentVfsStore, MemoryAgentVfsStore

logger = logging.getLogger(__name__)

DEPLOY_MODE = "hermes_general"
EXPECTED_POOL = "agent:hermes"


class InvokeRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict
    session_id: str | None = None
    principal: Principal | None = None
    stream: bool = False


def _principal_from_header(header_b64: str | None) -> Principal | None:
    if not header_b64:
        return None
    try:
        return Principal.model_validate_json(base64.b64decode(header_b64))
    except Exception as exc:
        logger.warning("x_principal_decode_failed", extra={"error": str(exc)})
        return None


async def _open_vfs_store(settings: Settings) -> tuple[AgentVfsStore, object | None]:
    if settings.vfs_dsn:
        from runtime_common.vfs.store import create_asyncpg_pool

        dsn = settings.vfs_dsn.replace("postgresql+asyncpg://", "postgresql://")
        pool = await create_asyncpg_pool(dsn, pgbouncer=settings.vfs_pgbouncer)
        return AsyncpgAgentVfsStore(pool), pool
    logger.warning("vfs_memory_fallback", extra={"reason": "VFS_DSN unset"})
    return MemoryAgentVfsStore(), None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    configure_opik(settings.opik_url, settings.opik_workspace)
    instance_cache = InstanceCache(settings.instance_cache_max)
    counter = ActiveCounter(settings.max_concurrent)
    deploy_client = DeployApiClient(settings.deploy_api_url)
    work_root = Path(settings.hermes_work_dir)
    work_root.mkdir(parents=True, exist_ok=True)
    materializer = ProfileMaterializer(work_root)
    vfs_store, vfs_pool = await _open_vfs_store(settings)
    vfs_sync = ProfileVfsSync(vfs_store)
    profile_lock = build_profile_lock(settings.redis_url, ttl_sec=settings.lock_ttl_sec)

    app.state.settings = settings
    app.state.instance_cache = instance_cache
    app.state.counter = counter
    app.state.deploy_client = deploy_client
    app.state.materializer = materializer
    app.state.vfs_sync = vfs_sync
    app.state.profile_lock = profile_lock
    app.state.vfs_pool = vfs_pool

    yield

    await instance_cache.clear()
    await deploy_client.aclose()
    await close_mcp_http_client()
    if vfs_pool is not None:
        await vfs_pool.close()
    if hasattr(profile_lock, "aclose"):
        await profile_lock.aclose()


app = FastAPI(title="hermes-base", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "kind": app.state.settings.runtime_kind}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


async def _resolve_hermes_invoke(
    req: InvokeRequest,
    principal: Principal,
    x_resolve: str | None,
    deploy_client: DeployApiClient,
) -> ResolveResponse:
    principal_id = str(principal.user_id) if principal.user_id else principal.sub
    try:
        return await resolve_for_invoke(
            deploy_client,
            kind="agent",
            name=req.agent,
            version=req.version,
            principal=principal_id,
            x_resolve=x_resolve,
        )
    except ResolveHeaderMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"resolve failed: {exc}") from exc


def _validate_hermes_source(source, agent: str) -> None:
    deploy_mode = getattr(source, "deploy_mode", None) or "bundle"
    if deploy_mode != DEPLOY_MODE:
        raise HTTPException(
            status_code=400,
            detail=f"agent {agent} is not hermes_general (got {deploy_mode})",
        )
    if source.runtime_pool != EXPECTED_POOL:
        raise HTTPException(
            status_code=400,
            detail=f"runtime_pool mismatch: {source.runtime_pool} != {EXPECTED_POOL}",
        )


async def _prepare_scratch(
    *,
    agent: str,
    cfg: dict,
    session_dsn: str | None,
    vfs_sync: ProfileVfsSync,
    materializer: ProfileMaterializer,
    scratch: Path,
) -> PullManifest:
    manifest = await vfs_sync.pull(agent, scratch)
    if config_needs_reconcile(scratch, cfg):
        materializer.ensure(agent, cfg, session_dsn=session_dsn, force=True)
    elif not (scratch / "SOUL.md").is_file():
        await vfs_sync.seed_from_config(agent, cfg, session_dsn=session_dsn)
        manifest = await vfs_sync.pull(agent, scratch)
    return manifest


def _invoke_result_payload(
    *,
    result: dict,
    req: InvokeRequest,
    scratch: Path,
) -> dict:
    output = result.get("final_response") if isinstance(result, dict) else str(result)
    return {
        "result": {
            "output": output,
            "session_id": req.session_id,
            "agent": req.agent,
            "profile_home": str(scratch),
        }
    }


@app.post("/invoke", response_model=None)
async def invoke(
    req: InvokeRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_principal: Annotated[str | None, Header()] = None,
    x_resolve: Annotated[str | None, Header()] = None,
) -> dict | JSONResponse | StreamingResponse:
    settings: Settings = app.state.settings
    if settings.runtime_kind != "hermes":
        raise HTTPException(status_code=500, detail="RUNTIME_KIND must be hermes")

    principal = req.principal or _principal_from_header(x_principal)
    if principal is None:
        raise HTTPException(status_code=401, detail="missing principal")
    if not principal.user_id:
        raise HTTPException(status_code=400, detail="hermes_general invoke requires user_id")

    message = req.input.get("message")
    if not message:
        raise HTTPException(status_code=400, detail="input.message required")

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    tok_token = set_current_token(token)

    try:
        resolved = await _resolve_hermes_invoke(
            req, principal, x_resolve, app.state.deploy_client
        )
        source = resolved.source
        user = resolved.user
        _validate_hermes_source(source, req.agent)

        secrets = build_secrets_resolver(user)
        cfg = merge_configs(source.config, user.config if user else None)
        session_dsn = settings.hermes_session_dsn or None
        vfs_sync: ProfileVfsSync = app.state.vfs_sync
        materializer: ProfileMaterializer = app.state.materializer
        profile_lock = app.state.profile_lock
        scratch = materializer.home_for(req.agent)
        counter: ActiveCounter = app.state.counter
        user_id = str(principal.user_id)
        opik_meta = {"version": req.version or "latest", "runtime_kind": settings.runtime_kind}
        task_id = req.session_id or f"rt-{req.agent}"

        if req.stream:

            async def _stream_body() -> AsyncIterator[str]:
                set_current_token(token)
                with opik_trace_context(
                    name=f"agent:{req.agent}",
                    project_name=req.agent,
                    session_id=req.session_id,
                    user_id=user_id,
                    metadata=opik_meta,
                ):
                    try:
                        async with profile_lock.hold(req.agent):
                            manifest = await _prepare_scratch(
                                agent=req.agent,
                                cfg=cfg,
                                session_dsn=session_dsn,
                                vfs_sync=vfs_sync,
                                materializer=materializer,
                                scratch=scratch,
                            )
                            async with counter:
                                instance = await get_or_build_hermes_agent(
                                    app.state.instance_cache,
                                    source,
                                    user,
                                    secrets,
                                    profile_home=scratch,
                                    user_id=principal.user_id,
                                    mcp_gateway_url=settings.mcp_gateway_url,
                                    agent_factory=(
                                        app.state.agent_factory
                                        if hasattr(app.state, "agent_factory")
                                        else None
                                    ),
                                )

                                def _run(on_delta) -> dict:
                                    return instance.run_conversation(
                                        user_message=str(message),
                                        task_id=task_id,
                                        stream_callback=on_delta,
                                    )

                                async for chunk in stream_run_conversation(
                                    _run,
                                    timeout=float(settings.invoke_timeout_sec),
                                ):
                                    yield chunk

                            await vfs_sync.push(req.agent, scratch, manifest)
                    except ProfileLockContended as exc:
                        yield f'data: {{"error": "profile lock contended for {exc.agent_name}"}}\n\n'
                    except ProfileVfsConflictError as exc:
                        logger.warning(
                            "invoke_vfs_conflict",
                            extra={"agent": req.agent, "paths": exc.paths},
                        )
                        yield f'data: {{"error": "VFS conflict: {", ".join(exc.paths)}"}}\n\n'
                    except HTTPException as exc:
                        yield f'data: {{"error": "{exc.detail}"}}\n\n'

            return StreamingResponse(_stream_body(), media_type="text/event-stream")

        with opik_trace_context(
            name=f"agent:{req.agent}",
            project_name=req.agent,
            session_id=req.session_id,
            user_id=user_id,
            metadata=opik_meta,
        ):
            try:
                async with profile_lock.hold(req.agent):
                    manifest = await _prepare_scratch(
                        agent=req.agent,
                        cfg=cfg,
                        session_dsn=session_dsn,
                        vfs_sync=vfs_sync,
                        materializer=materializer,
                        scratch=scratch,
                    )
                    async with counter:
                        instance = await get_or_build_hermes_agent(
                            app.state.instance_cache,
                            source,
                            user,
                            secrets,
                            profile_home=scratch,
                            user_id=principal.user_id,
                            mcp_gateway_url=settings.mcp_gateway_url,
                            agent_factory=(
                                app.state.agent_factory
                                if hasattr(app.state, "agent_factory")
                                else None
                            ),
                        )

                        def _run() -> dict:
                            return instance.run_conversation(
                                user_message=str(message),
                                task_id=task_id,
                            )

                        try:
                            result = await asyncio.wait_for(
                                asyncio.to_thread(_run),
                                timeout=settings.invoke_timeout_sec,
                            )
                        except TimeoutError as exc:
                            raise HTTPException(status_code=504, detail="invoke timeout") from exc
                        except Exception as exc:
                            logger.exception("hermes_invoke_failed", extra={"agent": req.agent})
                            raise HTTPException(status_code=500, detail=str(exc)) from exc

                    await vfs_sync.push(req.agent, scratch, manifest)
            except ProfileLockContended as exc:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"profile lock contended for {exc.agent_name}"},
                    headers={"Retry-After": str(min(settings.lock_ttl_sec, 60))},
                )
            except ProfileVfsConflictError as exc:
                logger.warning(
                    "invoke_vfs_conflict",
                    extra={"agent": req.agent, "paths": exc.paths},
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"VFS conflict on push: {', '.join(exc.paths)}",
                ) from exc

        return _invoke_result_payload(result=result, req=req, scratch=scratch)
    finally:
        reset_current_token(tok_token)
