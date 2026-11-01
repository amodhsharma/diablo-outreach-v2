#!/usr/bin/env bash
# Every automatic check, run as if it were each of the difficult days (1 Nov 2026, Ariel: no date may
# ever stop the buttons again). Usage:
#   date_checks.sh              the month ends, the new year and 29 February (used by "Code checks")
#   date_checks.sh next-month   the end of this month and the start of the next, India and UK time
#                               (the 25th's early warning, from button R)
# Exits 1 if any day fails; the days that failed are listed.
set -uo pipefail
if [ "${1:-}" = "next-month" ]; then
  first=$(python3 -c "import datetime as d; t=d.date.today(); n=(t.replace(day=28)+d.timedelta(days=4)).replace(day=1); print(n)")
  last=$(python3 -c "import datetime as d; print(d.date.fromisoformat('$first')-d.timedelta(days=1))")
  days="${last}T23:50:00+05:30 ${first}T00:20:00+05:30 ${first}T06:00:00+00:00 ${first}T23:55:00+00:00"
else
  y=$(date -u +%Y)
  days="${y}-11-30T23:50:00+05:30 ${y}-12-01T00:20:00+05:30 ${y}-12-31T23:30:00+00:00 $((y+1))-01-01T00:30:00+05:30
        $((y+1))-02-28T23:50:00+00:00 2028-02-29T12:00:00+00:00 $((y+1))-03-01T00:15:00+05:30 $((y+1))-06-30T23:55:00+05:30"
fi
failed=""
for day in $days; do
  if CHECK_DATE="$day" python -m pytest -q -p no:cacheprovider >"/tmp/checks_$$.txt" 2>&1; then
    echo "$day: every check passed"
  else
    echo "$day: FAILED"; tail -25 "/tmp/checks_$$.txt"; failed="$failed $day"
  fi
done
rm -f "/tmp/checks_$$.txt"
if [ -n "$failed" ]; then
  echo "DATE_CHECKS_FAILED=$failed" >> "${GITHUB_ENV:-/dev/null}"
  echo "::error::The checks fail on:$failed"
  exit 1
fi
