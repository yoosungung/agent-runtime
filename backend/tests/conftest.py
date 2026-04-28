"""Patch SQLAlchemy model types for SQLite compatibility.

Must run before any backend or runtime_common modules are imported so that
the metadata tables are already patched when create_all() is called.
"""

from sqlalchemy import JSON, Integer
from sqlalchemy.dialects.postgresql import JSONB

import runtime_common.db.models as _m

for _table in _m.Base.metadata.tables.values():
    for _col in _table.columns:
        # Remove onupdate so async SQLite doesn't trigger ORM lazy-load
        if _col.name == "updated_at":
            _col.onupdate = None
        # SQLite doesn't support BigInteger as PK — downgrade to Integer
        if _col.primary_key and "BigInteger" in type(_col.type).__name__:
            _col.type = Integer()
        # SQLite doesn't support JSONB — fall back to JSON
        if isinstance(_col.type, JSONB):
            _col.type = JSON()
