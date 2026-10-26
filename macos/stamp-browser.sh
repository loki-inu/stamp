#!/bin/bash
# Album in the default browser. build-app.sh uses this only when swiftc
# is not available; with the Xcode command line tools the app gets a real window.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$(cd "$HERE/../Resources" && pwd)"
export PYTHONPATH="$RES${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1

python_ok() {
  [ -x "$1" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

pick_python() {
  if [ -n "${STAMP_PYTHON:-}" ] && python_ok "$STAMP_PYTHON"; then
    printf '%s\n' "$STAMP_PYTHON"
    return
  fi
  local c root
  for c in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3 \
    /usr/bin/python3
  do
    if python_ok "$c"; then
      printf '%s\n' "$c"
      return
    fi
  done
  for root in "$HOME/Library/Frameworks/Python.framework/Versions" /Library/Frameworks/Python.framework/Versions; do
    [ -d "$root" ] || continue
    for c in "$root"/*/bin/python3; do
      if python_ok "$c"; then
        printf '%s\n' "$c"
        return
      fi
    done
  done
  return 1
}

PY="$(pick_python)" || {
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'display alert "Stamp needs Python 3.11 or newer" message "Install it from python.org or with Homebrew (brew install python), then open Stamp again."'
  else
    echo "Stamp needs Python 3.11 or newer." >&2
  fi
  exit 1
}

ENDPOINT="$(mktemp)"
PID=""
cleanup() {
  rm -f "$ENDPOINT"
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$PY" -m stamp.gui --no-open --endpoint-file "$ENDPOINT" &
PID=$!
i=0
while [ "$i" -lt 50 ]; do
  if [ -s "$ENDPOINT" ]; then
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Stamp could not open the album." >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 0.2
done
URL="$(cat "$ENDPOINT")"
if command -v open >/dev/null 2>&1; then
  open "$URL"
else
  printf '%s\n' "$URL"
fi
wait "$PID"
