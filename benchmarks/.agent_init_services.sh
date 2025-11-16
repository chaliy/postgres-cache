#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root so it can install packages and manage services." >&2
  exit 1
fi

PG_VERSION="16"
CLUSTER_NAME="agent-benchmarks"
PG_PORT="15432"
PG_USER="cache_user"
PG_PASSWORD="cache_pass"
PG_DB="cache_proto"
VALKEY_PORT="16379"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/.agent_state"
VALKEY_CONF="$STATE_DIR/valkey.conf"
VALKEY_PID="$STATE_DIR/valkey.pid"
mkdir -p "$STATE_DIR"

need_update=0
ensure_package() {
  local package="$1"
  if ! dpkg -s "$package" >/dev/null 2>&1; then
    if [[ $need_update -eq 0 ]]; then
      apt-get update
      need_update=1
    fi
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$package"
  fi
}

ensure_package "postgresql-${PG_VERSION}"
ensure_package "postgresql-common"
ensure_package "valkey-server"

if ! pg_lsclusters | awk -v ver="$PG_VERSION" -v name="$CLUSTER_NAME" '$1 == ver && $2 == name { found=1 } END { exit(found ? 0 : 1) }'; then
  pg_createcluster "$PG_VERSION" "$CLUSTER_NAME" --port "$PG_PORT"
fi

pg_ctlcluster "$PG_VERSION" "$CLUSTER_NAME" start

sudo -u postgres psql -p "$PG_PORT" <<SQL
DO
$$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${PG_USER}') THEN
    CREATE ROLE ${PG_USER} LOGIN PASSWORD '${PG_PASSWORD}';
  ELSE
    ALTER ROLE ${PG_USER} LOGIN PASSWORD '${PG_PASSWORD}';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${PG_DB}') THEN
    CREATE DATABASE ${PG_DB} OWNER ${PG_USER};
  END IF;
END
$$;
SQL

if [[ ! -f "$VALKEY_CONF" ]]; then
  cat > "$VALKEY_CONF" <<CONF
port ${VALKEY_PORT}
dbfilename ""
save ""
appendonly no
pidfile ${VALKEY_PID}
CONF
fi

if [[ -f "$VALKEY_PID" ]] && kill -0 "$(cat "$VALKEY_PID")" >/dev/null 2>&1; then
  echo "valkey-server already running with PID $(cat "$VALKEY_PID") on port ${VALKEY_PORT}."
else
  valkey-server "$VALKEY_CONF"
fi

echo "PostgreSQL ${PG_VERSION} cluster '${CLUSTER_NAME}' is running on port ${PG_PORT}."
echo "valkey-server is running on port ${VALKEY_PORT}."
