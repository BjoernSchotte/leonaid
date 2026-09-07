#!/bin/sh
# Sourced by the restore operator after pg_restore and before any app startup.
# The caller supplies root and compose(), with its exact target overlays/env.
apply_survey_erasure_gate() (
  set -eu
  schema=$(compose exec -T core-postgres psql \
    --username "${CORE_POSTGRES_USER:-leonaid}" \
    --dbname "${CORE_POSTGRES_DB:-leonaid}" --no-psqlrc --tuples-only --no-align \
    --set ON_ERROR_STOP=1 \
    --command "SELECT to_regclass('public.survey') IS NOT NULL OR to_regclass('public.survey_deletion') IS NOT NULL OR to_regclass('public.survey_recovery_identity') IS NOT NULL")
  checkpoint=${LEONAID_SURVEY_ERASURE_CHECKPOINT:-}
  cutoff=${LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH:-}
  case "$schema" in
    f)
      # Legacy databases without the module need no module-specific command.
      # An explicitly supplied checkpoint must never be silently discarded.
      if [ -z "$checkpoint" ] && [ -z "$cutoff" ]; then
        echo 'restore: survey module absent; survey erasure gate not applicable'
        exit 0
      fi
      ;;
    t) ;;
    *) echo 'restore: BLOCKED: cannot identify survey schema' >&2; exit 1 ;;
  esac
  if [ -z "$checkpoint" ] || [ ! -f "$checkpoint" ] || [ -z "$cutoff" ]; then
    echo 'restore: BLOCKED: survey recovery requires an independent erasure checkpoint and required-through cutoff; application services remain stopped' >&2
    exit 1
  fi
  checkpoint=$(cd "$(dirname "$checkpoint")" && pwd)/$(basename "$checkpoint")
  # Never build a replacement for the release-pinned image in no-build restores.
  if [ "${LEONAID_RESTORE_NO_BUILD:-false}" = true ]; then
    compose pull --policy missing api || exit 1
  else
    compose build api || exit 1
  fi
  compose run --rm --no-deps \
    --volume "$root:/repo:ro" \
    --volume "$checkpoint:/run/survey-recovery/checkpoint.json:ro" \
    --workdir /repo --entrypoint python api tools/surveys/recovery.py reapply \
    --checkpoint /run/survey-recovery/checkpoint.json --required-through "$cutoff"
)
