#!/usr/bin/env sh
# Serve the generated Project Atlas for viewing / showcasing.
#
# Scaffolded into a project as docs/atlas/serve.sh. Resolves the build/
# directory relative to this script, so it works from anywhere.
#
# Usage:
#   sh docs/atlas/serve.sh [PORT]      # default port 8080
#
# The generated pages are self-contained single files, so you can also just
# open docs/atlas/build/index.html directly in a browser (works offline) —
# the server is only needed for relative links between pages to resolve.

PORT="${1:-8080}"
DIR="$(cd "$(dirname "$0")" && pwd)/build"

if [ ! -d "$DIR" ]; then
  echo "No build/ directory at $DIR — run the generator first:" >&2
  echo "  node $(cd "$(dirname "$0")" && pwd)/scripts/build-atlas.mjs" >&2
  exit 1
fi

echo "Serving Project Atlas at http://localhost:$PORT  (Ctrl+C to stop)"
exec python3 -m http.server "$PORT" --directory "$DIR"
