"""Prune script smoke test — optional when hermes-agent is vendored."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_prune_script_exists_and_is_executable() -> None:
    root = Path(__file__).resolve().parents[3]
    candidates = [
        root / "scripts" / "prune-hermes-packages.sh",
        root / "scripts" / "hermes" / "prune-hermes-packages.sh",
    ]
    script = next((p for p in candidates if p.is_file()), None)
    assert script is not None, f"prune script not found under {candidates}"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
