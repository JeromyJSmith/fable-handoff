#!/usr/bin/env bash
# Install the fable-handoff skill for Claude Code.
#   curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/main/install.sh | bash
#   ... | bash -s -- --project     install into ./.claude/skills of the current repo
#   ... | bash -s -- --ref v1.1.0  install a release tag (recommended over main)
#   ... | bash -s -- --ref 8e75ea5  install one commit (a full or short hash)
set -euo pipefail
REPO="${FABLE_HANDOFF_REPO:-https://github.com/JeromyJSmith/fable-handoff}"
REF=main; DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"
while [ $# -gt 0 ]; do
  case "$1" in
    --project) DEST="$PWD/.claude/skills" ;;
    --ref) REF="$2"; shift ;;
    --dest) DEST="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac; shift
done
for cmd in git uv; do
  command -v "$cmd" >/dev/null || { echo "fable-handoff needs $cmd. Install uv: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
done
uv python find '>=3.11' >/dev/null 2>&1 || uv python install 3.11 || { echo "uv could not provide Python 3.11 or later" >&2; exit 1; }
command -v jq >/dev/null || echo "note: jq 1.7 is optional but needed for conversation and spec queries"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# A branch or tag clones directly. Anything else is taken as a commit: clone
# the history, then check that commit out (a short hash works too).
if ! git -c advice.detachedHead=false clone -q --depth 1 --branch "$REF" "$REPO" "$tmp/src" 2>/dev/null; then
  rm -rf "$tmp/src"
  git -c advice.detachedHead=false clone -q "$REPO" "$tmp/src"
  git -C "$tmp/src" -c advice.detachedHead=false checkout -q "$REF" 2>/dev/null || { echo "fable-handoff: no branch, tag or commit named $REF in $REPO" >&2; exit 1; }
fi
mkdir -p "$DEST"
if [ -d "$DEST/fable-handoff" ]; then mv "$DEST/fable-handoff" "$DEST/fable-handoff.bak-$(date +%Y%m%d%H%M%S)"; fi
cp -R "$tmp/src/fable-handoff" "$DEST/fable-handoff"
commit="$(git -C "$tmp/src" rev-parse HEAD)"
printf 'repo=%s\nref=%s\ncommit=%s\n' "$REPO" "$REF" "$commit" > "$DEST/fable-handoff/.installed-from"
echo "Installed fable-handoff $REF (commit $commit) to $DEST/fable-handoff"
[ "$REF" = main ] && echo "note: main can change at any time. For a fixed version, rerun with --ref <tag>; tags are listed at $REPO/tags"
echo "Start a Claude Code session and ask it to hand a project to Fable."
