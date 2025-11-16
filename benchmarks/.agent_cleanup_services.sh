#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root so it can manage installed services." >&2
  exit 1
fi

PG_VERSION="16"
CLUSTER_NAME="agent-benchmarks"
VALKEY_PORT="16379"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.agent_state"
VALKEY_CONF="$STATE_DIR/valkey.conf"
VALKEY_PID="$STATE_DIR/valkey.pid"

if pg_lsclusters | awk -v ver="$PG_VERSION" -v name="$CLUSTER_NAME" '$1 == ver && $2 == name { found=1 } END { exit(found ? 0 : 1) }'; then
  pg_ctlcluster "$PG_VERSION" "$CLUSTER_NAME" stop || true
  pg_dropcluster --stop "$PG_VERSION" "$CLUSTER_NAME"
fi

if [[ -f "$VALKEY_PID" ]]; then
  if kill -0 "$(cat "$VALKEY_PID")" >/dev/null 2>&1; then
    if command -v valkey-cli >/dev/null 2>&1; then
      valkey-cli -p "$VALKEY_PORT" shutdown || kill "$(cat "$VALKEY_PID")" || true
    else
      kill "$(cat "$VALKEY_PID")" || true
    fi
  fi
  rm -f "$VALKEY_PID"
fi

rm -f "$VALKEY_CONF"
rm -rf "$STATE_DIR"

echo "Cleaned up PostgreSQL cluster '${CLUSTER_NAME}' and valkey-server resources."
