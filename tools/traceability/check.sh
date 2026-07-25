#!/bin/sh
set -eu

repo_root=${1:-/workspace}
plan="$repo_root/specs/leonaid-poc/PLAN.md"
requirements="$repo_root/specs/leonaid-poc/requirements.tsv"
concept="$repo_root/specs/produkt-und-architekturvorschlag.md"

fail() {
  echo "traceability: ERROR: $*" >&2
  exit 1
}

[ -f "$plan" ] || fail "missing plan: $plan"
[ -f "$requirements" ] || fail "missing requirements: $requirements"
[ -f "$concept" ] || fail "missing product concept: $concept"

tasks_file=$(mktemp)
requirements_tasks=$(mktemp)
concept_gates=$(mktemp)
mapped_gates=$(mktemp)
trap 'rm -f "$tasks_file" "$requirements_tasks" "$concept_gates" "$mapped_gates"' EXIT

sed -n 's/^### \[[ x]\] \(POC-[0-9][0-9][0-9]\) .*/\1/p' "$plan" > "$tasks_file"

[ -s "$tasks_file" ] || fail "no task IDs found in PLAN.md"

duplicate_task=$(sort "$tasks_file" | uniq -d | head -n 1)
[ -z "$duplicate_task" ] || fail "duplicate task ID in plan: $duplicate_task"

header=$(head -n 1 "$requirements")
[ "$header" = "$(printf 'requirement_id\tcategory\tsource\ttasks\ttests')" ] ||
  fail "unexpected requirements.tsv header"

awk -F '\t' '
  NR == 1 { next }
  NF != 5 {
    printf "traceability: ERROR: line %d must have exactly 5 tab-separated columns\n", NR > "/dev/stderr"
    exit 1
  }
  $1 !~ /^POC-(SCOPE|GATE)-[0-9][0-9][0-9]$/ {
    printf "traceability: ERROR: invalid requirement ID on line %d: %s\n", NR, $1 > "/dev/stderr"
    exit 1
  }
  $2 !~ /^(included|excluded|gate)$/ {
    printf "traceability: ERROR: invalid category on line %d: %s\n", NR, $2 > "/dev/stderr"
    exit 1
  }
  $3 == "" || $4 == "" || $5 == "" {
    printf "traceability: ERROR: empty required value on line %d\n", NR > "/dev/stderr"
    exit 1
  }
  seen[$1]++ {
    printf "traceability: ERROR: duplicate requirement ID: %s\n", $1 > "/dev/stderr"
    exit 1
  }
  {
    count[$2]++
    split($4, task_ids, ",")
    for (i in task_ids) print task_ids[i]
  }
  END {
    if (count["included"] == 0 || count["excluded"] == 0 || count["gate"] == 0) {
      print "traceability: ERROR: included, excluded and gate requirements are mandatory" > "/dev/stderr"
      exit 1
    }
  }
' "$requirements" > "$requirements_tasks"

while IFS= read -r referenced_task; do
  grep -qx "$referenced_task" "$tasks_file" ||
    fail "unknown task referenced by requirements.tsv: $referenced_task"
done < "$requirements_tasks"

grep -o 'POC-GATE-[0-9][0-9][0-9]' "$concept" | sort > "$concept_gates"
awk -F '\t' 'NR > 1 && $2 == "gate" { print $1 }' "$requirements" | sort > "$mapped_gates"

duplicate_concept_gate=$(uniq -d "$concept_gates" | head -n 1)
[ -z "$duplicate_concept_gate" ] ||
  fail "duplicate hard-gate ID in product concept: $duplicate_concept_gate"

if ! diff -u "$concept_gates" "$mapped_gates" >/dev/null; then
  echo "traceability: ERROR: product-concept hard gates and requirements.tsv differ" >&2
  diff -u "$concept_gates" "$mapped_gates" >&2 || true
  exit 1
fi

gate_count=$(awk -F '\t' 'NR > 1 && $2 == "gate" { count++ } END { print count + 0 }' "$requirements")
scope_count=$(awk -F '\t' 'NR > 1 && ($2 == "included" || $2 == "excluded") { count++ } END { print count + 0 }' "$requirements")
task_count=$(wc -l < "$tasks_file" | tr -d ' ')

echo "traceability: OK: $task_count tasks, $scope_count scope requirements, $gate_count hard gates"
