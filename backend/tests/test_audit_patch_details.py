from backend.audit import audit_patch_details


def test_audit_patch_details_returns_sorted_changed_scalar():
    assert audit_patch_details({"mcp_servers": [], "system_prompt": "x"}) == {
        "changed": "mcp_servers, system_prompt",
    }


def test_audit_patch_details_empty_update():
    assert audit_patch_details({}) == {}
