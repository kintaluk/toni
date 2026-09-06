"""
Unit and integration tests for frontend delivery hardening, asset versioning,
caching policy, and container packaging rules.
"""

import re
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api import app, STATIC_DIR, ASSETS_DIR
from scripts.version_assets import version_assets, compute_file_hash, OWNED_ASSETS


@pytest.fixture
def api_client():
    return TestClient(app)


def test_required_styles_and_tokens():
    """Verify that toni.bundle.css contains all required brand utilities and tokens."""
    bundle_path = STATIC_DIR / "assets" / "toni.bundle.css"
    assert bundle_path.exists(), "toni.bundle.css must exist"
    css_text = bundle_path.read_text(encoding="utf-8")

    # Verify essential brand utilities and responsive rules
    required_utilities = [
        'bg-bone', 'text-ink', 'bg-lime', 'bg-lime/25', 'border-ink/15',
        'border-lime', 'font-serif', 'font-sans', 'shadow-2xs', 'shadow-xs',
        'rounded-tr-xs', 'backdrop-blur-xs', 'active:scale-98'
    ]
    for util in required_utilities:
        tw_escaped = util.replace(':', r'\:').replace('/', r'\/').replace('.', r'\.').replace('[', r'\[').replace(']', r'\]')
        pattern = re.compile(r'\.' + re.escape(tw_escaped) + r'[{:,.\s>\[]')
        assert pattern.search(css_text), f"Required utility '{util}' missing from toni.bundle.css"


def test_all_html_referenced_assets_exist():
    """Verify that all assets referenced in static/index.html exist on disk."""
    index_html = STATIC_DIR / "index.html"
    assert index_html.exists(), "static/index.html must exist"
    html_text = index_html.read_text(encoding="utf-8")

    # Find static/assets/... references
    refs = re.findall(r'static/assets/([a-zA-Z0-9_.-]+)', html_text)
    assert len(refs) > 0, "Must find asset references in static/index.html"
    for ref in set(refs):
        asset_file = STATIC_DIR / "assets" / ref
        assert asset_file.exists(), f"Referenced asset static/assets/{ref} does not exist on disk"

    # Also verify fallback assets/... references
    fallback_refs = re.findall(r'assets/([a-zA-Z0-9_.-]+)', html_text)
    for ref in set(fallback_refs):
        if "fonts.googleapis" in ref:
            continue
        asset_file = ASSETS_DIR / ref
        assert asset_file.exists(), f"Fallback asset assets/{ref} does not exist on disk"


def test_caching_policy_headers(api_client):
    """
    Verify immutable caching is only applied to HTTP 200 responses for recognised
    content-hashed assets, and never to errors or mutable resources.
    """
    # 1. Recognised hashed asset via /static/assets/
    bundle_hash = compute_file_hash(STATIC_DIR / "assets" / "toni.bundle.css")
    resp = api_client.get(f"/static/assets/toni.bundle.{bundle_hash}.css")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "public" in cc and "immutable" in cc and "max-age=31536000" in cc

    # 2. Recognised hashed asset via /assets/
    resp = api_client.get(f"/assets/toni.bundle.{bundle_hash}.css")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "public" in cc and "immutable" in cc

    # 3. Missing file (404) must NEVER have immutable cache headers
    resp = api_client.get("/static/assets/toni.bundle.00000000.css")
    assert resp.status_code == 404
    assert "immutable" not in (resp.headers.get("cache-control") or "")

    # 4. Unhashed mutable asset
    resp = api_client.get("/static/assets/toni.bundle.css")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "no-cache" in cc
    assert "immutable" not in cc

    # 5. HTML responses must be strictly revalidated / no-cache
    resp_root = api_client.get("/")
    assert resp_root.status_code == 200
    assert "no-store" in resp_root.headers.get("cache-control", "")

    resp_static = api_client.get("/static/index.html")
    assert resp_static.status_code == 200
    assert "no-store" in resp_static.headers.get("cache-control", "")


def test_assets_mount_isolation(api_client):
    """Verify /assets mounts directly to static/assets and cannot serve non-assets."""
    resp = api_client.get("/assets/index.html")
    assert resp.status_code == 404, "/assets mount must only serve static/assets, not root static files"


def test_versioning_idempotency():
    """Verify two consecutive runs produce identical filenames and unchanged HTML."""
    html_before = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    hashes1 = version_assets()
    html_after1 = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    hashes2 = version_assets()
    html_after2 = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert hashes1 == hashes2
    assert html_after1 == html_before
    assert html_after2 == html_after1


def test_versioning_mutation_in_temporary_fixture():
    """
    Run asset mutation test in a temporary fixture to ensure that changed content
    updates every relevant reference (including templates and fallbacks), while
    cleaning up only owned obsolete hashes and never touching unowned files.
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        tmp_static = tmp_dir / "static"
        tmp_assets = tmp_static / "assets"
        tmp_assets.mkdir(parents=True, exist_ok=True)

        for f in (STATIC_DIR / "assets").iterdir():
            if f.is_file():
                shutil.copy2(f, tmp_assets / f.name)
        shutil.copy2(STATIC_DIR / "index.html", tmp_static / "index.html")

        # Create an unowned custom file in assets that must NOT be deleted
        unowned_file = tmp_assets / "my_custom_user_icon.12345678.svg"
        unowned_file.write_text("<svg></svg>", encoding="utf-8")

        # Run versioning initially
        h1 = version_assets(repo_root=tmp_dir)

        # Mutate an owned asset (e.g. toni.bundle.css)
        bundle_file = tmp_assets / "toni.bundle.css"
        bundle_file.write_text(bundle_file.read_text(encoding="utf-8") + "\n/* mutated */", encoding="utf-8")

        # Run versioning again on fixture
        h2 = version_assets(repo_root=tmp_dir)
        assert h2["toni.bundle.css"] != h1["toni.bundle.css"], "Hash must change on mutated content"

        # Verify old hashed bundle was cleaned up, new hashed bundle was created
        old_versioned = tmp_assets / f"toni.bundle.{h1['toni.bundle.css']}.css"
        new_versioned = tmp_assets / f"toni.bundle.{h2['toni.bundle.css']}.css"
        assert not old_versioned.exists(), "Obsolete hashed file must be removed"
        assert new_versioned.exists(), "New hashed file must be created"

        # Verify unowned file was NOT touched
        assert unowned_file.exists(), "Unowned files must never be removed by cleanup"

        # Verify all references in HTML were updated to new hash
        html_content = (tmp_static / "index.html").read_text(encoding="utf-8")
        assert f"toni.bundle.{h2['toni.bundle.css']}.css" in html_content
        assert f"toni.bundle.{h1['toni.bundle.css']}.css" not in html_content


def test_dockerignore_rules_and_packaging_manifest():
    """
    Verify packaging rules:
    - node_modules and build tooling excluded
    - png files excluded except whitelisted apple-touch-icon
    - licenses included
    """
    repo_root = Path(__file__).resolve().parent.parent
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8")
    lines = [line.strip() for line in dockerignore.splitlines() if line.strip() and not line.startswith("#")]

    assert "node_modules/" in lines
    assert "package.json" in lines
    assert "tailwind.config.js" in lines
    assert "static/assets/*.png" in lines
    assert "!static/assets/TONI_Apple_Touch_Icon_180px_Deep_Ink*.png" in lines

    # License check
    assert (repo_root / "licenses" / "Newsreader-OFL.txt").exists()
    assert (repo_root / "static" / "licenses" / "Newsreader-OFL.txt").exists()
