#!/usr/bin/env bash
# Compila el módulo TypeScript del Mendix Model SDK bridge.
set -euo pipefail
cd "$(dirname "$0")/../mendix_sdk"
npm run build
echo "[mendex] SDK bridge compilado en mendix_sdk/dist/"
