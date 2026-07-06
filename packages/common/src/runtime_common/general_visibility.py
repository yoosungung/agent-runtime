"""Resource access visibility (private / tenant / public / allowlist)."""

from __future__ import annotations

from enum import StrEnum


class GeneralVisibility(StrEnum):
    PRIVATE = "private"
    TENANT = "tenant"
    PUBLIC = "public"
    ALLOWLIST = "allowlist"


VALID_GENERAL_VISIBILITIES = frozenset(GeneralVisibility)


def validate_tenant_visibility(visibility: str, owner_tenant: str | None) -> None:
    if visibility == GeneralVisibility.TENANT and not owner_tenant:
        raise ValueError("tenant visibility requires a tenant on the creator account")


def can_use_source_meta(
    *,
    visibility: str,
    created_by_user_id: int | None,
    owner_tenant: str | None,
    principal_user_id: int,
    principal_tenant: str | None,
    acl_has_row: bool = False,
    is_admin: bool = False,
) -> bool:
    if is_admin:
        return True
    if created_by_user_id is not None and created_by_user_id == principal_user_id:
        return True
    if visibility == GeneralVisibility.PUBLIC:
        return True
    if visibility == GeneralVisibility.TENANT:
        return (
            owner_tenant is not None
            and principal_tenant is not None
            and owner_tenant == principal_tenant
        )
    if visibility == GeneralVisibility.ALLOWLIST:
        return acl_has_row
    return False


def can_use_general_agent(
    *,
    visibility: str,
    created_by_user_id: int | None,
    owner_tenant: str | None,
    principal_user_id: int,
    principal_tenant: str | None,
    is_admin: bool = False,
    acl_has_row: bool = False,
) -> bool:
    return can_use_source_meta(
        visibility=visibility,
        created_by_user_id=created_by_user_id,
        owner_tenant=owner_tenant,
        principal_user_id=principal_user_id,
        principal_tenant=principal_tenant,
        acl_has_row=acl_has_row,
        is_admin=is_admin,
    )


def can_manage_general_agent(
    *,
    created_by_user_id: int | None,
    principal_user_id: int,
    is_admin: bool = False,
) -> bool:
    if is_admin:
        return True
    return created_by_user_id is not None and created_by_user_id == principal_user_id
