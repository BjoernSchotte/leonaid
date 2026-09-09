# Sourced only by compatible leaves launched by shared_stack.py/the survey gate.
# The leaf owns its proof directory; the parent alone owns Docker resources.
[ -n "${LEONAID_TEST_STACK_TOKEN:-}" ] || { echo 'Missing shared fixture owner token' >&2; exit 1; }
. "$LEONAID_TEST_STACK/context.env"
[ "$shared_root" = "$root" ] && [ "$shared_token" = "$LEONAID_TEST_STACK_TOKEN" ] || {
  echo 'Shared fixture belongs to a different invocation' >&2; exit 1;
}
# Share the same atomic lease as the parent's reset operation. Never wait and
# silently attach to a fixture whose test data may have changed in the meantime.
mkdir "$LEONAID_TEST_STACK/in-use" || {
  echo 'Shared fixture is already in use; refusing concurrent test/reset' >&2; exit 1;
}
shared_leaf_owned=true
owned=false
compose() {
  LEONAID_HTTP_PORT=8080 LEONAID_HTTPS_PORT=8443 \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose --project-name "$project" --env-file "$root/.env.local" \
      --file "$root/infra/compose/compose.yml" \
      --file "$LEONAID_TEST_STACK/compose.yml" \
      --file "$root/tools/testing/shared-runtime.yml" \
      --file "$LEONAID_TEST_STACK/services.yml" --profile dev-mail "$@"
}
if [ -f "$LEONAID_TEST_STACK/integration.env" ]; then
  cp "$LEONAID_TEST_STACK/integration.env" "$proof/integration.env"
  chmod 600 "$proof/integration.env"
fi
if [ -d "$LEONAID_TEST_STACK/pdfs" ]; then
  cp -R "$LEONAID_TEST_STACK/pdfs" "$proof/${shared_pdf_directory:-pdfs}"
fi
# Intentional splitting of the fixed service list from each leaf.
# shellcheck disable=SC2086
compose up --no-build --detach --wait --wait-timeout 420 $shared_services
