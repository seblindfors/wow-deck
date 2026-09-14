#!/bin/bash
# Build dist/wow-deck.tar.gz (what install.sh downloads). Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")"
ver=$(git describe --tags --always 2>/dev/null || echo dev)
mkdir -p dist
tar --exclude=.git --exclude=tests --exclude=dist --exclude='__pycache__' --exclude='.pytest_cache' \
    --transform "s,^\.,wow-deck-$ver," -czf "dist/wow-deck.tar.gz" .
echo "dist/wow-deck.tar.gz ($ver): $(tar tzf dist/wow-deck.tar.gz | wc -l) files"
