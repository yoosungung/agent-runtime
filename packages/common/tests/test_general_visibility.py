"""Tests for general-agent visibility helpers."""

from runtime_common.general_visibility import (
    GeneralVisibility,
    can_manage_general_agent,
    can_use_general_agent,
    can_use_source_meta,
    validate_tenant_visibility,
)


def test_private_only_creator_and_admin():
    assert can_use_general_agent(
        visibility=GeneralVisibility.PRIVATE,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=1,
        principal_tenant="acme",
    )
    assert not can_use_general_agent(
        visibility=GeneralVisibility.PRIVATE,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="acme",
    )
    assert can_use_general_agent(
        visibility=GeneralVisibility.PRIVATE,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="acme",
        is_admin=True,
    )


def test_tenant_visibility_same_tenant_only():
    assert can_use_general_agent(
        visibility=GeneralVisibility.TENANT,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="acme",
    )
    assert not can_use_general_agent(
        visibility=GeneralVisibility.TENANT,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="other",
    )
    assert not can_use_general_agent(
        visibility=GeneralVisibility.TENANT,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant=None,
    )


def test_public_any_authenticated_user():
    assert can_use_general_agent(
        visibility=GeneralVisibility.PUBLIC,
        created_by_user_id=1,
        owner_tenant=None,
        principal_user_id=99,
        principal_tenant=None,
    )


def test_manage_only_creator_or_admin():
    assert can_manage_general_agent(created_by_user_id=5, principal_user_id=5)
    assert not can_manage_general_agent(created_by_user_id=5, principal_user_id=6)
    assert can_manage_general_agent(
        created_by_user_id=5, principal_user_id=6, is_admin=True
    )


def test_allowlist_requires_acl_row():
    assert can_use_source_meta(
        visibility=GeneralVisibility.ALLOWLIST,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="acme",
        acl_has_row=True,
    )
    assert not can_use_source_meta(
        visibility=GeneralVisibility.ALLOWLIST,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=2,
        principal_tenant="acme",
        acl_has_row=False,
    )
    assert can_use_source_meta(
        visibility=GeneralVisibility.ALLOWLIST,
        created_by_user_id=1,
        owner_tenant="acme",
        principal_user_id=1,
        principal_tenant="acme",
        acl_has_row=False,
    )


def test_validate_tenant_visibility_requires_owner_tenant():
    validate_tenant_visibility(GeneralVisibility.PRIVATE, "acme")
    validate_tenant_visibility(GeneralVisibility.PUBLIC, None)
    try:
        validate_tenant_visibility(GeneralVisibility.TENANT, None)
    except ValueError as exc:
        assert "tenant" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
