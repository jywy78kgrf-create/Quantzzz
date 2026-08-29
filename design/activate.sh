#!/usr/bin/env bash
#
# Activate the "Design Deck" — wire every vendored skill under design/skills/
# into .claude/skills/ so Claude Code discovers and uses them in this repo.
#
# Each skill is exposed under a folder named after its canonical `name:`
# (the id in its SKILL.md front-matter), which is what Claude Code invokes.
#
# Usage:
#   ./design/activate.sh            # (re)create relative symlinks  [default]
#   ./design/activate.sh --copy     # copy instead of symlink (Windows / no-symlink envs,
#                                    #   or if your Claude Code build ignores symlinked skills)
#   ./design/activate.sh --clean    # remove everything under .claude/skills/
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/design/skills"
DST="$ROOT/.claude/skills"

mode="link"
case "${1:-}" in
  --copy)        mode="copy" ;;
  --clean)       rm -rf "$DST"; echo "Removed $DST"; exit 0 ;;
  --link|"" )    mode="link" ;;
  *) echo "usage: $(basename "$0") [--copy|--clean]"; exit 1 ;;
esac

relpath() { # relpath <target> <start-dir> — portable via python3
  python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

rm -rf "$DST"; mkdir -p "$DST"

count=0
while IFS= read -r f; do
  dir="$(dirname "$f")"
  name="$(grep -m1 -E '^name:' "$f" | sed -E 's/^name:[[:space:]]*//; s/^["'\'']//; s/["'\'']$//; s/[[:space:]]*$//')"
  [ -z "$name" ] && { echo "!! no name: in $f — skipped"; continue; }
  if [ -e "$DST/$name" ]; then echo "!! name collision '$name' — skipped $dir"; continue; fi
  if [ "$mode" = "copy" ]; then
    cp -R "$dir" "$DST/$name"
  else
    ln -s "$(relpath "$dir" "$DST")" "$DST/$name"
  fi
  count=$((count + 1))
done < <(find "$SRC" -name SKILL.md | sort)

echo "Activated $count skills into .claude/skills/ (mode: $mode)"
