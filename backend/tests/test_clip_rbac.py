from app.rbac_catalog import OWN_RESOURCE_PERMISSIONS, PERMISSIONS, ROLE_DEFINITIONS


def test_clip_permissions_registered() -> None:
    for code in ("clip:read", "clip:create", "clip:cancel", "clip:delete"):
        assert code in PERMISSIONS
    assert "clip:read:any" in PERMISSIONS


def test_clip_own_permissions_granted_to_base_user() -> None:
    assert "clip:create" in OWN_RESOURCE_PERMISSIONS
    assert "clip:create" in ROLE_DEFINITIONS["user"]["permissions"]
    assert "clip:read:any" not in OWN_RESOURCE_PERMISSIONS
