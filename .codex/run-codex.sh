#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
# shellcheck source=/dev/null
source "$PROJECT_ROOT/.env.ai"
set +a

: "${AI_BASE_URL:?AI_BASE_URL must be set in .env.ai}"
: "${AI_API_KEY:?AI_API_KEY must be set in .env.ai}"
: "${AI_MODEL:?AI_MODEL must be set in .env.ai}"

export OPENAI_BASE_URL="$AI_BASE_URL"
export OPENAI_API_KEY="$AI_API_KEY"
export OPENAI_MODEL="$AI_MODEL"

exec codex "$@"
