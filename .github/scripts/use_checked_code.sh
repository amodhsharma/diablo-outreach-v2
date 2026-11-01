#!/usr/bin/env bash
# Every button runs only code that passed the automatic checks (1 Nov 2026, Ariel). The checks run once,
# when the code changes ("Code checks"), and mark that version on the branch checked-code. Here the
# button compares its code with that version:
#   - the same: it goes ahead;
#   - different (a newer change has not passed, or is still being checked): it uses the last checked
#     version of the code for this run, and says so on the run's page. Nothing is saved back: only the
#     button's own data files are ever saved (save_changes.sh).
# Until the first version has been checked (no branch yet), the checks run here instead, as before.
set -uo pipefail
CODE=(outreach tests skills/outreachResearch/scripts skills/outreachMailWriting/scripts config templates requirements.txt)
if ! git fetch -q --depth=1 origin checked-code 2>/dev/null; then
  echo "No version has been marked as checked yet: running the checks here instead."
  python -m pytest -q
  exit $?
fi
if git diff --quiet FETCH_HEAD HEAD -- "${CODE[@]}"; then
  echo "This code passed the automatic checks."
  exit 0
fi
echo "::warning::The newest code change has not passed the automatic checks (yet); this run uses the last checked version."
git restore --source=FETCH_HEAD --worktree -- "${CODE[@]}"
pip install -q -r requirements.txt
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  echo "**This run used the last checked version of the code:** the newest change has not passed the automatic checks yet." >> "$GITHUB_STEP_SUMMARY"
fi
