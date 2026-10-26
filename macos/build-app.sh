#!/bin/sh
# Build dist/Stamp.app. On a Mac with the Xcode command line tools this is a
# native window; without swiftc it opens the same album in the browser.
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
OUT=${1:-"$ROOT/dist/Stamp.app"}

rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"
cp macos/Info.plist "$OUT/Contents/Info.plist"
cp macos/Stamp.icns "$OUT/Contents/Resources/Stamp.icns"
python3 - "$OUT" <<'PY'
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
shutil.copytree(
    Path("stamp"),
    out / "Contents/Resources/stamp",
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
)
PY
printf 'APPL????' > "$OUT/Contents/PkgInfo"

if command -v swiftc >/dev/null 2>&1; then
  swiftc -O -parse-as-library -framework Cocoa -framework WebKit \
    -o "$OUT/Contents/MacOS/Stamp" macos/StampMain.swift
  echo "built $OUT"
else
  cp macos/stamp-browser.sh "$OUT/Contents/MacOS/Stamp"
  chmod +x "$OUT/Contents/MacOS/Stamp"
  echo "built $OUT" >&2
  echo "swiftc was not found, so this build opens the album in the browser. Install the Xcode command line tools and run this again for a native window." >&2
fi
