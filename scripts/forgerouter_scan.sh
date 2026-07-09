#!/usr/bin/env bash
set -euo pipefail

cd /root/.hermes/forgerouter

docker run --rm --network host \
  --env-file /root/.hermes/forgerouter/.env \
  forgerouter:latest \
  python -m app.validation.scanner --persist
