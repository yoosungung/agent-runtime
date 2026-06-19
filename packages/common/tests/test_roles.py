from runtime_common.roles import UserRole, parse_role, role_at_least, role_from_legacy_is_admin


def test_role_at_least() -> None:
    assert role_at_least(UserRole.USER, UserRole.USER)
    assert not role_at_least(UserRole.USER, UserRole.DEVELOPER)
    assert role_at_least(UserRole.DEVELOPER, UserRole.USER)
    assert role_at_least(UserRole.ADMIN, UserRole.DEVELOPER)
    assert not role_at_least(UserRole.DEVELOPER, UserRole.ADMIN)


def test_parse_role_fallback() -> None:
    assert parse_role("developer") == UserRole.DEVELOPER
    assert parse_role("invalid") == UserRole.USER
    assert parse_role(None) == UserRole.USER


def test_role_from_legacy_is_admin() -> None:
    assert role_from_legacy_is_admin(True) == UserRole.ADMIN
    assert role_from_legacy_is_admin(False) == UserRole.USER
