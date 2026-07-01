"""VFS push conflict — another writer changed the file since pull."""

from __future__ import annotations


class ProfileVfsConflictError(Exception):
    """Raised when VFS modified_at changed between pull and push."""

    def __init__(self, agent_name: str, paths: list[str]) -> None:
        self.agent_name = agent_name
        self.paths = paths
        super().__init__(f"VFS conflict for {agent_name}: {', '.join(paths)}")
