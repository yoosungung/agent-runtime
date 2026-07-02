from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ArgoCallback(BaseModel):
    namespace: str
    workflow: str
    node_field_selector: str = ""


class JobCallback(BaseModel):
    argo: ArgoCallback | None = None


class JobRecord(BaseModel):
    job_id: str
    agent: str
    version: str | None = None
    session_id: str | None = None
    principal_sub: str
    tenant: str | None = None
    status: JobStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    callback: JobCallback | None = None
    auth_token: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


def new_job_id() -> str:
    return str(uuid.uuid4())


class JobStore:
    """Redis-backed async agent job records."""

    def __init__(self, redis_client: Any, *, ttl_sec: int = 604_800) -> None:
        self._redis = redis_client
        self._ttl_sec = ttl_sec

    def _key(self, job_id: str) -> str:
        return f"rt:agent_job:{job_id}"

    async def create(self, record: JobRecord) -> JobRecord:
        await self._redis.set(
            self._key(record.job_id),
            record.model_dump_json(),
            ex=self._ttl_sec,
        )
        return record

    async def get(self, job_id: str) -> JobRecord | None:
        raw = await self._redis.get(self._key(job_id))
        if not raw:
            return None
        return JobRecord.model_validate_json(raw)

    async def save(self, record: JobRecord) -> JobRecord:
        record.updated_at = time.time()
        await self._redis.set(
            self._key(record.job_id),
            record.model_dump_json(),
            ex=self._ttl_sec,
        )
        return record

    async def mark_running(self, job_id: str) -> JobRecord:
        record = await self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.running
        return await self.save(record)

    async def mark_succeeded(self, job_id: str, *, output: dict[str, Any]) -> JobRecord:
        record = await self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.succeeded
        record.output = output
        record.error = None
        return await self.save(record)

    async def mark_failed(self, job_id: str, *, error: str) -> JobRecord:
        record = await self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.failed
        record.error = error
        return await self.save(record)
