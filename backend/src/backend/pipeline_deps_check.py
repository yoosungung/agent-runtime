from __future__ import annotations


def assert_path_graph_console_ready() -> None:
    """Fail fast when backend runs against a stale path-graph install."""
    from path_graph.contracts.source import SourceDriver

    values = {d.value for d in SourceDriver}
    if SourceDriver.MANUAL.value not in values:
        raise RuntimeError(
            "Installed path-graph is outdated (SourceDriver.MANUAL missing). "
            "From agent-runtime repo run: uv sync --package backend, then restart backend."
        )
