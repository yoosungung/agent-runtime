from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from backend.bundle_storage import BundleStorage

router = APIRouter(prefix="/bundles", tags=["bundles"])

RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@router.get("/{sha256}.zip")
async def serve_bundle(sha256: str, request: Request) -> Response:
    if not RE_SHA256.match(sha256):
        raise HTTPException(status_code=404, detail="Not found")

    storage: BundleStorage = request.app.state.bundle_storage
    return await storage.serve_bundle(sha256)


@router.get("/{sha256}.sig")
async def serve_signature(sha256: str, request: Request) -> Response:
    if not RE_SHA256.match(sha256):
        raise HTTPException(status_code=404, detail="Not found")

    storage: BundleStorage = request.app.state.bundle_storage
    return await storage.serve_sig(sha256)
