#!/bin/bash
# Один раз после clone: git config core.hooksPath .githooks
# setup.sh тоже вызовет это.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
chmod +x scripts/bump_version.sh .githooks/pre-push 2>/dev/null || true
git config core.hooksPath .githooks
echo "hooksPath = .githooks (VERSION бампается при git push)"
