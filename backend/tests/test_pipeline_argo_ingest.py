from __future__ import annotations

from backend.pipeline_argo import ingest_rag_parameters


def test_ingest_rag_parameters_omits_inline_when_s3_key_present():
    params = ingest_rag_parameters(
        tenant="didim",
        batch_manifest_json='[{"tenant":"didim","source_id":"x"}]',
        batch_manifest_key="batches/didim/20260626-020623/manifest.jsonl",
    )
    by_name = {p["name"]: p["value"] for p in params}
    assert by_name["batch_manifest"] == ""
    assert by_name["batch_manifest_key"] == "batches/didim/20260626-020623/manifest.jsonl"
    assert by_name["tenant"] == "didim"
    assert by_name["rag"] == "true"


def test_ingest_rag_parameters_keeps_inline_when_no_s3_key():
    inline = '[{"tenant":"didim","project_id":"p1"}]'
    params = ingest_rag_parameters(
        tenant="didim",
        batch_manifest_json=inline,
        batch_manifest_key="",
    )
    by_name = {p["name"]: p["value"] for p in params}
    assert by_name["batch_manifest"] == inline
    assert by_name["batch_manifest_key"] == ""
