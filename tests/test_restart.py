"""Restarting companies where nobody replied (19 Nov 2026, Ariel): off until switched on, and then nothing changes
by itself; a person sets the company back to GATE1, it waits 9 days after closing, it is refused when anyone there
replied, three new people go first and the earlier ones follow, everyone gets the same email again in this month's
RESTART campaign, and nobody whose address bounced is ever emailed again."""

import datetime as dt

import pytest

from outreach import chain, find_contacts, import_lines, restart, send, send_memory, stages
from outreach.common import load_settings
from outreach.next_in_line import instantly_view
from outreach.schema import INBOX_TITLE, LAST_CLOSED, ROUND, TIMES_INTRODUCED, TIMES_REMINDED
from outreach.stages import RESTART_LABEL, LeadStatus

from .fakes import FakeApollo, FakeCRM, FakeInstantly

LS, ORDER, LINE = "hs_lead_status", "diablo_outreach_order", "diablo_personal_line"
OLD_C, OLD_P = "Contacted, but no response, unqualified", "CONTACTED_NO_RESPONSE_UNQUALIFIED"
NEW_P = "NO_RESPONSE_CAN_RESTART"
TODAY = dt.datetime.now(dt.timezone.utc).date()


def quiet(*_):
    pass


def crm():
    """A HubSpot account where button 1 has added "No response: can restart"."""
    hs = FakeCRM()
    hs.options[("companies", LS)][RESTART_LABEL] = RESTART_LABEL
    hs.options[("contacts", LS)][NEW_P] = RESTART_LABEL
    return hs


def settings(on=True):
    s = load_settings()
    s["send"]["sending_accounts"] = ["one@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"
    s["restart"]["enabled"] = on
    return s


@pytest.fixture
def switched_on(monkeypatch):
    monkeypatch.setattr(stages, "restart_on", lambda settings=None: True)


def closed_company(hs, days_ago, status=RESTART_LABEL, people=None):
    """A company that closed with no reply days_ago and was set back to GATE1 by a person."""
    cid = hs.add("companies", name="Harris Farm", domain="harris.example", country="Australia",
                 industry_type="Distributor Wholesaler",
                 **{LS: "GATE1: Approved for outreach", LAST_CLOSED: (TODAY - dt.timedelta(days=days_ago)).isoformat()})
    ids = {}
    for key, title, st, order in people or (("p1", "Owner", NEW_P, 1), ("p2", "Buyer", "COLLEAGUE_CONTACTED_NO_RESPONSE", 2),
                                            ("p3", "Category Manager", "UNQUALIFIED_BOUNCED_OTHER", 3),
                                            ("inbox", INBOX_TITLE, NEW_P, 4)):
        pid = hs.add("contacts", email=f"{key}@harris.example", firstname=key, lastname="L", jobtitle=title,
                     diablo_company_note="imports sweets", **{ORDER: str(order), LS: st, LINE: f"Line of {key}."})
        hs.links[pid] = [cid]
        ids[key] = pid
    return cid, ids


def apollo_with_three():
    people = [{"id": f"n{i}", "title": t, "seniority": "director", "first_name": f"N{i}", "last_name": "New"}
              for i, t in enumerate(("Managing Director", "Head of Buying", "Purchasing Manager"), start=1)]
    return FakeApollo({"harris.example": people},
                      {f"n{i}": (f"n{i}@harris.example", "verified") for i in (1, 2, 3)})


def by_email(hs, email):
    return next(p for p in hs.records["contacts"].values() if p.get("email") == email)


# ---- switched off: nothing changes ----------------------------------------------------------------------------


def test_switched_off_everything_writes_and_sends_as_before():
    hs = crm()
    statuses = LeadStatus(hs, restart=False)
    assert statuses.props("companies", "no_response")[LS] == OLD_C  # still the old label
    assert statuses.props("contacts", "no_response")[LS] == OLD_P
    assert statuses.filter("companies", "no_response")["operator"] == "IN"  # both labels are read as "no response"
    assert statuses.stage("companies", RESTART_LABEL) == "no_response"
    assert restart.config(settings(on=False)) is None
    # Button 3 leaves a closed company on GATE1 alone (no migration, no restart).
    cid, ids = closed_company(hs, 20, people=(("p1", "Owner", OLD_P, 1),))
    hs.records["companies"][cid][LS] = OLD_C
    find_contacts.run("test", settings(on=False), hs, apollo_with_three(), log=quiet)
    assert hs.records["companies"][cid][LS] == OLD_C and hs.records["contacts"][ids["p1"]][LS] == OLD_P


def test_switched_off_button_4_adds_leads_exactly_as_before():
    hs, instantly = crm(), FakeInstantly()
    cid = hs.add("companies", name="Costco", domain="costco.example", country="Australia",
                 industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing", ROUND: "2"})
    pid = hs.add("contacts", email="p1@costco.example", firstname="P", lastname="L", jobtitle="Buyer",
                 diablo_company_note="imports sweets", **{ORDER: "1", LS: "APPROVED_TO_SEND", LINE: "Line."})
    hs.links[pid] = [cid]
    send.run("test", settings(on=False), hs, instantly, log=quiet)
    assert instantly.add_calls == [("camp1", False)]  # "skip if anywhere in Instantly", as today
    assert "RESTART" not in instantly.campaigns["camp1"]["name"]


# ---- switching on ---------------------------------------------------------------------------------------------


def test_switching_on_moves_the_no_response_companies_and_people_once_and_keeps_the_date(switched_on):
    hs = crm()
    cid = hs.add("companies", name="Old Co", country="Australia", **{LS: OLD_C})
    pid = hs.add("contacts", email="a@old.example", **{LS: OLD_P})
    other = hs.add("contacts", email="b@old.example", **{LS: "UNQUALIFIED_BOUNCED_OTHER"})
    hs.past = {("companies", cid): [(OLD_C, "2026-11-01T10:00:00Z"), ("Attempted to Contact", "2026-10-20T10:00:00Z")]}
    out = restart.migrate(hs, LeadStatus(hs), log=quiet)
    assert out == {"companies": 1, "contacts": 1}
    assert hs.records["companies"][cid][LS] == RESTART_LABEL and hs.records["companies"][cid][LAST_CLOSED] == "2026-11-01"
    assert hs.records["contacts"][pid][LS] == NEW_P
    assert hs.records["contacts"][other][LS] == "UNQUALIFIED_BOUNCED_OTHER"  # a bounce is never moved
    assert restart.migrate(hs, LeadStatus(hs), log=quiet) == {"companies": 0, "contacts": 0}  # once only


def test_switched_on_a_company_with_no_reply_ends_on_the_new_label():
    hs = crm()
    statuses = LeadStatus(hs, restart=True)
    assert statuses.props("companies", "no_response")[LS] == RESTART_LABEL
    assert statuses.props("contacts", "no_response")[LS] == NEW_P


def test_the_old_backlog_reopening_stops_once_restarts_are_on():
    shown = []
    out = chain.run_backlog(FakeCRM(), FakeInstantly(), settings(on=True), log=shown.append)
    assert out["reopened"] == 0 and "restarts are on" in shown[0]


# ---- a restart ------------------------------------------------------------------------------------------------


def test_nothing_restarts_before_9_days_after_closing(switched_on):
    hs, apollo = crm(), apollo_with_three()
    cid, ids = closed_company(hs, 5)
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert hs.records["companies"][cid][LS] == "GATE1: Approved for outreach"  # waits, your status is kept
    assert apollo.revealed == [] and hs.records["contacts"][ids["p1"]][LS] == NEW_P
    allowed = (TODAY + dt.timedelta(days=4)).isoformat()
    assert any(f"allowed from {allowed}" in line for line in shown)


@pytest.mark.parametrize("answered", ["IN_PROGRESS", "COLLEAGUE_REPLIED", "UNQUALIFIED_RESPONSE_NEGATIVE",
                                      "UNQUALIFIED_OPTED_OUT_BLOCKLIST", "END_FORWARDED_TO_SALES_TEAM"])
def test_a_company_where_anyone_replied_is_never_restarted(switched_on, answered):
    hs, apollo = crm(), apollo_with_three()
    cid, ids = closed_company(hs, 20, people=(("p1", "Owner", answered, 1), ("p2", "Buyer", "COLLEAGUE_REPLIED", 2),
                                              ("p3", "Category Manager", NEW_P, 3)))
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert apollo.revealed == []
    assert hs.records["contacts"][ids["p2"]][LS] == "COLLEAGUE_REPLIED"  # kept, never "can restart"
    assert hs.records["contacts"][ids["p3"]][LS] == NEW_P and hs.records["companies"][cid].get(ROUND) is None
    assert any("not restarted" in line for line in shown)


def test_a_restart_puts_three_new_people_first_and_never_the_bounced_one(switched_on):
    hs, apollo = crm(), apollo_with_three()
    cid, ids = closed_company(hs, 10)
    find_contacts.run("test", settings(), hs, apollo, log=quiet)
    order = sorted(((int(p[ORDER]), p["email"], p[LS]) for p in hs.records["contacts"].values()
                    if p.get(LS) == "APPROVED_TO_SEND"))
    assert [e for _, e, _ in order] == ["n1@harris.example", "n2@harris.example", "n3@harris.example",
                                        "p1@harris.example", "p2@harris.example", "inbox@harris.example"]
    assert [o for o, _, _ in order] == [1, 2, 3, 4, 5, 6]
    assert by_email(hs, "n1@harris.example")[LINE] == "Line of p1."  # the same email as before
    assert hs.records["contacts"][ids["p3"]][LS] == "UNQUALIFIED_BOUNCED_OTHER"  # never emailed again
    company = hs.records["companies"][cid]
    assert company[LS] == "Contact located. Queued for processing" and company[ROUND] == "2"
    assert restart.load()["companies"][str(cid)]["round"] == 2
    # The next run does not start it again.
    apollo.revealed.clear()
    find_contacts.run("test", settings(), hs, apollo, log=quiet)
    assert apollo.revealed == [] and hs.records["companies"][cid][ROUND] == "2"


def test_button_4_sends_the_round_in_the_restart_campaign_and_the_memory_lets_it(switched_on):
    hs, apollo, instantly = crm(), apollo_with_three(), FakeInstantly()
    cid, ids = closed_company(hs, 10)
    instantly.campaigns["old"] = {"name": "Diablo | OCT2026"}
    instantly.leads["old"] = [
        {"id": "l1", "email": "p1@harris.example", "status": 3, "timestamp_created": "2026-10-20T10:00:00Z",
         "timestamp_last_contact": "2026-10-20T10:00:00Z"},
        {"id": "l3", "email": "p3@harris.example", "status": -1, "timestamp_created": "2026-10-20T10:00:00Z"}]
    memory = send_memory.load()
    for key in ("p1", "p3"):
        send_memory._set(memory, ids[key], "introduced", dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc),
                         company=str(cid))
    send_memory._set(memory, ids["p1"], "reminded", dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc))
    send_memory.save(memory)
    find_contacts.run("test", settings(), hs, apollo, log=quiet)
    send.run("test", settings(), hs, instantly, log=quiet)
    restart_campaign = next(cid_ for cid_, c in instantly.campaigns.items() if "RESTART" in c["name"])
    assert instantly.campaigns[restart_campaign]["name"] == f"Diablo | RESTART | {send.month_label()}"
    assert [l["email"] for l in instantly.leads[restart_campaign]] == ["n1@harris.example"]  # new person 1 first
    assert (restart_campaign, True) in instantly.add_calls  # only "already in this campaign" is skipped
    memory = send_memory.load()
    assert not send_memory.blocks_intro(memory, ids["p1"])  # a new round: their introduction may go again
    assert memory["contacts"][ids["p1"]]["past"][0]["introduced"].startswith("2026-10-20")
    # The counters: p1 introduced and reminded once in round 1; the company counts everyone.
    assert hs.records["contacts"][ids["p1"]][TIMES_INTRODUCED] == "1"
    assert hs.records["contacts"][ids["p1"]][TIMES_REMINDED] == "1"
    assert hs.records["companies"][cid]["diablo_introductions_sent"] == "3"  # p1, p3 and new person 1


def test_an_address_that_bounced_anywhere_is_never_added_to_a_restart(switched_on):
    hs, instantly = crm(), FakeInstantly()
    cid = hs.add("companies", name="Bounce Co", domain="bounce.example", country="Australia",
                 industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing", ROUND: "2"})
    pid = hs.add("contacts", email="p1@bounce.example", firstname="P", lastname="L", jobtitle="Buyer",
                 diablo_company_note="imports sweets", **{ORDER: "1", LS: "APPROVED_TO_SEND", LINE: "Line."})
    hs.links[pid] = [cid]
    instantly.campaigns["old"] = {"name": "Diablo | OCT2026"}
    instantly.leads["old"] = [{"id": "l1", "email": "p1@bounce.example", "status": -1,
                               "timestamp_created": "2026-10-20T10:00:00Z"}]
    shown = []
    send.run("test", settings(), hs, instantly, log=shown.append)
    assert not any("RESTART" in c["name"] for c in instantly.campaigns.values())
    assert any("bounced in an earlier campaign" in line for line in shown)
    assert hs.records["contacts"][pid][LS] == "APPROVED_TO_SEND"  # never marked as sent


def test_the_newest_lead_counts_and_a_bounce_anywhere_is_remembered():
    instantly = FakeInstantly()
    instantly.campaigns = {"a": {"name": "Diablo | OCT2026"}, "b": {"name": "Diablo | RESTART | NOV2026"}}
    instantly.leads = {"a": [{"email": "x@y.example", "status": -1, "timestamp_created": "2026-10-01T00:00:00Z"}],
                       "b": [{"email": "x@y.example", "status": 1, "timestamp_created": "2026-11-20T00:00:00Z"}]}
    view = instantly_view(instantly, "Diablo |")
    assert view["x@y.example"]["_campaign_id"] == "b" and view["x@y.example"]["_dead_anywhere"]


def test_a_new_person_whose_line_was_still_to_write_goes_straight_to_gate2(switched_on, monkeypatch):
    data = {"companies": {"9": {"round": 2, "started": "2026-11-20T00:00:00+00:00", "straight": ["55"]}}}
    assert restart.straight_to_gate2("55", data) and not restart.straight_to_gate2("56", data)


def test_the_counters_add_up_every_round():
    memory = {"contacts": {
        "1": {"company": "9", "round": 2, "introduced": "2026-11-20T00:00:00+00:00",
              "past": [{"introduced": "2026-10-01T00:00:00+00:00", "reminded": "2026-10-05T00:00:00+00:00"}]},
        "2": {"company": "9", "queued": "2026-11-21T00:00:00+00:00"}}}
    people, companies = restart.counts(memory)
    assert people == {"1": (2, 1), "2": (1, 0)} and companies == {"9": (3, 1)}


def _day_of_sending(on, monkeypatch):
    monkeypatch.setattr(stages, "restart_on", lambda settings=None: on)
    hs, instantly = crm(), FakeInstantly()
    for name, n in (("Alpha", 3), ("Beta", 1), ("Gamma", 2)):
        cid = hs.add("companies", name=name, domain=f"{name.lower()}.example", country="Australia",
                     industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing"})
        for rank in range(1, n + 1):
            pid = hs.add("contacts", email=f"p{rank}@{name.lower()}.example", firstname="P", lastname="L",
                         jobtitle="Buyer", diablo_company_note="imports sweets",
                         **{ORDER: str(rank), LS: "APPROVED_TO_SEND", LINE: "Line."})
            hs.links[pid] = [cid]
    send.run("test", settings(on=on), hs, instantly, log=quiet)
    leads = sorted((c["name"], l["email"]) for k, c in instantly.campaigns.items() for l in instantly.leads[k])
    counters = {"diablo_times_introduced", "diablo_times_reminded", "diablo_introductions_sent",
                "diablo_reminders_sent", ROUND}
    records = {obj: {i: {k: v for k, v in p.items() if k not in counters} for i, p in hs.records[obj].items()}
               for obj in ("companies", "contacts")}
    return leads, records, instantly.add_calls


def test_with_restarts_on_but_no_company_restarted_the_sending_is_exactly_the_same(monkeypatch):
    off = _day_of_sending(False, monkeypatch)
    send_memory.FILE.unlink(missing_ok=True)
    on = _day_of_sending(True, monkeypatch)
    assert on == off
    assert len(off[0]) == 3  # one introduction per company


# ---- automatic restarts and the 3-round limit (20 Nov 2026, Ariel) ---------------------------------------------


def waiting_company(hs, days_ago, rounds="1", people=None):
    """A company that closed with no reply days_ago and sits on "No response: can restart" (nobody touched it)."""
    cid, ids = closed_company(hs, days_ago, people=people)
    hs.records["companies"][cid].update({LS: RESTART_LABEL, ROUND: rounds})
    return cid, ids


def test_button_3_restarts_a_ready_company_by_itself_and_leaves_one_still_waiting(switched_on):
    hs, apollo = crm(), apollo_with_three()
    ready, ids = waiting_company(hs, 10)
    early, _ = waiting_company(hs, 5, people=(("q1", "Owner", NEW_P, 1),))
    hs.records["companies"][early]["domain"] = "early.example"
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert hs.records["companies"][ready][LS] == "Contact located. Queued for processing"
    assert hs.records["companies"][ready][ROUND] == "2"
    assert by_email(hs, "n1@harris.example")[LS] == "APPROVED_TO_SEND"  # new person 1, the same email as before
    assert hs.records["companies"][early][LS] == RESTART_LABEL  # its 9 days are not over: left alone
    assert any("Automatic restarts: 1 companies set to GATE1" in line and "1 more wait" in line for line in shown)


def test_with_automatic_off_a_ready_company_waits_for_a_person(switched_on):
    hs, apollo = crm(), apollo_with_three()
    cid, _ = waiting_company(hs, 10)
    s = settings()
    s["restart"]["automatic"] = False
    find_contacts.run("test", s, hs, apollo, log=quiet)
    assert hs.records["companies"][cid][LS] == RESTART_LABEL and apollo.revealed == []


def test_a_company_with_every_round_used_is_never_restarted(switched_on):
    hs, apollo = crm(), apollo_with_three()
    left, _ = waiting_company(hs, 20, rounds="3")
    find_contacts.run("test", settings(), hs, apollo, log=quiet)
    assert hs.records["companies"][left][LS] == RESTART_LABEL and apollo.revealed == []
    # Set to GATE1 by mistake: refused and put back on the final status.
    hs.records["companies"][left][LS] = "GATE1: Approved for outreach"
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert hs.records["companies"][left][LS] == OLD_C and apollo.revealed == []
    assert any("it has had all 3 rounds" in line for line in shown)


def test_only_the_channels_we_target_are_restarted_automatically(switched_on):
    """20 Nov 2026 (Ariel): a company from a channel we no longer target is never restarted; it is set to
    "Unqualified: Channel no longer targeted" instead."""
    hs, apollo = crm(), apollo_with_three()
    shop, _ = waiting_company(hs, 10)
    hs.records["companies"][shop]["industry_type"] = "Specialist retail"
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert hs.records["companies"][shop][LS] == "Unqualified: Channel no longer targeted"
    assert apollo.revealed == [] and by_email(hs, "p1@harris.example")[LS] != "APPROVED_TO_SEND"
    assert any("not one we target" in line for line in shown)


@pytest.mark.parametrize("industry", ["", "Other", "Grocery Retail"])
def test_a_company_whose_channel_is_not_known_waits_for_a_person(switched_on, industry):
    hs, apollo = crm(), apollo_with_three()
    cid, _ = waiting_company(hs, 10)
    hs.records["companies"][cid]["industry_type"] = industry
    shown = []
    find_contacts.run("test", settings(), hs, apollo, log=shown.append)
    assert hs.records["companies"][cid][LS] == RESTART_LABEL and apollo.revealed == []
    assert any("channel is not known" in line and "Harris Farm" in line for line in shown)


def test_the_targeted_channels():
    from outreach.common import targeted
    notes = {"a.example": {"category": "Health food distributors"}, "b.example": {"category": "Snack vending operators"},
             "c.example": {"category": "Confectionery importers"}, "d.example": {"category": "Retailers"}}
    assert targeted({"domain": "a.example"}, notes) and targeted({"domain": "c.example"}, notes)
    assert not targeted({"domain": "b.example"}, notes) and not targeted({"domain": "d.example"}, notes)
    assert targeted({"domain": "x.example", "industry_type": "Distributor Wholesaler"}, notes)
    assert not targeted({"domain": "x.example", "industry_type": "Specialist retail"}, notes)
    assert targeted({"domain": "x.example", "industry_type": "Grocery Retail"}, notes) is None  # not known
    assert targeted({"domain": "x.example"}, notes) is None


def test_a_company_where_someone_replied_is_not_restarted_automatically(switched_on):
    hs, apollo = crm(), apollo_with_three()
    cid, _ = waiting_company(hs, 20, people=(("p1", "Owner", "UNQUALIFIED_RESPONSE_NEGATIVE", 1),
                                              ("p2", "Buyer", NEW_P, 2)))
    find_contacts.run("test", settings(), hs, apollo, log=quiet)
    assert hs.records["companies"][cid][LS] == RESTART_LABEL and apollo.revealed == []


def test_the_move_to_can_restart_happens_only_once(switched_on):
    hs = crm()
    data = {"companies": {}}
    assert restart.migrate(hs, LeadStatus(hs), log=quiet, data=data)["companies"] == 0
    assert data["migrated"]
    cid = hs.add("companies", name="Finished Co", **{LS: OLD_C})  # used all its rounds since
    assert restart.migrate(hs, LeadStatus(hs), log=quiet, data=data) == {"companies": 0, "contacts": 0}
    assert hs.records["companies"][cid][LS] == OLD_C


def test_the_final_status_is_the_old_no_response_label(switched_on):
    hs = crm()
    statuses = LeadStatus(hs)
    assert statuses.final("companies")[LS] == OLD_C and statuses.final("contacts")[LS] == OLD_P
    assert statuses.can_restart("contacts", {"properties": {LS: NEW_P}})
    assert not statuses.can_restart("contacts", {"properties": {LS: OLD_P}})
    cfg = restart.config(settings())
    assert restart.finished({ROUND: "3"}, cfg) and not restart.finished({ROUND: "2"}, cfg)
    assert not restart.finished({}, cfg)  # an empty round is round 1


def test_fresh_companies_go_before_a_restarted_one_in_the_day_s_room(switched_on, monkeypatch):
    hs, instantly = crm(), FakeInstantly()
    old = hs.add("companies", name="Restarted Co", domain="re.example", country="Australia",
                 industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing", ROUND: "2"})
    fresh = hs.add("companies", name="Fresh Co", domain="fresh.example", country="Australia",
                   industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing"})
    for cid, dom in ((old, "re.example"), (fresh, "fresh.example")):
        pid = hs.add("contacts", email=f"p1@{dom}", firstname="P", lastname="L", jobtitle="Buyer",
                     diablo_company_note="imports sweets", **{ORDER: "1", LS: "APPROVED_TO_SEND", LINE: "Line."})
        hs.links[pid] = [cid]
    instantly.campaigns["old"] = {"name": "Diablo | OCT2026"}
    instantly.leads["old"] = [{"id": "l0", "email": "p9@re.example", "status": 3,
                               "timestamp_created": "2026-10-20T10:00:00Z",
                               "timestamp_last_contact": "2026-10-20T10:00:00Z"}]
    monkeypatch.setattr(chain, "room_today", lambda leads, limit, now=None: 1)  # room for one new company today
    shown = []
    send.run("test", settings(), hs, instantly, log=shown.append)
    added = [l["email"] for ls in instantly.leads.values() for l in ls if l["id"] != "l0"]
    assert added == ["p1@fresh.example"]
    assert any("Restarted Co: today's room for new introductions is used up" in line for line in shown)


def test_a_company_ending_its_last_round_with_no_reply_is_closed_for_good(switched_on, monkeypatch):
    from outreach import sync
    from .test_chain import started
    from .test_corrupt import ago as days_ago
    s = settings()
    hs, instantly, emails, cid, (p1, p2) = started(s, 20)
    hs.options[("companies", LS)][RESTART_LABEL] = RESTART_LABEL
    hs.options[("contacts", LS)][NEW_P] = RESTART_LABEL
    hs.records["contacts"][p2][LS] = NEW_P  # closed earlier in this round, 48 hours after their reminder
    hs.records["companies"][cid][ROUND] = "3"
    hs.records["contacts"][p1][LS] = "REMINDER_SENT"
    emails.campaign_email("p1@chain.example", days_ago(10), subject="Fwd: A sugar-free brand")
    shown = []
    sync.run("test", s, hs, instantly, log=shown.append, emails_api=emails)
    assert hs.records["companies"][cid][LS] == OLD_C  # never "can restart" again
    assert hs.records["contacts"][p1][LS] == OLD_P and hs.records["contacts"][p2][LS] == OLD_P
    assert any("all its rounds are used" in line for line in shown)
    # The same ending in round 2 still leaves the company on "can restart".
    hs2, instantly2, emails2, cid2, (q1, q2) = started(s, 20)
    hs2.options[("companies", LS)][RESTART_LABEL] = RESTART_LABEL
    hs2.options[("contacts", LS)][NEW_P] = RESTART_LABEL
    hs2.records["contacts"][q2][LS] = "UNQUALIFIED"
    hs2.records["companies"][cid2][ROUND] = "2"
    hs2.records["contacts"][q1][LS] = "REMINDER_SENT"
    emails2.campaign_email("p1@chain.example", days_ago(10), subject="Fwd: A sugar-free brand")
    sync.run("test", s, hs2, instantly2, log=quiet, emails_api=emails2)
    assert hs2.records["companies"][cid2][LS] == RESTART_LABEL


def test_button_4_s_sync_keeps_restarted_people_on_gate2_despite_their_old_leads(switched_on):
    from outreach import sync
    hs, instantly = crm(), FakeInstantly()
    cid, ids = waiting_company(hs, 10, people=(("p1", "Owner", NEW_P, 1), ("inbox", INBOX_TITLE, NEW_P, 2)))
    instantly.campaigns["old"] = {"name": "Diablo | OCT2026"}
    instantly.leads["old"] = [
        {"id": f"l{k}", "email": f"{k}@harris.example", "status": 3, "timestamp_created": "2026-10-20T10:00:00Z",
         "timestamp_last_contact": "2026-10-24T10:00:00Z"} for k in ("p1", "inbox")]
    find_contacts.run("test", settings(), hs, FakeApollo({}, {}), log=quiet)  # Apollo finds nobody new
    assert hs.records["contacts"][ids["p1"]][LS] == "APPROVED_TO_SEND"
    sync.run("test", settings(), hs, instantly, log=quiet)
    assert hs.records["contacts"][ids["p1"]][LS] == "APPROVED_TO_SEND"  # the October lead is not this round's
    assert hs.records["contacts"][ids["inbox"]][LS] == "APPROVED_TO_SEND"
    send.run("test", settings(), hs, instantly, log=quiet)
    restart_campaign = next(i for i, c in instantly.campaigns.items() if "RESTART" in c["name"])
    assert [l["email"] for l in instantly.leads[restart_campaign]] == ["p1@harris.example"]
    # Once the new round's lead is there, Instantly counts as usual.
    instantly.leads[restart_campaign][0]["timestamp_created"] = dt.datetime.now(dt.timezone.utc).isoformat()
    sync.run("test", settings(), hs, instantly, log=quiet)
    assert hs.records["contacts"][ids["p1"]][LS] != "APPROVED_TO_SEND"


def test_when_instantly_s_plan_is_full_the_leads_wait_on_gate2_and_the_run_carries_on(switched_on, monkeypatch):
    from outreach.instantly_client import InstantlyError
    hs, instantly = crm(), FakeInstantly()
    cid = hs.add("companies", name="Full Co", domain="full.example", country="Australia",
                 industry_type="Distributor Wholesaler", **{LS: "Contact located. Queued for processing"})
    pid = hs.add("contacts", email="p1@full.example", firstname="P", lastname="L", jobtitle="Buyer",
                 diablo_company_note="imports sweets", **{ORDER: "1", LS: "APPROVED_TO_SEND", LINE: "Line."})
    hs.links[pid] = [cid]

    def full(*a, **k):
        raise InstantlyError('POST /leads/add failed with 403: {"message":"Lead limit reached. Reamining uploads: 18."}')
    monkeypatch.setattr(instantly, "add_leads", full)
    shown = []
    out = send.run("test", settings(), hs, instantly, log=shown.append)
    assert out["plan_full"] and out["queued"] == 0
    assert hs.records["contacts"][pid][LS] == "APPROVED_TO_SEND"
    assert any("no uploads left" in line for line in shown)
    assert not send_memory.blocks_intro(send_memory.load(), pid)  # nothing remembered as sent


def test_a_restarted_person_is_not_closed_by_their_october_reminder(switched_on, monkeypatch):
    """20 Nov 2026: only the emails since the round started count for the reminder and the 48-hour close."""
    from outreach import sync
    from .test_chain import started
    from .test_corrupt import ago as days_ago
    s = settings()
    hs, instantly, emails, cid, (p1, p2) = started(s, 1)  # this round's introduction went yesterday
    hs.records["contacts"][p2]["hs_lead_status"] = "UNQUALIFIED"
    hs.records["companies"][cid][ROUND] = "2"
    emails.campaign_email("p1@chain.example", days_ago(30), subject="An earlier round")
    emails.campaign_email("p1@chain.example", days_ago(20), subject="Fwd: An earlier round")  # its old reminder
    restart.save({"companies": {str(cid): {"round": 2, "started": days_ago(1.5), "straight": []}},
                  "migrated": "2026-11-19"})
    sync.run("test", s, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["contacts"][p1][LS] == "ATTEMPTED_TO_CONTACT"  # not closed: this round has had no reminder yet
    assert not emails.forwards  # and its reminder is not due yet (4 days after this round's introduction)
    restart.save({"companies": {}, "migrated": "2026-11-19"})  # without the round, the old reminder would close them
    sync.run("test", s, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["contacts"][p1][LS] != "ATTEMPTED_TO_CONTACT"
