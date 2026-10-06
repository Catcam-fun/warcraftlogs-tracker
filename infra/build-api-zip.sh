#!/bin/bash
# Builds the Lambda code zip for the API: backend/'s tracked files (no tests,
# scripts or migrations) plus its dependencies built for Lambda (Linux x86_64,
# Python 3.12). Usage: infra/build-api-zip.sh [out.zip]   (default: api.zip)
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
out=$(realpath -m "${1:-api.zip}")
pkg=$(mktemp -d)
trap 'rm -rf "$pkg"' EXIT

pip install --quiet --target "$pkg" --platform manylinux2014_x86_64 \
    --python-version 3.12 --implementation cp --only-binary=:all: \
    -r "$root/backend/requirements.txt"
(cd "$root" && git ls-files backend \
    | grep -vE '^backend/(test_[^/]*|tests/.*|scripts/.*|migrations/.*)$' \
    | while read -r f; do mkdir -p "$pkg/$(dirname "${f#backend/}")"; cp "$f" "$pkg/${f#backend/}"; done)
chmod +x "$pkg/run.sh"
find "$pkg" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f "$out"
(cd "$pkg" && zip -qr9 -X "$out" .)
echo "$out: $(du -h "$out" | cut -f1)"
