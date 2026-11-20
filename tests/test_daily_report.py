"""The daily summary email (Ariel, 27 Oct 2026): the agreed wording, the figures for the India day
before, and sending through Google from admin@diablosnosugar.com."""

import json

import pytest

from outreach import daily_log, daily_report
from outreach.common import PipelineError, load_settings
from outreach.schema import CONTACT_SOURCE, INBOX_TITLE, STOP_REASON

from .fakes import FakeCRM, FakeInstantly

DAY = "2026-10-26"


def quiet(_):
    pass


class FakeSMTP:
    def __init__(self):
        self.sent, self.login_as = [], None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        self.login_as = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


class Accounts:
    def __init__(self, accounts):
        self.accounts = accounts

    def list_accounts(self):
        return self.accounts


def _details(instantly, connected=None):
    """Instantly's campaign details and sending status, as the health check reads them."""
    def request(method, path, **kw):
        parts = path.strip("/").split("/")
        if len(parts) == 2:
            return dict(instantly.campaigns[parts[1]])
        return {"diagnostics": {"accounts_summary": {"total_connected": connected}}} if connected else {}
    instantly.request = request


def _month(day=None):
    """The campaign label of the month of `day` (default today), as button 4 names the campaigns (e.g. NOV2026)."""
    import datetime as dt
    from outreach.send import month_label
    return month_label(dt.date.fromisoformat(day) if day else None)


def _world():
    hs, instantly = FakeCRM(), FakeInstantly()
    # Research on 26 Oct (India time): two in Australia, one in South Africa; one the day before.
    for name, country, when in (("Alpha", "Australia", "2026-10-26T03:00:00Z"), ("Beta", "Australia", "2026-10-26T10:00:00Z"),
                                ("Gamma", "South Africa", "2026-10-26T17:00:00Z"),
                                ("Old", "Australia", "2026-10-25T17:00:00Z")):  # 25 Oct, 22:30 India time
        hs.add("companies", name=name, country=country, createdate=when, hs_lastmodifieddate=when,
               hs_lead_status="New")
    approved = hs.add("companies", name="Approved Co", country="Australia", createdate="2026-10-20T00:00:00Z",
                      hs_lastmodifieddate="2026-10-26T06:00:00Z", hs_lead_status="GATE1: Approved for outreach")
    nowhere = hs.add("companies", name="Sport Benzin", createdate="2026-10-20T00:00:00Z",
                     hs_lastmodifieddate="2026-10-26T07:00:00Z", hs_lead_status="Missing Info",
                     **{STOP_REASON: "No contact found anywhere (2026-10-26): nobody in Apollo"})
    quiet_co = hs.add("companies", name="Quiet Co", createdate="2026-10-10T00:00:00Z",
                      hs_lastmodifieddate="2026-10-26T08:00:00Z", hs_lead_status="Contacted, but no response, unqualified")
    hs.past = {("companies", approved): [("GATE1: Approved for outreach", "2026-10-26T06:00:00Z"), ("New", "2026-10-20T00:00:00Z")],
               ("companies", nowhere): [("Missing Info", "2026-10-26T07:00:00Z"), ("GATE1: Approved for outreach", "2026-10-25T07:00:00Z")],
               ("companies", quiet_co): [("Contacted, but no response, unqualified", "2026-10-26T08:00:00Z"),
                                         ("Attempted to Contact", "2026-10-18T08:00:00Z")]}
    # Contacts found on 26 Oct: Approved Co has a person, Inbox Co only its website address.
    inbox_co = hs.add("companies", name="Inbox Co", createdate="2026-10-20T00:00:00Z", hs_lead_status="GATE1: Approved for outreach")
    person = hs.add("contacts", email="p@approved.example", jobtitle="Buyer", createdate="2026-10-26T06:30:00Z",
                    hs_lead_status="NEW_PERSONAL_LINE_FILLED", **{CONTACT_SOURCE: "Apollo"})
    hs.links[person] = [approved]
    inbox = hs.add("contacts", email="info@inbox.example", jobtitle=INBOX_TITLE, createdate="2026-10-26T06:40:00Z",
                   hs_lead_status="NEW")
    hs.links[inbox] = [inbox_co]
    felfel = hs.add("companies", name="FELFEL", createdate="2026-10-20T00:00:00Z", hs_lead_status="In Progress")
    happy = hs.add("contacts", email="a@felfel.example", jobtitle="Owner", createdate="2026-10-20T00:00:00Z",
                   hs_lead_status="IN_PROGRESS")
    hs.links[happy] = [felfel]
    # Instantly: three introductions sent on 26 Oct (one to a company inbox), one on 25 Oct.
    main = instantly.create_campaign({"name": f"Diablo | {_month("2026-10-26")}", "email_list": ["sales@x.example"], "status": 1})["id"]
    box = instantly.create_campaign({"name": f"Diablo | {_month("2026-10-26")} | Company inboxes", "email_list": [], "status": 1})["id"]
    instantly.leads[main] = [{"email": "a@felfel.example", "timestamp_last_contact": "2026-10-26T09:00:00Z"},
                             {"email": "b@x.example", "timestamp_last_contact": "2026-10-26T10:00:00Z"},
                             {"email": "c@x.example", "timestamp_last_contact": "2026-10-25T10:00:00Z"}]
    instantly.leads[box] = [{"email": "info@y.example", "timestamp_last_contact": "2026-10-26T11:00:00Z"}]
    _details(instantly, connected=1)
    log = {"days": {DAY: {"positive": [happy], "negative": ["9"], "neutral": [], "auto": ["7", "8"], "bounced": ["6"],
                          "opted_out": []}},
           "before": {"2026-10": {"positive": 2, "negative": 1, "neutral": 1}}}
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 100}])
    return hs, instantly, accounts, log


def test_key_numbers_read_as_agreed():
    """20 Nov 2026 (Ariel): the old written summary is gone; Key numbers sits under the three charts."""
    hs, instantly, accounts, log = _world()
    result = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY, preview=True,
                              log=quiet, log_data=log)
    assert result["subject"] == "Partner outreach: daily summary, Monday 26 October 2026"
    text = result["text"]
    for gone in ("Good morning", "Prospecting", "Month to date", "Kind regards", "240"):
        assert gone not in text
    lines = [" ".join(line.split()) for line in text.splitlines()]
    assert lines[0] == "Key numbers - Monday 26 October 2026"
    assert lines[1] == "Yesterday Day before Month so far"
    assert "Introductions sent 3 1 ▲ 4" in lines
    assert "Instantly uploads used: 4 of 25,000 (0%)" in lines
    assert "Undelivered (bounced; Instantly pauses at 5%) 1 (33.3%) 0 ▲ 1 (25.0%)" in lines
    assert "Asked not to be emailed 0 0 = 0" in lines and "Automatic replies (out of office) 2 0 ▲ 2" in lines
    # 21 Nov 2026 (Ariel): Health, each campaign by its full name, straight to the point
    assert f"!! Diablo | {_month("2026-10-26")} | Company inboxes: No sending account connected" in lines
    assert f"OK Diablo | {_month("2026-10-26")}: Running" in lines and "OK 1 of 1 healthy" in lines
    assert "[Parameter] Sending" in lines and "[Health] Campaigns" in lines and "[Health] Sending accounts" in lines
    assert "[For sales team] Positive replies to follow up" in lines
    at = next(i for i, line in enumerate(lines) if "Positive replies to follow up" in line)
    assert lines[at + 1] == "FELFEL (country not known), replied Mon 26 Oct"
    at = next(i for i, line in enumerate(lines) if "Negative replies to convert into possible leads" in line)
    assert lines[at + 1] == "None"
    # 21 Nov 2026 (Ariel): "Waiting for you" is merged into Initial stages; nobody found has its own section
    assert not any("Waiting for you" in line for line in lines)
    assert "New companies waiting for your GATE1 approval 4" in lines and "Introductions waiting for your GATE2 approval 1" in lines
    at = lines.index("[Need Amodh's input] Companies where nobody could be found (need sales people input) 1")
    assert lines[at + 1] == "Sport Benzin"
    assert result["sent"] is False


def test_it_is_sent_from_the_agreed_mailbox(monkeypatch):
    hs, instantly, accounts, log = _world()
    smtp = FakeSMTP()
    with pytest.raises(PipelineError):  # no secrets yet: nothing is sent
        daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY, log=quiet,
                         smtp=smtp, log_data=log)
    monkeypatch.setenv("DAILY_REPORT_TO", "one@team.example, two@team.example,three@team.example")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY, log=quiet, smtp=smtp,
                     log_data=log)
    msg = smtp.sent[0]
    assert smtp.login_as == ("admin@diablosnosugar.com", "app-password")
    assert msg["From"] == "Diablo Partner Outreach <admin@diablosnosugar.com>"
    assert msg["To"] == "one@team.example, two@team.example, three@team.example"
    html = msg.get_body(("html",)).get_content()
    assert "<b>Key numbers - Monday 26 October 2026</b>" in html and "FELFEL (country not known)" in html
    assert "Prospecting" not in html and "Good morning" not in html


def test_a_quiet_day_and_all_healthy():
    hs, instantly = FakeCRM(), FakeInstantly()
    instantly.create_campaign({"name": f"Diablo | {_month("2026-11-01")}", "email_list": ["sales@x.example"], "status": 1})
    _details(instantly)
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 99}])
    result = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False,
                              date="2026-11-01", preview=True, log=quiet, log_data={})
    lines = [" ".join(line.split()) for line in result["text"].splitlines()]
    assert "Introductions sent 0 0 = 0" in lines and "OK 1 of 1 healthy" in lines
    # 21 Nov 2026: no positive or negative replies, no referral, no reply from outside; nothing waiting, and
    # "Waiting for you" is now part of Initial stages; "Referrals handled automatically" only when there are some
    assert lines.count("None") == 3
    assert not any("Referrals handled automatically" in line for line in lines)
    assert "[Need Amodh's input] Replies not AUTO-OUTREACH 0" in lines
    assert "Your input needed 0" in lines and not any("Waiting for you" in line for line in lines)
    assert not any("nobody could be found" in line for line in lines)  # its own section only on days with some
    assert not any(line.startswith("Companies waiting for GATE1 approval") for line in lines)  # 0: left out
    assert "#0F6E56" in result["html"]  # the healthy line is green
    assert 'color:#0F6E56;">No input needed (automatic)</td>' in result["html"]  # 21 Nov 2026: in green


def test_every_company_that_replied_is_named_neutral_and_referrals_marked():
    """20 Nov 2026 (Ariel): Positive, Neutral and Referral go under "Positive replies to follow up" (the last two
    marked), Negative under "Negative replies to convert into possible leads"; a company counts once, by its strongest
    tag as on the chart."""
    hs = FakeCRM()
    people = {}
    for company, country in (("Kadac", "au"), ("Nordic Sweets", "Norway"), ("Swiss Snack Box", "Switzerland"),
                             ("Hamper Co", "United Kingdom"), ("Mixed Co", "Germany")):
        cid = hs.add("companies", name=company, country=country)
        for i in range(2 if company == "Mixed Co" else 1):
            person = hs.add("contacts", email=f"p{i}@{company[:3].lower()}.example")
            hs.links[person] = [cid]
            people.setdefault(company, []).append(person)
    entry = {"positive": [people["Kadac"][0]], "negative": [people["Nordic Sweets"][0], people["Mixed Co"][0]],
             "neutral": [people["Swiss Snack Box"][0], people["Hamper Co"][0], people["Mixed Co"][1]]}
    forwarded = {people["Hamper Co"][0]: ["Referral"], people["Mixed Co"][1]: ["Neutral"]}
    follow, negative = daily_report.replies(hs, entry, "2026-11-19", forwarded)
    assert follow == [("Hamper Co", "United Kingdom", "referral"), ("Kadac", "Australia", None),
                      ("Swiss Snack Box", "Switzerland", "neutral")]
    assert negative == [("Mixed Co", "Germany", None), ("Nordic Sweets", "Norway", None)]


def test_at_the_month_change_only_the_reported_month_shows():
    """21 Nov 2026 (Ariel): the email sent just after midnight on 1 December reports 30 November, so Health shows
    the November campaigns only, never December's (or October's)."""
    hs, instantly = FakeCRM(), FakeInstantly()
    for month in ("OCT2026", "NOV2026", "DEC2026"):
        instantly.create_campaign({"name": f"Diablo | {month}", "email_list": ["sales@x.example"], "status": 1})
    instantly.create_campaign({"name": "Diablo | NOV2026 | Company inboxes", "email_list": ["sales@x.example"], "status": 1})
    _details(instantly)
    accounts = Accounts([{"email": "sales@x.example", "status": 1, "warmup_status": 1, "stat_warmup_score": 99}])
    h = daily_report.health(instantly, load_settings(), accounts, view={}, day="2026-11-30")
    assert [name for _, name, *_ in h["campaigns"]] == ["Diablo | NOV2026", "Diablo | NOV2026 | Company inboxes"]
    h = daily_report.health(instantly, load_settings(), accounts, view={}, day="2026-12-01")
    assert [name for _, name, *_ in h["campaigns"]] == ["Diablo | DEC2026"]


def test_a_mailbox_that_needs_attention_is_named():
    hs, instantly = FakeCRM(), FakeInstantly()
    instantly.create_campaign({"name": f"Diablo | {_month()}", "email_list": ["sales@x.example"], "status": 1})
    _details(instantly)
    accounts = Accounts([{"email": "sales@x.example", "status": -1, "warmup_status": 1, "stat_warmup_score": 100}])
    h = daily_report.health(instantly, load_settings(), accounts)
    assert h["accounts"] == {"healthy": 0, "total": 1, "problems": [("sales@x.example", "Connection error")]}


def test_the_log_records_each_answer_once_by_india_day(tmp_path):
    notes = tmp_path / "timeline_notes.json"
    notes.write_text(json.dumps({"reply:marked interested": ["1"], "bounced": ["2"]}))
    events = [({"id": "1"}, {}, "marked interested"),            # already known before the log: not again
              ({"id": "3"}, {"timestamp_last_reply": "2026-10-26T20:00:00Z"}, "replied"),  # sent 27 Oct India time
              ({"id": "4"}, {}, "out of office"), ({"id": "5"}, {}, "bounced"), ({"id": "6"}, {}, "blocklisted"),
              ({"id": "7"}, {}, "emailed")]
    import datetime as dt
    now = dt.datetime(2026, 10, 26, 12, 0, tzinfo=dt.timezone.utc)
    assert daily_log.record(events, notes_path=notes, now=now) == 4
    assert daily_log.record(events, notes_path=notes, now=now) == 0
    data = daily_log.load()
    # 20 Nov 2026 (Ariel): filed on the day it was noticed, not the day it was sent
    assert daily_log.day(data, "2026-10-27")["neutral"] == []
    assert daily_log.day(data, DAY) == {"positive": [], "negative": [], "neutral": ["3"], "auto": ["4"], "bounced": ["5"],
                                         "opted_out": ["6"]}
    assert daily_log.month_counts(data, "2026-10-01", "2026-10-31")["positive"] == 1  # from before the log


import datetime as dt  # noqa: E402


# ---- 20 Nov 2026 (Ariel): the day reported is the UK day, midnight to midnight UK time ------------------------

def test_the_reported_day_is_the_uk_day_summer_time_included():
    from outreach import daily_report as dr
    ten_am_uk_winter = dt.datetime(2026, 11, 20, 10, 0, tzinfo=dt.timezone.utc)
    assert dr.yesterday(ten_am_uk_winter) == "2026-11-19"
    start, end = dr.window("2026-11-19")
    assert (start.isoformat(), end.isoformat()) == ("2026-11-19T00:00:00+00:00", "2026-11-20T00:00:00+00:00")
    start, end = dr.window("2026-07-01")  # British summer time: midnight UK is 23:00 UTC
    assert (start.isoformat(), end.isoformat()) == ("2026-06-30T23:00:00+00:00", "2026-07-01T23:00:00+00:00")
    start, end = dr.window("2027-03-28")  # the clocks go forward: a 23-hour day
    assert (end - start) == dt.timedelta(hours=23)
    just_after_midnight_india = dt.datetime(2026, 11, 20, 19, 0, tzinfo=dt.timezone.utc)  # 00:30 India, 19:00 UK
    assert dr.yesterday(just_after_midnight_india) == "2026-11-19"


def test_the_daily_log_keeps_uk_days_and_falls_back_to_india_days_before_them(tmp_path):
    from outreach import daily_log
    path = tmp_path / "log.json"
    data = {"days": {"2026-11-18": {"positive": ["1"]}}, "seen": {}, "before": {}, "uk_since": "2026-11-19T00:00:00+00:00"}
    daily_log.save(data, path)
    late = dt.datetime(2026, 11, 20, 20, 0, tzinfo=dt.timezone.utc)  # 20:00 UK on the 20th, 01:30 India on the 21st
    rec = {"id": "2"}
    lead = {"timestamp_last_reply": (late - dt.timedelta(hours=3)).isoformat()}  # filed when noticed (20 Nov 2026)
    daily_log.record([(rec, lead, "marked interested")], path=path, now=late)
    data = daily_log.load(path)
    assert data["days"]["2026-11-21"]["positive"] == ["2"] and data["uk_days"]["2026-11-20"]["positive"] == ["2"]
    assert daily_log.day(data, "2026-11-20", uk=True)["positive"] == ["2"]
    assert daily_log.day(data, "2026-11-18", uk=True)["positive"] == ["1"]  # before the UK record: India days
    month = daily_log.month_counts(data, "2026-11-01", "2026-11-20", uk=True)
    assert month["positive"] == 2  # the 18th from India days, the 20th from UK days, nobody twice


def _with_a_company_that_moved(hs, day):
    when = dt.datetime.fromisoformat(f"{day}T12:00:00+00:00")
    cid = hs.add("companies", name="Kadac", country="Australia", hs_lead_status="New",
                 hs_lastmodifieddate=str(int(when.timestamp() * 1000)))
    past = dict(getattr(hs, "past", {}) or {})
    past[("companies", cid)] = [("New", when.isoformat())]
    hs.past = past


def test_the_sankey_charts_go_at_the_top_of_the_daily_email_to_everyone(monkeypatch, tmp_path):
    """20 Nov 2026 (Ariel): the three Sankey charts for the UK day, then Key numbers, to all three."""
    from pathlib import Path
    monkeypatch.setenv("DAILY_REPORT_TO", "a@example.com, b@example.com, c@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    monkeypatch.chdir(tmp_path)
    drawn = []

    def draw(spec, png):
        drawn.append(spec)
        Path(png).write_bytes(b"\x89PNG fake")
        return png
    hs, instantly, accounts, log = _world()
    _with_a_company_that_moved(hs, DAY)
    smtp = FakeSMTP()
    daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, log=quiet, smtp=smtp,
                     log_data=log, draw=draw)
    msg = smtp.sent[0]
    assert msg["To"] == "a@example.com, b@example.com, c@example.com"
    assert len([p for p in msg.walk() if p.get_content_type() == "image/png"]) == 3
    html_body = msg.get_body(("html",)).get_content()
    assert html_body.count("<img") == 3
    assert html_body.index("<img") < html_body.index("Key numbers")  # the charts first
    for gone in ("Good morning", "Prospecting", "Kind regards", "written out"):
        assert gone not in html_body
    assert drawn[0]["title"] == "Monday 26 October 2026: auto outreach companies assessed today"
    text = msg.get_body(("plain",)).get_content()
    assert "October so far (1 to 26 October 2026): auto outreach companies assessed (chart in the HTML" in text
    assert "Key numbers - Monday 26 October 2026" in text


def test_a_chart_that_cannot_be_drawn_is_written_out_with_its_arrows(monkeypatch, tmp_path):
    """20 Nov 2026 (Ariel): the same three charts as text, with the same words, numbers, % and arrows."""
    monkeypatch.setenv("DAILY_REPORT_TO", "a@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    monkeypatch.chdir(tmp_path)

    def broken(spec, png):
        raise RuntimeError("node is missing")
    hs, instantly, accounts, log = _world()
    _with_a_company_that_moved(hs, DAY)
    smtp, shown = FakeSMTP(), []
    daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, log=shown.append,
                     smtp=smtp, log_data=log, draw=broken)
    assert smtp.sent and not [p for p in smtp.sent[0].walk() if p.get_content_type() == "image/png"]
    assert any("could not be drawn" in line for line in shown)
    text = smtp.sent[0].get_body(("plain",)).get_content()
    lines = text.splitlines()
    assert lines[0] == "The charts could not be drawn today, so they are written out below."
    assert "Monday 26 October 2026: auto outreach companies assessed today" in lines
    assert "Companies assessed (all AUTO-OUTREACH): 4" in lines and "  By country: Australia 2, Other 2" in lines
    assert "    Unqualified: 2 (50%) ▲ was 0%" in lines and "      Nobody usable found: 1 (50%) ▲ was 0%" in lines
    assert "    Initial stages: 2 (50%) ▼ was 100%" in lines  # the day chart
    # Kadac is New (waits for GATE1 approval) and Approved Co has an introduction waiting for GATE2 approval
    assert "      Your input needed: 2 (100%) ▲ was 0%" in lines
    assert not any(line.startswith("No replies received") for line in lines[:12])  # FELFEL replied that day
    html_body = smtp.sent[0].get_body(("html",)).get_content()
    assert "#C0392B;font-weight:bold\">▲" in html_body  # more Unqualified: a red arrow, as on the chart
    assert "Key numbers - Monday 26 October 2026" in text


def test_the_chart_text_matches_the_chart():
    from outreach import flow_charts
    spec = {"title": "T", "subtitle": "S", "total": 10, "shareCol": 2,
            "nodes": {"all": ["Companies assessed\n(all AUTO-OUTREACH)", "#5F5E5A", 0], "c0": ["Australia", "#7F77DD", 1],
                      "U": ["Unqualified", flow_charts.RED, 2], "N": ["Emails sent,\nno reply yet", "#888780", 2],
                      "r4": ["No reply in time", flow_charts.RED, 3], "n2": ["1 person emailed", "#B4B2A9", 3]},
            "links": [["all", "c0", 10], ["c0", "U", 4], ["c0", "N", 6], ["U", "r4", 4], ["N", "n2", 6]],
            "prev": {"U": 20, "N": 60, "r4": 100, "n2": 50}, "notes": {"r4": "2 will restart automatically within 9 days"}}
    assert flow_charts.chart_text(spec) == [
        "T", "S", "Companies assessed (all AUTO-OUTREACH): 10", "  By country: Australia 10",
        "    Unqualified: 4 (40%) ▲ was 20%", "      No reply in time: 4 (100%) = 100%",
        "        2 will restart automatically within 9 days",
        "    Emails sent, no reply yet: 6 (60%) = 60%", "      1 person emailed: 6 (100%) ▲ was 50%"]
    rows = {r["label"]: r for r in flow_charts.chart_lines(spec)}
    assert rows["Unqualified"]["good"] is False and rows["1 person emailed"]["good"] is True


def test_one_line_when_hubspot_cannot_be_read(monkeypatch, tmp_path):
    """20 Nov 2026 (Ariel): if HubSpot cannot be read at all, a one-line email says why."""
    from outreach.hubspot_client import HubSpotError
    monkeypatch.setenv("DAILY_REPORT_TO", "a@example.com")
    monkeypatch.setenv("DAILY_REPORT_APP_PASSWORD", "app-password")
    monkeypatch.chdir(tmp_path)
    hs, instantly, accounts, log = _world()

    def down():
        raise HubSpotError("503 Service Unavailable")
    hs.portal_id = down
    smtp = FakeSMTP()
    daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, date=DAY, log=quiet, smtp=smtp,
                     log_data=log)
    text = smtp.sent[0].get_body(("plain",)).get_content()
    assert text == "Today's charts could not be produced: HubSpot could not be read (503 Service Unavailable).\n"


def test_the_bounces_name_their_sending_account_and_company():
    """20 Nov 2026 (Ariel): under Undelivered, which sending account each bounce came from (with its share of that
    account's emails that day) and at which company."""
    hs, instantly, accounts, log = _world()
    shop = hs.add("companies", name="Kadac", country="au", createdate="2026-10-20T00:00:00Z",
                  hs_lead_status="Attempted to Contact")
    gone = hs.add("contacts", email="old@kadac.example", jobtitle="Buyer", createdate="2026-10-20T00:00:00Z",
                  hs_lead_status="ATTEMPTED_TO_CONTACT")
    hs.links[gone] = [shop]
    main = next(k for k, c in instantly.campaigns.items() if c["name"] == f"Diablo | {_month("2026-10-26")}")
    instantly.leads[main].append({"email": "old@kadac.example", "timestamp_last_contact": "2026-10-26T12:00:00Z",
                                  "last_step_from": "sales@x.example", "status": -1})
    for lead in instantly.leads[main]:
        lead.setdefault("last_step_from", "sales@x.example")
    log["days"][DAY]["bounced"] = [gone]
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY,
                            preview=True, log=quiet, log_data=log)["text"]
    lines = [" ".join(line.split()) for line in text.splitlines()]
    assert "By sending account: sales@x.example 1 (33% of its 3 emails)" in lines
    assert "At: Kadac (Australia)" in lines


@pytest.mark.channels
def test_companies_whose_channel_is_not_known_are_named_under_waiting_for_you():
    hs, instantly, accounts, log = _world()
    hs.add("companies", name="Mystery Co", domain="mystery.example", hs_lead_status="GATE1: Approved for outreach")
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY,
                            preview=True, log=quiet, log_data=log)["text"]
    lines = [" ".join(line.split()) for line in text.splitlines()]
    at = next(i for i, line in enumerate(lines) if line.startswith("Companies whose channel is not known"))
    assert "Mystery Co" in lines[at + 1:]


def test_initial_stages_section_says_what_needs_input_and_what_does_not():
    """20 Nov 2026 (Ariel): under Key numbers, the companies not yet emailed, at midnight UK, by whether input is needed."""
    hs, instantly, accounts, log = _world()
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY,
                            preview=True, log=quiet, log_data=log)["text"]
    lines = [" ".join(line.split()) for line in text.splitlines()]
    at = next(i for i, line in enumerate(lines) if "Initial stages - your input needed or not (at midnight UK)" in line)
    block = lines[at + 1:]
    assert block[0] == "Your input needed 5"  # 4 new companies and 1 introduction
    assert "New companies waiting for your GATE1 approval 4" in block
    assert "Introductions waiting for your GATE2 approval 1" in block
    assert "Approved Co (Australia)" in block
    # 21 Nov 2026 (Ariel): one green line, without the breakdown
    assert "No input needed (automatic) 3" in block
    assert not any(line.startswith(("Approved, Apollo search", "People found, introduction")) for line in block)


# ---- 20 Nov 2026 (Ariel): one cut-off for the whole email, midnight UK at the end of the day reported ----------

def test_waiting_and_initial_stages_are_as_they_stood_at_midnight_uk():
    hs, instantly, accounts, log = _world()
    # Approved at 00:02 UK the next morning: still waiting for GATE1 at midnight, so it counts
    late = hs.add("companies", name="Late Co", country="Australia", hs_lead_status="GATE1: Approved for outreach",
                  hs_lastmodifieddate="2026-10-27T00:02:00Z")
    # Created at 00:03 UK the next morning: not there at midnight, so it does not count
    tomorrow = hs.add("companies", name="Tomorrow Co", country="Australia", hs_lead_status="New",
                      hs_lastmodifieddate="2026-10-27T00:03:00Z")
    hs.past = {**hs.past, ("companies", late): [("GATE1: Approved for outreach", "2026-10-27T00:02:00Z"),
                                                ("New", "2026-10-24T10:00:00Z")],
               ("companies", tomorrow): [("New", "2026-10-27T00:03:00Z")]}
    text = daily_report.run("test", load_settings(), hs, instantly, accounts_api=accounts, charts=False, date=DAY,
                            preview=True, log=quiet, log_data=log)["text"]
    lines = [" ".join(line.split()) for line in text.splitlines()]
    block = lines[next(i for i, line in enumerate(lines) if "Initial stages - your input needed or not (at midnight UK)" in line) + 1:]
    assert "New companies waiting for your GATE1 approval 5" in block  # the 4 of the day and Late Co
    assert "Late Co" in block and "Tomorrow Co" not in block
    assert not any(line.startswith("Companies waiting for GATE1 approval") for line in lines)  # merged, once only


def test_a_day_not_over_yet_is_read_as_it_stands_now():
    from outreach.stages import LeadStatus
    hs = FakeCRM()
    cid = hs.add("companies", name="Now Co", hs_lead_status="New", hs_lastmodifieddate="2026-10-26T10:00:00Z")
    at = daily_report.AtCutoff(hs, LeadStatus(hs), dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc),
                               now=dt.datetime(2026, 10, 26, 12, tzinfo=dt.timezone.utc))
    assert at.live and [r["id"] for r in at.records("companies", "found")] == [cid]


def test_the_check_names_chart_companies_missing_from_key_numbers():
    key = {"initial": {"ids": {"1"}}}
    assert daily_report.sync_check({"input": {"1": "Alpha"}}, key) is None
    line = daily_report.sync_check({"input": {"1": "Alpha", "2": "Beta"}}, key)
    assert line == "Check: the day chart shows 1 company needing your input that this list does not: Beta"
    assert daily_report.sync_check({"input": {"2": "Beta"}}, {}) is None  # Key numbers could not be read
