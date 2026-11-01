"""1 Nov 2026 (Ariel): no date may ever stop the buttons again. These make sure the pretend date of
.github/scripts/date_checks.sh really reaches the code, and that the month and year changes work."""

import datetime as dt
import os

from outreach import send


def test_the_pretend_date_reaches_the_code():
    when = os.environ.get("CHECK_DATE")
    if not when:
        return  # an ordinary run: today's date
    pretend = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
    if pretend.tzinfo:
        pretend = pretend.astimezone(dt.timezone.utc).replace(tzinfo=None)
    assert abs((dt.datetime.now() - pretend).total_seconds()) < 600
    assert send.month_label() == send.month_label(pretend.date())


def test_campaign_months_across_the_year_end():
    assert send.month_label(dt.date(2026, 12, 31)) == "DEC2026"
    assert send.month_label(dt.date(2027, 1, 1)) == "JAN2027"
    assert send.month_label(dt.date(2028, 2, 29)) == "FEB2028"
