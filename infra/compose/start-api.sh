#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn leonaid.entrypoints.fastapi.platform:app \
  --host 0.0.0.0 \
  --port 8000 \
  --no-access-log \
  --proxy-headers \
  --forwarded-allow-ips="*"
