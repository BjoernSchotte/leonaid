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
proof_fixture=$(mktemp -d)
mapping_fixture=$(mktemp -d)
trap 'rm -rf "$duplicate_fixture" "$unknown_fixture" "$proof_fixture" "$mapping_fixture"' EXIT

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

for fixture_root in "$proof_fixture" "$mapping_fixture"; do
  mkdir -p "$fixture_root/specs/leonaid-poc"
  cp "$source_root/specs/leonaid-poc/PLAN.md" "$fixture_root/specs/leonaid-poc/PLAN.md"
  cp "$source_root/specs/leonaid-poc/requirements.tsv" "$fixture_root/specs/leonaid-poc/requirements.tsv"
  cp "$source_root/specs/produkt-und-architekturvorschlag.md" "$fixture_root/specs/produkt-und-architekturvorschlag.md"
  cp -R "$source_root/specs/leonaid-poc/proofs" "$fixture_root/specs/leonaid-poc/proofs"
done

sed -i.bak '/^| POC-GATE-023 |/d' \
  "$proof_fixture/specs/leonaid-poc/proofs/POC-122.md"
rm "$proof_fixture/specs/leonaid-poc/proofs/POC-122.md.bak"
run_fixture "$proof_fixture" "hard-gate proof table and requirements.tsv differ"

sed -i.bak \
  's/| POC-GATE-014 | POC-092 |/| POC-GATE-014 | POC-094 |/' \
  "$mapping_fixture/specs/leonaid-poc/proofs/POC-122.md"
rm "$mapping_fixture/specs/leonaid-poc/proofs/POC-122.md.bak"
run_fixture "$mapping_fixture" "proof tasks differ for POC-GATE-014"

echo "traceability-test: OK: positive and four traceability-drift cases passed"
