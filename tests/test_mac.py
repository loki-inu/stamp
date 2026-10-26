"""The Mac app bundle: plist, icon, and the build script."""

import plistlib
import subprocess
from pathlib import Path

from stamp import __version__

ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "macos"


def test_plist_matches_the_package_version():
    info = plistlib.loads((MACOS / "Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == __version__
    assert info["CFBundleVersion"] == __version__
    assert info["CFBundleIdentifier"] == "com.loki-inu.stamp"
    assert info["CFBundleExecutable"] == "Stamp"
    assert info["CFBundleIconFile"] == "Stamp"
    assert info["NSHighResolutionCapable"] is True
    assert "127.0.0.1" in info["NSAppTransportSecurity"]["NSExceptionDomains"]


def test_sources_present():
    swift = (MACOS / "StampMain.swift").read_text(encoding="utf-8")
    assert "WKWebView" in swift and "stamp.gui" in swift
    assert "STAMP_PYTHON" in swift
    script = (MACOS / "stamp-browser.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/bash")
    assert (MACOS / "Stamp.icns").stat().st_size > 1000


def test_build_app_bundles_the_package(tmp_path):
    out = tmp_path / "Stamp.app"
    subprocess.run(["sh", str(MACOS / "build-app.sh"), str(out)], check=True, cwd=ROOT)
    assert (out / "Contents/Info.plist").is_file()
    assert (out / "Contents/Resources/Stamp.icns").is_file()
    assert (out / "Contents/Resources/stamp/gui/static/index.html").is_file()
    assert (out / "Contents/MacOS/Stamp").is_file()
    assert (out / "Contents/PkgInfo").read_bytes() == b"APPL????"
    # No compiler here, so the executable is the browser launcher.
    text = (out / "Contents/MacOS/Stamp").read_text(encoding="utf-8")
    assert "stamp.gui" in text
    assert "__pycache__" not in "".join(
        p.name for p in (out / "Contents/Resources/stamp").rglob("*")
    )
