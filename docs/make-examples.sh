#!/usr/bin/env sh
# Regenerate docs/example-stamp.svg, docs/example-stamp-no-preview.svg and
# docs/example-sheet.svg from live public pages.
#
#   sh docs/make-examples.sh          # PYTHON=... to pick an interpreter
#
# Uses a throwaway album so your own ~/.stamp is untouched. Pillow should be
# installed (pip install 'stamp-philately[preview]') so previews are shrunk.
set -eu

PYTHON="${PYTHON:-python3}"

cd "$(dirname "$0")/.."
export STAMP_HOME="$(mktemp -d)"
trap 'rm -rf "$STAMP_HOME"' EXIT

# Eight pages that show the range: pictures and descriptions from Open Graph
# tags, a first-paragraph fallback (Wikipedia), and a page that offers
# nothing at all (the RFC), which gets the empty slot.
for url in \
    https://peps.python.org/pep-0020/ \
    https://en.wikipedia.org/wiki/Penny_Black \
    https://www.gutenberg.org/ebooks/1342 \
    https://developer.mozilla.org/en-US/docs/Web/SVG \
    https://www.rfc-editor.org/rfc/rfc2549.html \
    https://en.wikipedia.org/wiki/Postage_stamp \
    https://www.nasa.gov/ \
    https://www.npr.org/
do
    "$PYTHON" -m stamp add "$url"
done

"$PYTHON" -m stamp sheet --out "$STAMP_HOME/sheet.svg" --title "Stamp album · sheet of eight"
cp "$STAMP_HOME/sheet.svg" docs/example-sheet.svg  # the print-ready sheet.html is not kept; it duplicates the SVG

# The path of the stamp whose list line matches a pattern.
svg_of() { "$PYTHON" -m stamp show "$("$PYTHON" -m stamp list | grep -F "$1" | head -n1 | awk '{print $2}')" | awk '/^stamp /{print $2}'; }
cp "$(svg_of 'PEP 20')" docs/example-stamp.svg
cp "$(svg_of 'rfc2549')" docs/example-stamp-no-preview.svg

ls -l docs/example-*.svg
