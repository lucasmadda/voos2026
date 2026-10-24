#!/usr/bin/env bash
# Prepara o ambiente local: venv Python com deps pinadas e dependências Node.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e '.[dev]'
npm install --no-fund --no-audit
echo "ok: .venv e node_modules prontos. Rode: npm run dev"
