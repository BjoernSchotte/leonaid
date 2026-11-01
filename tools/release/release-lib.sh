# LeonAid release helpers (POSIX sh + git + awk), sourced by release.sh and
# release_test.py. Adapted from getdone's CalVer scheme.
#
# Releases: vYYYY.M.N (N counts releases within the UTC month, no zero
# padding). Fix releases on top of one release: vYYYY.M.N.P (P from 1).
# Tags are annotated and never moved, deleted or reused.

_release_re='^v[0-9]{4}\.(1[0-2]|[1-9])\.[1-9][0-9]*$'
_fix_re='^v[0-9]{4}\.(1[0-2]|[1-9])\.[1-9][0-9]*\.[1-9][0-9]*$'
_base_re='^[0-9]{4}\.(1[0-2]|[1-9])\.[1-9][0-9]*$'

# Versions (with or without v) on stdin, sorted ascending and numerically; a
# release sorts before its fix releases.
sort_versions() {
  awk -F. '{ v = $0; sub(/^v/, "", $1); printf "%06d %04d %06d %06d %s\n", $1, $2, $3, (NF > 3 ? $4 : 0), v }' |
    sort | cut -d' ' -f5
}

# The current UTC month as YYYY.M from a single date call (no year/month mix
# at midnight on 31 December). RELEASE_MONTH overrides it for tests.
release_month() {
  if [ -n "${RELEASE_MONTH:-}" ]; then
    echo "$RELEASE_MONTH"
  else
    date -u +%Y.%m | sed 's/\.0/./'
  fi
}

# Next release in a UTC month (default: release_month), e.g. 2026.11.4 after
# v2026.11.3. Gaps are not refilled.
next_version() {
  prefix="${1:-$(release_month)}"
  last=$(git tag -l "v$prefix.*" | grep -E "$_release_re" | sort_versions | tail -1)
  if [ -z "$last" ]; then echo "$prefix.1"; else echo "$prefix.$((${last##*.} + 1))"; fi
}

# Next fix release on top of a release, e.g. 2026.11.1.3 after v2026.11.1.2.
next_fix() {
  last=$(git tag -l "v$1.*" | grep -E "$_fix_re" | sort_versions | tail -1)
  if [ -z "$last" ]; then echo "$1.1"; else echo "$1.$((${last##*.} + 1))"; fi
}

# Newest release or fix release tag merged into a ref (by version, never by
# date); empty if there is none.
last_tag() {
  git tag --merged "${1:-HEAD}" -l 'v*' | grep -E "$_release_re|$_fix_re" | sort_versions | tail -1
}

# Markdown notes for <from>..<to> (empty from = whole history), grouped by
# Conventional Commit type. Merge commits and chore(release) commits drop out.
release_notes() {
  range="$2"
  [ -z "$1" ] || range="$1..$2"
  git log --no-merges --format='%h%x09%s' "$range" | awk -F'\t' '
    $2 ~ /^chore\(release\)/ { next }
    { s = $2; type = "other"
      if (match(s, /^[a-z]+(\([^)]*\))?!?: /)) {
        head = substr(s, 1, RLENGTH - 2); s = substr(s, RLENGTH + 1); scope = ""
        bang = (head ~ /!$/); sub(/!$/, "", head)
        if (match(head, /\(.*\)/)) { scope = substr(head, RSTART + 1, RLENGTH - 2); head = substr(head, 1, RSTART - 1) }
        type = bang ? "breaking" : head
        if (scope != "") s = "**" scope ":** " s
      }
      sec = type == "breaking" ? 1 : type == "feat" ? 2 : type == "fix" ? 3 : type == "security" ? 4 : 5
      if (sec == 5 && type != "other") s = type ": " s
      out[sec] = out[sec] "- " s " (" $1 ")\n" }
    END { name[1] = "Breaking changes"; name[2] = "Features"; name[3] = "Fixes"; name[4] = "Security"; name[5] = "Other"
      for (i = 1; i <= 5; i++) if (out[i] != "") { printf "%s### %s\n\n%s", (n++ ? "\n" : ""), name[i], out[i] } }'
}
