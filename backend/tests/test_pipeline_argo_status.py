from __future__ import annotations

import pytest

from backend.pipeline_argo import workflow_status_from_object


def test_workflow_status_from_object_extracts_phase_and_timestamps():
    wf = {
        "status": {
            "phase": "Running",
            "startedAt": "2026-06-26T12:00:01Z",
            "finishedAt": None,
        }
    }
    assert workflow_status_from_object(wf) == {
        "phase": "Running",
        "started_at": "2026-06-26T12:00:01Z",
        "ended_at": None,
    }


def test_workflow_status_from_object_empty_status():
    assert workflow_status_from_object({}) == {
        "phase": None,
        "started_at": None,
        "ended_at": None,
    }
