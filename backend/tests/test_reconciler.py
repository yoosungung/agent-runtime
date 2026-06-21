from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.reconciler import reconcile_once


@pytest.mark.asyncio
async def test_reconcile_once_reads_settings_from_app_state():
    app = MagicMock()
    app.state.settings = MagicMock(K8S_PENDING_TIMEOUT_SEC=300)
    app.state.k8s_pool_manager = None

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    class _SessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    app.state.session_factory = MagicMock(return_value=_SessionCtx())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.reconciler.session_scope", lambda _factory: _SessionCtx())
        await reconcile_once(app)

    assert session.execute.await_count == 3
