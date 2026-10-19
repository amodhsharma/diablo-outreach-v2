"""Offline tests for jobs 3 to 5, run end to end against in-memory fakes."""

import pytest

from outreach import common, find_contacts, send, sync
from outreach.common import PRODUCTION_PORTAL_ID, PipelineError, clean_domain, load_settings

from .fakes import FakeApollo, FakeCRM, FakeInstantly


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    from outreach import find_contacts as _fc
    monkeypatch.setattr(_fc, "SKIPPED_FILE", tmp_path / "apollo_skipped.json")
    monkeypatch.setattr(_fc, "KEPT_FILE", tmp_path / "apollo_kept.json")
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
    s["send"]["booking_link"] = "https://book.example/diablo"  # the real link is not set yet ("xxx")
    return s


def test_clean_domain():
    assert clean_domain("https://www.NobleFoods.in/about?x=1") == "noblefoods.in"
    assert clean_domain("no domain") is None
    assert clean_domain("m.indiamart.com/foo") is None
    assert clean_domain(None) is None
    assert clean_domain("not a domain") is None


def test_target_guard():
    with pytest.raises(PipelineError):
        common.check_target(FakeCRM(portal=PRODUCTION_PORTAL_ID), "test")
    with pytest.raises(PipelineError):
        common.check_target(FakeCRM(portal=5), "live")
    assert common.check_target(FakeCRM(portal=5), "test") == 5


CO = "hs_lead_status"  # Lead Status, as stored (the live account's own values)


def approved_company(hs, **extra):
    props = dict(name="Noble Foods", domain="noblefoods.in", country="India",
                 industry_type="Distributor Wholesaler", hs_ideal_customer_profile="tier_1",
                 **{CO: "GATE1: Approved for outreach"})
    props.update(extra)
    return hs.add("companies", **props)


def full_pipeline(settings):
    hs = FakeCRM()
    noble = approved_company(hs)  # as the research import adds it, then gate 1 approved
    apollo = FakeApollo(
        {"noblefoods.in": [{"id": "p1", "title": "Sales Executive"}, {"id": "p2", "title": "Purchasing Manager"},
                           {"id": "p3", "title": "Category Manager"}, {"id": "p4", "title": "Intern"}]},
        {"p2": ("buyer@noblefoods.in", "verified"), "p3": ("cat@noblefoods.in", "unverified")},
    )
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    return hs, noble, apollo


def test_find_contacts_keeps_only_verified_and_ranks_titles(settings):
    hs, noble, apollo = full_pipeline(settings)
    assert apollo.revealed == ["p2", "p3", "p1"]  # best titles first
    contacts = list(hs.records["contacts"].values())
    assert [c["email"] for c in contacts] == ["buyer@noblefoods.in"]
    assert contacts[0][CO] == "NEW" and contacts[0]["lead_source"] == "AUTO-OUTREACH"
    assert contacts[0]["diablo_outreach_order"] == "1"
    assert not any(k.startswith("diablo_") and k not in ("diablo_outreach_order", "diablo_contact_source")
                   for k in contacts[0])
    assert contacts[0]["diablo_contact_source"] == "Apollo"  # the field exists in this (fake) account
    assert hs.records["companies"][noble][CO] == "GATE1: Approved for outreach"  # waits for gate 2 and the emails
    assert find_contacts.load_skipped(find_contacts.KEPT_FILE) == {"p2": next(iter(hs.records["contacts"]))}
    import json
    handed = json.loads(find_contacts.new_contacts_file().read_text())  # for step 3 of button 3
    assert handed == {"contact_ids": [str(next(iter(hs.records["contacts"])))]}


def test_find_contacts_never_adds_or_touches_an_existing_email(settings):
    hs = FakeCRM()
    company = approved_company(hs)
    team = hs.add("contacts", tagged=False, email="buyer@noblefoods.in", **{CO: "WON"})
    apollo = FakeApollo({"noblefoods.in": [{"id": "p2", "title": "Buyer"}]}, {"p2": ("buyer@noblefoods.in", "verified")})
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert list(hs.records["contacts"]) == [team]
    assert hs.records["contacts"][team] == {"email": "buyer@noblefoods.in", CO: "WON"}
    assert hs.records["companies"][company][CO] == "Missing Info"  # nobody new to email there
    assert all(team not in ids for _, _, ids in hs.writes)


def test_find_contacts_no_domain_credit_cap_and_untagged(settings):
    hs = FakeCRM()
    nodomain = approved_company(hs, name="S", domain="")
    a = approved_company(hs, name="A", domain="a.in")
    b = approved_company(hs, name="B", domain="b.in")
    team = hs.add("companies", tagged=False, name="T", domain="t.in", **{CO: "GATE1: Approved for outreach"})
    settings["contacts"]["max_credits_per_run"] = 1
    apollo = FakeApollo({"a.in": [{"id": "x"}], "b.in": [{"id": "y"}], "t.in": [{"id": "z"}]},
                        {"x": ("x@a.in", "verified"), "y": ("y@b.in", "verified"), "z": ("z@t.in", "verified")})
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert hs.records["companies"][nodomain][CO] == "Missing Info"
    assert len(hs.links) == 1 and hs.links[next(iter(hs.links))] == [a]
    assert hs.records["companies"][b][CO] == "GATE1: Approved for outreach"  # waits for next run
    assert "z" not in apollo.revealed and hs.records["companies"][team] == {
        "name": "T", "domain": "t.in", CO: "GATE1: Approved for outreach"}  # the team's record: never touched


def test_send_and_sync(settings):
    hs, noble, _ = full_pipeline(settings)
    contact_id = next(iter(hs.records["contacts"]))
    c = hs.records["contacts"][contact_id]
    c.update({"diablo_personal_line": "Your Reliance range has room for sugar free chocolate.", "diablo_company_note": "runs a health food aisle", CO: "NEW_PERSONAL_LINE_FILLED"})

    instantly = FakeInstantly()
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 0  # gate 2 not passed yet

    c[CO] = "APPROVED_TO_SEND"  # gate 2
    logs = []
    plan = send.run("test", settings, hs, None, dry_run=True, log=logs.append)
    assert plan["queued"] == 0 and plan["campaigns"][0]["leads"] == 1
    shown = "\n".join(logs)  # the whole email, filled in, is printed in the job log
    assert "Subject: A sugar-free brand with no India partner yet" in shown  # template 3 (15 Oct 2026)
    # Template 4 (19 Oct 2026): the full name, the fuller line after the note, the booking link above
    # the signature, which has its grey line; the hidden preview line is not shown.
    assert "Hi Firstp2" in shown and "as we noticed " in shown and (" runs a health food aisle. We are a UK brand "
           "without a direct partner in India yet, and we believe you could be the right partner for us there.") in shown
    assert "XXXXXX" not in shown and ("Book a quick meeting with us: book.example/diablo [https://book.example/diablo]\n\n"
                                      "Best regards,\n| Joshua\n| International Account Executive\n| Diablo Sugar Free") in shown
    assert "looking for a partner in" not in shown
    assert "office of the Strategy Director" in shown and "By way of introduction" in shown
    assert "{{" not in shown and "<br/>" not in shown
    assert "--- Email 2" not in shown  # later emails are sent by Sync, in rounds

    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1
    camp_id, body = next(iter(instantly.campaigns.items()))
    assert body["name"] == "Diablo | " + send.month_label()  # one campaign per month
    assert body["campaign_schedule"]["schedules"][0]["timezone"] == "Europe/Isle_of_Man"  # any time, every day
    assert body["campaign_schedule"]["schedules"][0]["timing"] == {"from": "00:00", "to": "23:59"}
    email = body["sequences"][0]["steps"][0]["variants"][0]["body"]
    assert "Best regards," in email and "{{privacy_url}}" not in email and "Privacy notice" not in email
    assert "<b>we are Europe's largest sugar-free confectionery company</b>" in email and "{{company_note}}" in email
    assert "Joshua<br/>International Account Executive<br/>Diablo Sugar Free</div>" in email
    assert "{{catalogue_link}}" not in email and "{{sender_phone}}" not in email
    assert "117 products across 11 categories" in email and "<div><ul>" not in email
    lead = instantly.leads[camp_id][0]
    assert lead["custom_variables"]["personal_line"].startswith("Your Reliance")  # kept for the forwards
    assert lead["custom_variables"]["company_note"] == "runs a health food aisle"
    assert lead["custom_variables"]["country_name"] == "India"
    assert lead["custom_variables"]["partner_type"] == "distributor"
    assert c[CO] == "ATTEMPTED_TO_CONTACT"
    assert hs.records["companies"][noble][CO] == "Attempted to Contact"

    # Sending again does not create a second campaign.
    c[CO] = "APPROVED_TO_SEND"
    send.run("test", settings, hs, instantly, log=quiet)
    assert len(instantly.campaigns) == 1
    c[CO] = "ATTEMPTED_TO_CONTACT"

    lead["timestamp_last_contact"] = "2026-10-05T05:00:00Z"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c[CO] == "ATTEMPTED_TO_CONTACT"

    lead["email_reply_count"] = 1
    lead["timestamp_last_reply"] = "2026-10-06T05:00:00Z"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c[CO] == "IN_PROGRESS"
    assert hs.records["companies"][noble][CO] == "In Progress"

    lead["status"] = -2
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c[CO] == "UNQUALIFIED"
    assert hs.records["companies"][noble][CO] == "Unqualified"

    lead["status"] = 1  # nothing moves backwards
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c[CO] == "UNQUALIFIED"

    # A person takes the company over (a Lead Status the pipeline does not use): never changed again.
    hs.records["companies"][noble][CO] = "Won"
    c[CO] = "IN_PROGRESS"
    lead["status"] = -2
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["companies"][noble][CO] == "Won"


def test_send_needs_sending_accounts(settings):
    settings["send"]["sending_accounts"] = []
    with pytest.raises(PipelineError):
        send.campaign_body("Diablo | India | X | 2026-10", "India", settings)


def test_lead_status_mapping():
    assert sync.lead_result({"status": -1}) == ("closed", None, "bounced")  # the others carry on
    assert sync.lead_result({"status": -2}) == ("closed", "closed", "unsubscribed")
    assert sync.lead_result({"lt_interest_status": 1}) == ("replied", "replied", "marked interested")
    assert sync.lead_result({"lt_interest_status": -1}) == ("closed", "closed", "marked not interested")
    assert sync.lead_result({"email_reply_count": 2}) == ("replied", "replied", "replied")
    assert sync.lead_result({}) == ("in_outreach", None, "queued")


def test_every_stage_has_a_live_lead_status_choice():
    from outreach.stages import LeadStatus, STAGES
    statuses = LeadStatus(FakeCRM())
    for obj, stages in STAGES.items():
        for stage in stages:
            assert statuses.stage(obj, statuses.value(obj, stage)) == stage
    assert statuses.stage("companies", "Won") == "team" and statuses.stage("contacts", "Emailed") == "team"
    assert statuses.value("contacts", "approved") == "APPROVED_TO_SEND"
    assert statuses.value("companies", "approved") == "GATE1: Approved for outreach"


def test_hierarchy_levels(settings):
    h = settings["contacts"]["hierarchy"]
    level = lambda t: find_contacts.hierarchy_level(t.lower(), h)[0]
    assert level("Chief Executive Officer") == level("Managing Director") == level("Founder & CEO") == 0
    assert level("COO") == level("Chief Commercial Officer") == 1
    assert level("Regional Director") == level("Director") == level("Vice President Sales") == 2
    assert level("Assistant Director") == level("Head - Procurement") == level("AVP") == 3
    assert level("Purchase Manager") == level("Channel Partner Manager") == 4
    assert level("Sales Executive") == level("Coordinator") == 5


def test_find_contacts_collects_the_top_four_once(settings):
    hs = FakeCRM()
    cid = approved_company(hs, name="Big Co", domain="big.in")
    titles = ["Sales Executive", "Purchase Manager", "Assistant Director", "Regional Director",
              "Chief Executive Officer", "Intern", "Area Sales Manager", "COO", "Accountant",
              "Head - Procurement", "Category Manager", "Director", "Senior Manager", "Store Keeper"]
    people = [{"id": f"p{i}", "title": t, "has_email": t != "Area Sales Manager",
               "seniority": "c_suite" if t in ("Chief Executive Officer", "COO") else "manager"}
              for i, t in enumerate(titles)]
    emails = {f"p{i}": (f"p{i}@big.in", "unverified" if t == "Director" else "verified")
              for i, t in enumerate(titles)}
    apollo = FakeApollo({"big.in": people}, emails)
    summary = find_contacts.run("test", settings, hs, apollo, log=quiet)

    def ranked():
        return [c["jobtitle"] for c in sorted(hs.records["contacts"].values(),
                                              key=lambda c: int(c["diablo_outreach_order"]))]
    assert ranked() == ["Chief Executive Officer", "COO", "Regional Director", "Assistant Director"]  # top 4
    assert summary["rows"][0]["verified"] == 4 and len(apollo.revealed) == 5  # one revealed was unverified
    assert hs.records["companies"][cid][CO] == "GATE1: Approved for outreach"

    # A second run leaves a company that already has its contacts alone (no Apollo spend).
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert len(hs.records["contacts"]) == 4 and len(apollo.revealed) == 5


def test_send_reports_leads_instantly_skipped(settings):
    hs = FakeCRM()
    cid = approved_company(hs, name="Co", domain="co.in")
    contact = hs.add("contacts", email="old@co.in", firstname="A", diablo_personal_line="L", diablo_company_note="imports European sweets",
                     **{CO: "APPROVED_TO_SEND"})
    hs.links[contact] = [cid]
    inst = FakeInstantly()
    inst.create_campaign({"name": "Older test"})
    inst.leads["camp1"].append({"email": "old@co.in"})  # already somewhere in the workspace
    logs = []
    result = send.run("test", settings, hs, inst, log=logs.append)
    assert result["queued"] == 0
    assert hs.records["contacts"][contact][CO] == "APPROVED_TO_SEND"
    assert any("0 leads added, 1 skipped" in line for line in logs)


def test_time_zones_instantly_accepts():
    from outreach.instantly_timezones import ALLOWED, instantly_timezone
    assert instantly_timezone("Europe/London") == "Europe/Isle_of_Man"
    assert instantly_timezone("Europe/Dublin") == "Europe/Isle_of_Man"
    assert instantly_timezone("Asia/Kolkata") == "Asia/Kolkata"
    assert instantly_timezone("Europe/Paris") == "Europe/Belgrade"
    assert instantly_timezone("Europe/Copenhagen") == "Europe/Belgrade"
    assert instantly_timezone("Africa/Nairobi") == "Africa/Addis_Ababa"
    assert instantly_timezone("Europe/Athens") in ALLOWED
    for tz in ("Asia/Tokyo", "America/New_York", "Asia/Riyadh", "Asia/Singapore"):
        assert instantly_timezone(tz) in ALLOWED


def test_email_body_in_paragraphs_and_old_campaigns_refreshed(settings):
    from .fakes import FakeInstantly
    steps = send.sequence_steps(settings["send"])
    body = steps[0]["variants"][0]["body"]
    gap = "<div><br></div>"
    assert body.startswith('<div><div style="display:none')  # the hidden inbox preview line (19 Oct 2026)
    assert ("Europe's largest sugar-free confectionery company, looking for a partner in {{market_country}}</div>"
            f"Hi {{{{full_name}}}},</div>{gap}<div>I'm writing from the office of the Strategy Director") in body
    assert f"Holland & Barrett</b>.</div>{gap}<div>Here is the link to our catalogue" in body
    assert "<br/><br/>" not in body
    assert ('<div>Book a quick meeting with us: <a href="https://book.example/diablo">book.example/diablo</a></div>'
            f'{gap}<div>Best regards,<div style="border-left:3px solid #cccccc;padding-left:10px;margin:4px 0 0 2px">'
            'Joshua<br/>International Account Executive<br/>Diablo Sugar Free</div></div>') in body
    shown = send.render(body, {"first_name": "Ann"})
    assert "\n\nWould this week work, or would next week be better suited?\n\nBook a quick meeting" in shown
    instantly = FakeInstantly()
    old = instantly.create_campaign({"name": "Diablo | Dublin, Ireland | Retailers | OCT2026",
                                     "sequences": [{"steps": [{"variants": [{"subject": "{{subject_line}}", "body": ""}]}]}]})
    instantly.create_campaign({"name": "Someone else's campaign", "sequences": []})
    assert send.refresh_campaign_content(instantly, settings, log=quiet) == 1
    assert instantly.campaigns[old["id"]]["sequences"][0]["steps"][0]["variants"][0]["body"] == body
    assert send.refresh_campaign_content(instantly, settings, log=quiet) == 0  # already up to date


def test_created_leads_matched_by_position():
    leads = [{"email": "A@x.com"}, {"email": "b@y.com"}]
    # Instantly may return created_leads without the email filled in.
    results = [{"leads_uploaded": 1, "total_sent": 2, "created_leads": [{"index": 1, "id": "u1", "email": None}]}]
    assert send.created_emails(results, leads) == {"b@y.com"}
    assert send.created_emails([{"leads_uploaded": 2, "created_leads": []}], leads) == {"a@x.com", "b@y.com"}
    assert send.created_emails([{"leads_uploaded": 0, "skipped_count": 2, "created_leads": []}], leads) == set()


def test_send_says_why_a_contact_is_skipped(settings):
    hs = FakeCRM()
    hs.add("contacts", email="solo@x.com", diablo_personal_line="Line.", diablo_company_note="imports European sweets", **{CO: "APPROVED_TO_SEND"})
    team_co = hs.add("companies", tagged=False, name="Team Co", domain="team.in", **{CO: "In Progress"})
    linked = hs.add("contacts", email="at@team.in", diablo_personal_line="Line.", diablo_company_note="imports European sweets", **{CO: "APPROVED_TO_SEND"})
    hs.links[linked] = [team_co]
    messages = []
    send.run("test", settings, hs, None, dry_run=True, log=messages.append)
    assert any("not linked to an AUTO-OUTREACH company" in m and "s***@x.com" in m for m in messages)
    assert any("not linked to an AUTO-OUTREACH company" in m and "a***@team.in" in m for m in messages)
    assert send.mask("buyer@shop.ie") == "b***@shop.ie"


# ---- the AUTO-OUTREACH safety rule ---------------------------------------------------------

def test_guard_refuses_to_change_untagged_records():
    from outreach.hubspot_client import TagGuardError
    hs = FakeCRM()
    ours = hs.add("companies", name="Ours", **{CO: "New"})
    theirs = hs.add("companies", tagged=False, name="Theirs", **{CO: "New"})
    with pytest.raises(TagGuardError, match="SAFETY STOP"):
        hs.update_tagged("companies", [(ours, {CO: "Unqualified"}), (theirs, {CO: "Unqualified"})])
    assert hs.records["companies"][ours][CO] == "New"  # nothing at all was saved
    assert hs.records["companies"][theirs][CO] == "New"
    with pytest.raises(TagGuardError):
        hs.update_tagged("companies", [(ours, {"lead_source": "Apollo"})])  # the tag itself never changes
    with pytest.raises(TagGuardError):
        hs.update_tagged("companies", [("424242", {CO: "New"})])  # a record that does not exist
    contact = hs.add("contacts", tagged=False, email="x@y.com")
    with pytest.raises(TagGuardError):
        hs.associate_tagged("contacts", "companies", [(contact, ours)])
    assert hs.writes == []
    made = hs.create_tagged("companies", [{"name": "New Co", "lead_source": "Apollo"}])
    assert hs.records["companies"][made[0]["id"]]["lead_source"] == "AUTO-OUTREACH"
    assert [r["id"] for r in hs.tagged_search("companies", [], ["name"])] == [ours, made[0]["id"]]


def test_sync_ignores_the_teams_contacts(settings):
    hs = FakeCRM()
    team = hs.add("contacts", tagged=False, email="theirs@shop.ie", **{CO: "NEW"})
    instantly = FakeInstantly()
    camp = instantly.create_campaign({"name": "Diablo | OCT2026"})["id"]
    instantly.leads[camp].append({"email": "theirs@shop.ie", "status": -2, "email_reply_count": 1})
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["contacts"][team] == {"email": "theirs@shop.ie", CO: "NEW"}
    assert hs.writes == []


def test_no_job_can_write_to_hubspot_without_the_guard():
    """Only hubspot_client.py (the guard) and setup_hubspot.py (fields, never records) may call
    HubSpot's write endpoints; every job finds its work with tagged_search."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "outreach"
    raw_writes = re.compile(r"\._batch_update\(|\._batch_create\(|\._associate_default\(|hs\.request\(|ensure_option")
    plain_search = re.compile(r"\bhs\.search\(")
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name in ("hubspot_client.py", "setup_hubspot.py"):
            continue
        assert not raw_writes.search(text), f"{path.name} calls HubSpot directly"
        if path.name not in ("import_research.py", "known_companies.py"):  # duplicate checks: read only
            assert not plain_search.search(text), f"{path.name} searches without the AUTO-OUTREACH filter"
        for name in ("batch_update(", "batch_create(", "associate_default("):
            assert f"hs.{name}" not in text, f"{path.name} uses hs.{name}"


def test_a_colleague_unsubscribing_keeps_a_warm_company_warm(settings):
    hs = FakeCRM()
    co = approved_company(hs, **{CO: "In Progress"})
    talker = hs.add("contacts", email="a@noblefoods.in", **{CO: "IN_PROGRESS"})
    other = hs.add("contacts", email="b@noblefoods.in", **{CO: "ATTEMPTED_TO_CONTACT"})
    hs.links[talker], hs.links[other] = [co], [co]
    instantly = FakeInstantly()
    camp = instantly.create_campaign({"name": "Diablo | OCT2026"})["id"]
    instantly.leads[camp] += [{"email": "a@noblefoods.in", "email_reply_count": 1},
                              {"email": "b@noblefoods.in", "status": -2}]
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["contacts"][other][CO] == "UNQUALIFIED"
    assert hs.records["companies"][co][CO] == "In Progress"


def test_the_auto_outreach_company_is_used_when_hubspot_links_another(settings):
    hs = FakeCRM()
    team = hs.add("companies", tagged=False, name="Parent Group", domain="group.com", **{CO: "Won"})
    ours = approved_company(hs)
    contact = hs.add("contacts", email="buyer@group.com", diablo_personal_line="Line.", diablo_company_note="imports European sweets", **{CO: "APPROVED_TO_SEND"})
    hs.links[contact] = [team, ours]  # HubSpot linked the email's domain by itself, first
    instantly = FakeInstantly()
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 1
    assert hs.records["companies"][ours][CO] == "Attempted to Contact"
    assert hs.records["companies"][team] == {"name": "Parent Group", "domain": "group.com", CO: "Won"}


def test_a_contact_rejected_at_gate_two_is_skipped_not_a_stop():
    from outreach.next_in_line import decide
    person = lambda pid, rank, state: {"id": pid, "properties": {"diablo_outreach_order": str(rank)},
                                       "state": state, "sent_at": None, "campaign": None}
    due, why = decide([person("a", 1, "skipped"), person("b", 2, "approved")], "approved", 3)
    assert why == "next" and due["id"] == "b"


def test_paid_lookups_are_saved_even_when_hubspot_refuses_a_contact(settings, monkeypatch):
    from outreach.hubspot_client import HubSpotError
    hs = FakeCRM()
    approved_company(hs)
    real = hs._batch_create

    def picky(object_type, records):
        if object_type == "contacts" and any(r["email"].startswith("dup") for r in records):
            raise HubSpotError("409 Conflict")
        return real(object_type, records)
    hs._batch_create = picky
    apollo = FakeApollo({"noblefoods.in": [{"id": "p1", "title": "CEO"}, {"id": "p2", "title": "Director"}]},
                        {"p1": ("dup@noblefoods.in", "verified"), "p2": ("ok@noblefoods.in", "verified")})
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert [c["email"] for c in hs.records["contacts"].values()] == ["ok@noblefoods.in"]
    kept = find_contacts.load_skipped(find_contacts.KEPT_FILE)
    assert kept["p1"] == "not added" and kept["p2"] in hs.records["contacts"]
