#!/usr/bin/env python3
"""
Deterministic asset versioning utility for TONI.
Calculates 8-character SHA-256 hashes for owned runtime static assets,
creates content-hashed copies alongside the canonical unhashed files,
removes obsolete previous hashes owned by this process,
and safely updates references and fallback URLs in static/index.html.
"""

import hashlib
import re
import sys
from pathlib import Path

OWNED_ASSETS = [
    "toni.bundle.css",
    "TONI_Design_Tokens.css",
    "TONI_Mark_Aperture_Notch_Primary.svg",
    "TONI_Favicon_16px_Deep_Ink.svg",
    "TONI_Favicon.ico",
    "TONI_Apple_Touch_Icon_180px_Deep_Ink.png",
]

def compute_file_hash(path: Path) -> str:
    """Compute 8-character SHA-256 hash of file content."""
    sha = hashlib.sha256()
    data = path.read_bytes()
    if path.suffix.lower() in (".css", ".svg", ".json", ".html", ".txt", ".js"):
        data = data.replace(b"\r\n", b"\n")
    sha.update(data)
    return sha.hexdigest()[:8]

def version_assets(repo_root: Path = None) -> dict[str, str]:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    assets_dir = repo_root / "static" / "assets"
    index_html = repo_root / "static" / "index.html"

    if not assets_dir.exists():
        raise FileNotFoundError(f"Assets directory not found: {assets_dir}")
    if not index_html.exists():
        raise FileNotFoundError(f"index.html not found: {index_html}")

    asset_hashes = {}

    for filename in OWNED_ASSETS:
        canonical_file = assets_dir / filename
        if not canonical_file.exists():
            print(f"Warning: canonical asset {filename} not found at {canonical_file}", file=sys.stderr)
            continue

        h = compute_file_hash(canonical_file)
        asset_hashes[filename] = h
        stem, ext = filename.rsplit(".", 1)
        versioned_filename = f"{stem}.{h}.{ext}"
        versioned_file = assets_dir / versioned_filename

        # Write or touch versioned file with exact identical bytes
        content = canonical_file.read_bytes()
        if canonical_file.suffix.lower() in (".css", ".svg", ".json", ".html", ".txt", ".js"):
            content = content.replace(b"\r\n", b"\n")
        if not versioned_file.exists() or versioned_file.read_bytes() != content:
            versioned_file.write_bytes(content)

        # Cleanup obsolete hashes owned strictly by this process
        hash_pattern = re.compile(rf"^{re.escape(stem)}\.([a-f0-9]{{8}})\.{re.escape(ext)}$")
        for existing in assets_dir.iterdir():
            if existing.name == versioned_filename or existing.name == filename:
                continue
            m = hash_pattern.match(existing.name)
            if m and m.group(1) != h:
                try:
                    existing.unlink()
                except OSError as e:
                    print(f"Warning: could not unlink {existing}: {e}", file=sys.stderr)

    # Update static/index.html
    html_content = index_html.read_text(encoding="utf-8")
    original_content = html_content

    for filename, h in asset_hashes.items():
        stem, ext = filename.rsplit(".", 1)
        versioned_name = f"{stem}.{h}.{ext}"

        # 1. Primary static/assets/... references (with optional existing hash)
        pattern_primary = re.compile(
            rf'(static/assets/{re.escape(stem)})(?:\.[a-f0-9]{{8}})?(\.{re.escape(ext)})'
        )
        html_content = pattern_primary.sub(f"static/assets/{versioned_name}", html_content)

        # 2. Fallback assets/... references in onerror / event handlers
        pattern_fallback = re.compile(
            rf'([\'"]assets/{re.escape(stem)})(?:\.[a-f0-9]{{8}})?(\.{re.escape(ext)}[\'"])'
        )
        def replace_fallback(match):
            q1 = match.group(1)[0]
            q2 = match.group(2)[-1]
            return f"{q1}assets/{versioned_name}{q2}"
        html_content = pattern_fallback.sub(replace_fallback, html_content)

    if html_content != original_content:
        index_html.write_text(html_content, encoding="utf-8")
        print("Updated static/index.html with current asset versions.")
    else:
        print("static/index.html references already match current asset versions.")

    return asset_hashes

if __name__ == "__main__":
    hashes = version_assets()
    print("Asset versioning complete:")
    for fn, h in hashes.items():
        print(f"  {fn} -> {h}")
