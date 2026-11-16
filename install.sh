#!/usr/bin/env bash
# Install the fable-handoff skill for Claude Code.
#   curl -fsSL https://raw.githubusercontent.com/JeromyJSmith/fable-handoff/main/install.sh | bash
#   ... | bash -s -- --project     install into ./.claude/skills of the current repo
#   ... | bash -s -- --ref v1.0.0  install a tag or branch
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
for cmd in git python3; do command -v "$cmd" >/dev/null || { echo "fable-handoff needs $cmd" >&2; exit 1; }; done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "fable-handoff needs python3 3.9 or later" >&2; exit 1; }
command -v jq >/dev/null || echo "note: jq 1.7 is optional but needed for conversation and spec queries"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
git clone -q --depth 1 --branch "$REF" "$REPO" "$tmp/src"
mkdir -p "$DEST"
if [ -d "$DEST/fable-handoff" ]; then mv "$DEST/fable-handoff" "$DEST/fable-handoff.bak-$(date +%Y%m%d%H%M%S)"; fi
cp -R "$tmp/src/fable-handoff" "$DEST/fable-handoff"
echo "Installed fable-handoff to $DEST/fable-handoff"
echo "Start a Claude Code session and ask it to hand a project to Fable."
