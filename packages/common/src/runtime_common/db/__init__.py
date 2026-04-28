"""runtime_common.db — async SQLAlchemy engine utilities.

Re-exports engine helpers so that existing callers using
``from runtime_common.db import make_engine, make_session_factory, session_scope``
continue to work without modification.

Models live in ``runtime_common.db.models`` and must be imported explicitly
by services that need them (gateway/pool do NOT import models).
"""

from runtime_common.db.engine import make_engine, make_session_factory, session_scope

__all__ = ["make_engine", "make_session_factory", "session_scope"]
