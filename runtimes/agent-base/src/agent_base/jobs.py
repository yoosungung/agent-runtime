from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from agent_base.invoke_handler import InvokeContext, execute_invoke
from agent_base.settings import Settings
from runtime_common.agent_jobs import (
    ArgoCallback,
    JobCallback,
    JobRecord,
    JobStatus,
    JobStore,
    new_job_id,
)
from runtime_common.argo_workflows import resume_workflow, stop_workflow
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)


class ArgoCallbackRequest(BaseModel):
    namespace: str
    workflow: str
    node_field_selector: str = ""


class JobCallbackRequest(BaseModel):
    argo: ArgoCallbackRequest | None = None


class JobSubmitRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict[str, Any]
    session_id: str | None = None
    principal: Principal | None = None
    callback: JobCallbackRequest | None = None
    job_id: str | None = None


class JobService:
    def __init__(
        self,
        store: JobStore,
        ctx: InvokeContext,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._store = store
        self._ctx = ctx
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def submit(
        self,
        req: JobSubmitRequest,
        *,
        principal: Principal,
        auth_token: str | None,
        x_resolve: str | None = None,
    ) -> JobRecord:
        callback = None
        if req.callback and req.callback.argo:
            argo = req.callback.argo
            callback = JobCallback(
                argo=ArgoCallback(
                    namespace=argo.namespace,
                    workflow=argo.workflow,
                    node_field_selector=argo.node_field_selector,
                )
            )

        record = JobRecord(
            job_id=req.job_id or new_job_id(),
            agent=req.agent,
            version=req.version,
            session_id=req.session_id,
            principal_sub=principal.sub,
            tenant=principal.tenant,
            status=JobStatus.pending,
            callback=callback,
            auth_token=auth_token,
        )
        await self._store.create(record)

        asyncio.create_task(self._run_job(record.job_id, req, principal, x_resolve))
        return record

    async def get_for_principal(self, job_id: str, *, principal: Principal) -> JobRecord:
        record = await self._store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        if record.principal_sub != principal.sub:
            raise HTTPException(status_code=403, detail="job access denied")
        return record

    async def _run_job(
        self,
        job_id: str,
        req: JobSubmitRequest,
        principal: Principal,
        x_resolve: str | None,
    ) -> None:
        record = await self._store.get(job_id)
        token = record.auth_token if record else None
        try:
            await self._store.mark_running(job_id)
            result = await execute_invoke(
                self._ctx,
                agent=req.agent,
                version=req.version,
                input_data=req.input,
                session_id=req.session_id,
                principal=principal,
                token=token,
                x_resolve=x_resolve,
                timeout_sec=self._settings.job_invoke_timeout_sec,
            )
            record = await self._store.mark_succeeded(job_id, output=result)
            await self._maybe_argo_callback(record, success=True)
        except Exception as exc:
            record = await self._store.mark_failed(job_id, error=str(exc))
            await self._maybe_argo_callback(record, success=False, message=str(exc))
            logger.warning("agent_job_failed", extra={"job_id": job_id, "error": str(exc)})

    async def _maybe_argo_callback(
        self,
        record: JobRecord,
        *,
        success: bool,
        message: str = "",
    ) -> None:
        if record.callback is None or record.callback.argo is None:
            return
        if not self._settings.argo_server_url:
            logger.info(
                "argo_callback_skipped",
                extra={"job_id": record.job_id, "reason": "ARGO_SERVER_URL unset"},
            )
            return
        argo = record.callback.argo
        try:
            if success:
                await resume_workflow(
                    self._http,
                    base_url=self._settings.argo_server_url,
                    token=self._settings.argo_auth_token or None,
                    namespace=argo.namespace,
                    workflow=argo.workflow,
                    node_field_selector=argo.node_field_selector,
                )
            else:
                await stop_workflow(
                    self._http,
                    base_url=self._settings.argo_server_url,
                    token=self._settings.argo_auth_token or None,
                    namespace=argo.namespace,
                    workflow=argo.workflow,
                    node_field_selector=argo.node_field_selector,
                    message=message or "agent job failed",
                )
        except Exception as exc:
            logger.warning(
                "argo_callback_failed",
                extra={"job_id": record.job_id, "error": str(exc)},
            )
