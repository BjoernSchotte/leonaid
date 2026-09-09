#!/bin/sh
set -eu
python3 tools/dx/generate_secrets.py .env.example .env.local
mkdir -p .artifacts/cache-measurement
start=$(date +%s)
if [ "$CACHE_TARGETS" = proxy ]; then
  set -- proxy
else
  set --
fi
# Unique job-local project tags deliberately differ from Bake tags. The existing
# harnesses must reuse build layers even though their project/image names change.
docker compose --progress plain --project-name leonaid-cache-benchmark \
  --env-file .env.local --file infra/compose/compose.yml build "$@" \
  > "$RUNNER_TEMP/cache-compose.log" 2>&1
elapsed=$(( $(date +%s) - start ))
cat "$RUNNER_TEMP/cache-compose.log"
python3 - "$RUNNER_TEMP/cache-compose.log" "$elapsed" <<'CHECK'
import json
import re
import sys
from pathlib import Path

log = Path(sys.argv[1]).read_text()
runs = set(re.findall(r"^#(\d+) \[.*?\] RUN ", log, re.MULTILINE))
cached = set(re.findall(r"^#(\d+) CACHED", log, re.MULTILINE))
report = {"seconds": int(sys.argv[2]), "runSteps": len(runs), "cachedRunSteps": len(runs & cached)}
Path(".artifacts/cache-measurement/compose.json").write_text(json.dumps(report) + "\n")
assert runs and runs <= cached, f"Compose repeated Dockerfile RUN steps: {sorted(runs - cached)}"
CHECK
if [ "$CACHE_TARGETS" = default ]; then
  sh tools/ci/public-runtime.sh leonaid-cache-public:local
fi
