#!/usr/bin/env bash
# Standard build entrypoint — use this instead of a bare `docker compose build`.
#
# Bakes the current commit into the image (readable at runtime via GET /health)
# and tags the result with the VERSION file's version, not just `latest`, so a
# stale image is always visible/pinnable instead of silently drifting behind
# the code on disk (see CLAUDE.md: forgerouter:latest went stale for over a
# week — nothing pointed it out until a cron job built against it failed).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="$(cat VERSION)"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

docker compose build --build-arg "GIT_SHA=${GIT_SHA}" --build-arg "BUILD_DATE=${BUILD_DATE}"

# docker compose names the built image <project>-<service>:latest — retag it
# under the plain `forgerouter` repo (what every documented `docker run`
# command in CLAUDE.md and the cron scripts expect) with both a pinned
# version tag and `latest`.
docker tag forgerouter-forgerouter:latest "forgerouter:${VERSION}"
docker tag forgerouter-forgerouter:latest forgerouter:latest

echo "Built forgerouter:${VERSION} (latest) @ ${GIT_SHA}"
