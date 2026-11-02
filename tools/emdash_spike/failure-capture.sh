# Sourced by EmDash spike harnesses; expects $root, $project and compose().
# On a failed CI run, record the overlay-complete Compose state of the current
# project as sanitized evidence. Proof directories hold live session tokens and
# are never copied. Local runs (no LEONAID_CI_ARTIFACT_DIR) are unaffected.
emdash_capture_failure() {
  artifact_directory=${LEONAID_CI_ARTIFACT_DIR:-}
  if [ -z "$artifact_directory" ]; then
    return 0
  fi
  case "$artifact_directory" in
    /*) ;;
    *) artifact_directory="$root/$artifact_directory" ;;
  esac
  destination="$artifact_directory/runtime-$project"
  mkdir -p "$destination"
  compose ps --all >"$destination/services.txt" 2>&1 || true
  compose logs --no-color --timestamps >"$destination/compose.log" 2>&1 || true
  # Per-run credentials are not in .env.local; redact them explicitly.
  capture_secrets=$(mktemp -d)
  {
    printf 'LEONAID_ORDER_SUBMISSION_KEY=%s\n' "${LEONAID_ORDER_SUBMISSION_KEY:-}"
    printf 'TWENTY_INTEGRATION_API_KEY=%s\n' "${TWENTY_INTEGRATION_API_KEY:-}"
  } >"$capture_secrets/run.env"
  if ! docker run --rm --network none --user "$(id -u):$(id -g)" \
    --volume "$root:/workspace:ro" \
    --volume "$capture_secrets:/secrets:ro" \
    --volume "$destination:/ci" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/ci/sanitize_artifacts.py \
    /ci /workspace/.env.local --env-directory /secrets \
    >"$capture_secrets/sanitize.log" 2>&1; then
    find "$destination" -type f -delete
    {
      printf '%s\n' "Artifacts discarded for safety: redaction check failed."
      # The checker names only the rejected file and rule, never its content.
      grep '^ci-artifact-sanitize: BLOCKED:' "$capture_secrets/sanitize.log" || true
    } >"$destination/SANITIZATION-FAILED.txt"
  fi
  rm -f "$capture_secrets/run.env" "$capture_secrets/sanitize.log"
  rmdir "$capture_secrets"
  echo "emdash-spike: failure evidence for $project recorded in $destination" >&2
}
