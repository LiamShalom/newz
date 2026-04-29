#!/bin/sh
# Phase 9 (D-13): Railway preDeployCommand entrypoint for `alembic upgrade head`.
# Lives in backend/scripts/ so it ships inside the Dockerfile's /app/backend/
# tree. Wrapped in a script (rather than inline in railway.toml) so we can
# surface diagnostics and merge stderr -> stdout reliably.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[migrate] cwd-before=$(pwd)"
cd "${BACKEND_DIR}"
echo "[migrate] cwd-after=$(pwd)"
echo "[migrate] DATABASE_URL_set=$([ -n "${DATABASE_URL}" ] && echo yes || echo no)"
echo "[migrate] METADATA_BACKEND=${METADATA_BACKEND:-unset}"
echo "[migrate] python=$(command -v python || echo missing) alembic=$(command -v alembic || echo missing)"
echo "[migrate] alembic-version=$(alembic --version 2>&1 || true)"
echo "[migrate] running: alembic upgrade head"

# Merge stderr into stdout so Railway's pre-deploy log captures everything.
exec alembic upgrade head 2>&1
