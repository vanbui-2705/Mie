from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTENT_MAIN = ROOT / "extension" / "content-main.js"
MANIFEST = ROOT / "extension" / "manifest.json"


def test_group_destination_is_scoped_to_share_overlay() -> None:
    source = CONTENT_MAIN.read_text(encoding="utf-8-sig")

    assert "clickFirstMatchingMenuItem(patterns, 12000, { overlayOnly: true })" in source
    assert 'const roots = options.overlayOnly ? findVisibleShareSurfaces() : [document];' in source
    assert "/^group$/" not in source
    assert "/^nhom$/" not in source


def test_extension_main_world_version_matches_manifest() -> None:
    source = CONTENT_MAIN.read_text(encoding="utf-8-sig")
    manifest_version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]

    assert f'const VERSION = "{manifest_version}";' in source


def test_facebook_url_is_not_typed_verbatim_into_group_search() -> None:
    source = CONTENT_MAIN.read_text(encoding="utf-8-sig")

    assert "function shareTargetSearchQuery(targetName, targetUrl)" in source
    assert '!/^https?:\\/\\//i.test(name)' in source
    assert 'shareTargetQuery(targetUrl).replace(/[-_.]+/g, " ")' in source


def test_final_post_button_uses_pointer_events_and_waits_for_dialog_to_close() -> None:
    source = CONTENT_MAIN.read_text(encoding="utf-8-sig")

    assert "function dispatchSubmitPointerEvents(element)" in source
    assert "function findFinalShareSubmitButton(patterns)" in source
    assert 'button.closest("div[role=\'dialog\']")' in source
    assert "/tao bai viet|create post/" in source
    assert 'new PointerEvent("pointerdown", options)' in source
    assert "dispatchSubmitPointerEvents(button);" in source
    assert "!button.isConnected" in source
    assert "if (accepted) return { success: true };" in source
