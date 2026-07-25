#!/bin/sh
set -eu

source_root=${1:-/workspace}
checker="$source_root/tools/traceability/check.sh"

run_fixture() {
  fixture_root=$1
  expected_message=$2
  output_file=$(mktemp)

  if /bin/sh "$checker" "$fixture_root" >"$output_file" 2>&1; then
    cat "$output_file" >&2
    rm -f "$output_file"
    echo "traceability-test: ERROR: invalid fixture unexpectedly passed" >&2
    exit 1
  fi

  grep -F "$expected_message" "$output_file" >/dev/null || {
    cat "$output_file" >&2
    rm -f "$output_file"
    echo "traceability-test: ERROR: expected diagnostic not found: $expected_message" >&2
    exit 1
  }

  rm -f "$output_file"
}

/bin/sh "$checker" "$source_root"

duplicate_fixture=$(mktemp -d)
unknown_fixture=$(mktemp -d)
trap 'rm -rf "$duplicate_fixture" "$unknown_fixture"' EXIT

mkdir -p "$duplicate_fixture/specs/leonaid-poc"
cp "$source_root/specs/leonaid-poc/PLAN.md" "$duplicate_fixture/specs/leonaid-poc/PLAN.md"
cp "$source_root/specs/leonaid-poc/requirements.tsv" "$duplicate_fixture/specs/leonaid-poc/requirements.tsv"
cp "$source_root/specs/produkt-und-architekturvorschlag.md" "$duplicate_fixture/specs/produkt-und-architekturvorschlag.md"
tail -n 1 "$source_root/specs/leonaid-poc/requirements.tsv" >> "$duplicate_fixture/specs/leonaid-poc/requirements.tsv"
run_fixture "$duplicate_fixture" "duplicate requirement ID"

mkdir -p "$unknown_fixture/specs/leonaid-poc"
cp "$source_root/specs/leonaid-poc/PLAN.md" "$unknown_fixture/specs/leonaid-poc/PLAN.md"
cp "$source_root/specs/produkt-und-architekturvorschlag.md" "$unknown_fixture/specs/produkt-und-architekturvorschlag.md"
sed 's/POC-052,POC-122/POC-052,POC-999/' \
  "$source_root/specs/leonaid-poc/requirements.tsv" \
  > "$unknown_fixture/specs/leonaid-poc/requirements.tsv"
run_fixture "$unknown_fixture" "unknown task referenced by requirements.tsv: POC-999"

echo "traceability-test: OK: positive, duplicate-ID and unknown-task cases passed"
