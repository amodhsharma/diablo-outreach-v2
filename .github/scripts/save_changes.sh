#!/usr/bin/env bash
# Commit the given files back to the repository if they changed.
# Usage: save_changes.sh "commit message" file [file ...]
set -euo pipefail
message="$1"; shift
if [ -z "$(git status --porcelain -- "$@")" ]; then
  echo "Nothing changed, nothing to save."
  exit 0
fi
git config user.name "github-actions[bot]"
git config user.email "41898283+github-actions[bot]@users.noreply.github.com"
git add -- "$@"
git commit -m "$message"
for attempt in 1 2 3; do
  if git pull --rebase && git push; then
    exit 0
  fi
  sleep 5
done
echo "Could not save the changes after 3 tries." >&2
exit 1
