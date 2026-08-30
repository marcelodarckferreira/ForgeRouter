#!/usr/bin/env bash
# Subscription CLI keepalive script
#
# Keeps OAuth tokens and session credentials fresh for:
# 1. OpenAI Codex (~/.codex/auth.json)
# 2. Claude Code (~/.claude/.credentials.json)
# 3. Google Antigravity (~/.gemini/antigravity-cli/)
#
# Runs on the HOST machine where the CLI tools and keyrings reside.
# Designed to be invoked periodically via cron with flock protection.

set -uo pipefail

LOG_TAG="[subscription-keepalive]"
TIMESTAMP="$(date -u '+%Y-%m-%d %H:%M:%SZ')"

echo "${TIMESTAMP} ${LOG_TAG} Starting subscription credentials refresh..."

# Ensure PATH has npm global, local bin, and cargo bin
export PATH="/root/.npm-global/bin:/root/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

# 1. OpenAI Codex
if command -v codex >/dev/null 2>&1; then
    echo "${TIMESTAMP} ${LOG_TAG} Refreshing OpenAI Codex..."
    if timeout 20 codex doctor --summary >/dev/null 2>&1; then
        echo "${TIMESTAMP} ${LOG_TAG} Codex: OK"
    else
        echo "${TIMESTAMP} ${LOG_TAG} Codex: check finished"
    fi
else
    echo "${TIMESTAMP} ${LOG_TAG} codex binary not found in PATH, skipping."
fi

# 2. Claude Code
if command -v claude >/dev/null 2>&1; then
    echo "${TIMESTAMP} ${LOG_TAG} Refreshing Claude Code..."
    if timeout 25 claude -p "ping" --dangerously-skip-permissions >/dev/null 2>&1; then
        echo "${TIMESTAMP} ${LOG_TAG} Claude Code: OK"
    else
        echo "${TIMESTAMP} ${LOG_TAG} Claude Code: check finished"
    fi
else
    echo "${TIMESTAMP} ${LOG_TAG} claude binary not found in PATH, skipping."
fi

# 3. Google Antigravity (agy)
if command -v agy >/dev/null 2>&1; then
    echo "${TIMESTAMP} ${LOG_TAG} Refreshing Google Antigravity (agy)..."
    if timeout 20 agy models >/dev/null 2>&1; then
        echo "${TIMESTAMP} ${LOG_TAG} Antigravity (agy): OK"
    else
        echo "${TIMESTAMP} ${LOG_TAG} Antigravity (agy): check finished"
    fi
else
    echo "${TIMESTAMP} ${LOG_TAG} agy binary not found in PATH, skipping."
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%SZ') ${LOG_TAG} Refresh cycle completed."
