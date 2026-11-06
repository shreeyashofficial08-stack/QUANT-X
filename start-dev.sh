#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_PORT="${PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
VITE_API_PORT="${BACKEND_PORT}"

if [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  VITE_API_URL="https://${CODESPACE_NAME}-${BACKEND_PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
else
  VITE_API_URL="http://127.0.0.1:${BACKEND_PORT}"
fi

export VITE_API_PORT
export VITE_API_URL

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [ -n "${BACKEND_PID}" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "${FRONTEND_PID}" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT

if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "Backend already running on http://127.0.0.1:${BACKEND_PORT}"
else
  cd "$BACKEND_DIR"
  . venv/bin/activate
  PORT="$BACKEND_PORT" uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
  BACKEND_PID=$!
  echo "Backend started at http://127.0.0.1:${BACKEND_PORT}"
fi

if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
  echo "Frontend already running on http://127.0.0.1:${FRONTEND_PORT}"
else
  cd "$FRONTEND_DIR"
  VITE_API_URL="$VITE_API_URL" VITE_API_PORT="$BACKEND_PORT" npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" &
  FRONTEND_PID=$!
  echo "Frontend started at http://127.0.0.1:${FRONTEND_PORT}"
fi

if [ -n "$BACKEND_PID" ] || [ -n "$FRONTEND_PID" ]; then
  echo "Press Ctrl+C to stop the services started by this script."
  if [ -n "$BACKEND_PID" ]; then
    wait "$BACKEND_PID"
  fi
  if [ -n "$FRONTEND_PID" ]; then
    wait "$FRONTEND_PID"
  fi
else
  echo "Both services are already running. Exiting without restarting them."
fi
