#!/usr/bin/env bash
# Generic, self-contained installer — brings up ForgeRouter with its own
# bundled PostgreSQL, no dependency on any pre-existing Docker network or
# externally-managed database. See INSTALL.md for the manual step-by-step
# this automates, and for what it deliberately leaves out (the Hermes
# ecosystem's systemd-based agent key-rotation feature).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE=(docker compose -f docker-compose.standalone.yml)

command -v docker >/dev/null || { echo "docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose (v2) is required." >&2; exit 1; }

if [ ! -f .env ]; then
  echo "No .env found — creating one from .env.example."
  cp .env.example .env
fi

random_secret() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }

# Fill in a real admin password: .env.example ships a placeholder that must
# never actually be used to run a real database.
if ! grep -q '^POSTGRES_PASSWORD=' .env || grep -qE '^POSTGRES_PASSWORD=(change_me)?$' .env; then
  generated="$(random_secret)"
  if grep -q '^POSTGRES_PASSWORD=' .env; then
    sed -i.bak "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=${generated}#" .env && rm -f .env.bak
  else
    echo "POSTGRES_PASSWORD=${generated}" >> .env
  fi
  echo "Generated a random POSTGRES_PASSWORD in .env."
fi

# proxyrouter_user is the restricted app role db/*.sql grants everything to
# (db/001_initial.sql: CREATE SCHEMA ai_router AUTHORIZATION proxyrouter_user)
# — ForgeRouter connects as this role, never as the Postgres admin above.
if ! grep -q '^PROXYROUTER_PASSWORD=' .env || grep -qE '^PROXYROUTER_PASSWORD=$' .env; then
  generated="$(random_secret)"
  if grep -q '^PROXYROUTER_PASSWORD=' .env; then
    sed -i.bak "s#^PROXYROUTER_PASSWORD=.*#PROXYROUTER_PASSWORD=${generated}#" .env && rm -f .env.bak
  else
    echo "PROXYROUTER_PASSWORD=${generated}" >> .env
  fi
  echo "Generated a random PROXYROUTER_PASSWORD in .env."
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

echo "Starting PostgreSQL..."
"${COMPOSE[@]}" up -d postgres

echo "Waiting for PostgreSQL to be ready..."
until "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-forgerouter_user}" -d "${POSTGRES_DB:-forgerouter}" >/dev/null 2>&1; do
  sleep 1
done

psql_admin() {
  "${COMPOSE[@]}" exec -T postgres psql -U "${POSTGRES_USER:-forgerouter_user}" -d "${POSTGRES_DB:-forgerouter}" -v ON_ERROR_STOP=1 "$@"
}

echo "Creating the proxyrouter_user app role (idempotent)..."
psql_admin -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'proxyrouter_user') THEN
    CREATE ROLE proxyrouter_user LOGIN PASSWORD '${PROXYROUTER_PASSWORD}';
  ELSE
    ALTER ROLE proxyrouter_user WITH PASSWORD '${PROXYROUTER_PASSWORD}';
  END IF;
END
\$\$;
"

echo "Applying database schema..."
for f in db/*.sql; do
  echo "  $f"
  psql_admin < "$f"
done

echo "Building the ForgeRouter image..."
./scripts/build.sh

echo "Starting ForgeRouter..."
"${COMPOSE[@]}" up -d forgerouter

echo
echo "Waiting for the service to come up..."
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:2100/health >/dev/null 2>&1; then
    echo "ForgeRouter is up: http://127.0.0.1:2100"
    echo "Dashboard login: admin / admin (you'll be asked to change it on first sign-in)."
    exit 0
  fi
  sleep 1
done

echo "ForgeRouter didn't come up within 30s — check the logs:" >&2
echo "  ${COMPOSE[*]} logs forgerouter" >&2
exit 1
