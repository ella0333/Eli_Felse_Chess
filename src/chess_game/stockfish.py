"""Finding Stockfish, and downloading the official build when it is missing.

Stockfish is GPLv3 and is not shipped in this repo. The setup scripts fetch
the latest release from github.com/official-stockfish/Stockfish into
`stockfish/` next to the module, or use one already installed on the system.
"""

from __future__ import annotations

import io
import json
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent
STOCKFISH_DIR = MODULE_ROOT / "stockfish"
RELEASES_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"


def _platform_tag() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _arch_tags() -> tuple[str, ...]:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return ("arm64",)
    return ("x86-64", "x86_64")


def find_stockfish() -> str | None:
    """The Stockfish binary: a system install on Mac/Linux, else the bundled folder."""
    if os.name != "nt":
        system_sf = shutil.which("stockfish")
        if system_sf:
            return system_sf
    if not STOCKFISH_DIR.is_dir():
        return None
    for root, _dirs, files in os.walk(STOCKFISH_DIR):
        for f in files:
            name_lower = f.lower()
            if not name_lower.startswith("stockfish"):
                continue
            path = os.path.join(root, f)
            if name_lower.endswith(".exe") or (os.name != "nt" and "." not in f and os.access(path, os.X_OK)):
                return path
    return None


def download_stockfish() -> str:
    """Download the latest official release for this platform."""
    print("\n  Stockfish not found. Downloading...")
    STOCKFISH_DIR.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "eli-felse-chess"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read().decode())

    platform_tag = _platform_tag()
    arch_tags = _arch_tags()
    archive_url = None
    for asset in release.get("assets", []):
        name = asset["name"].lower()
        if platform_tag not in name or not name.endswith((".zip", ".tar", ".tar.gz")):
            continue
        # The macOS build is universal and names no architecture
        if platform_tag == "macos" or any(tag in name for tag in arch_tags):
            archive_url = asset["browser_download_url"]
            break

    if not archive_url:
        print(f"  ERROR: no {platform_tag} Stockfish build in the latest release.")
        if platform_tag == "linux":
            print("  Try: sudo apt install stockfish")
        elif platform_tag == "macos":
            print("  Try: brew install stockfish")
        else:
            print("  Download Stockfish manually and place it in:")
            print(f"    {STOCKFISH_DIR}")
        sys.exit(1)

    print(f"  Downloading: {archive_url.split('/')[-1]}")
    req = urllib.request.Request(archive_url, headers={"User-Agent": "eli-felse-chess"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = resp.read()
    print(f"  Downloaded {len(data) / 1024 / 1024:.1f} MB")

    if archive_url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(STOCKFISH_DIR)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(STOCKFISH_DIR)

    sf_path = find_stockfish()
    if not sf_path:
        print("  ERROR: extraction completed but the stockfish binary was not found.")
        sys.exit(1)
    print(f"  Stockfish installed: {sf_path}")
    return sf_path


def get_stockfish() -> str:
    """The Stockfish binary path, downloading it first if needed."""
    return find_stockfish() or download_stockfish()
