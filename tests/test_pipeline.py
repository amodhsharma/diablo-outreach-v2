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
    monkeypatch.setattr(common, "NOTES_FILE", tmp_path / "company_notes.json")


@pytest.fixture
def settings():
    s = load_settings()
    s["send"]["sending_accounts"] = ["ariel@getdiablo-test.com"]
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


def full_pipeline(settings):
    hs = FakeCRM()
    # As the research import adds it, then gate 1 approved.
    noble = hs.add("companies", name="Noble Foods", domain="noblefoods.in", country="India",
                   diablo_market="India", diablo_channel_category="grocery_wholesaler",
                   diablo_tier="tier_1", diablo_outreach_status="approved")

    apollo = FakeApollo(
        {"noblefoods.in": [{"id": "p1", "title": "Sales Executive"}, {"id": "p2", "title": "Purchasing Manager"},
                           {"id": "p3", "title": "Category Manager"}, {"id": "p4", "title": "Intern"}]},
        {"p2": ("buyer@noblefoods.in", "verified"), "p3": ("cat@noblefoods.in", "unverified")},
    )
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    return hs, noble, apollo


def test_find_contacts_keeps_only_verified_and_ranks_titles(settings):
    hs, noble, apollo = full_pipeline(settings)
    assert apollo.revealed == ["p2", "p3", "p1"]  # best titles first, 3 per company
    contacts = list(hs.records["contacts"].values())
    assert [c["email"] for c in contacts] == ["buyer@noblefoods.in"]
    assert contacts[0]["diablo_contact_status"] == "contact_found"
    assert hs.records["companies"][noble]["diablo_outreach_status"] == "contacts_found"


def test_find_contacts_never_readds_opted_out(settings):
    hs = FakeCRM()
    company = hs.add("companies", name="Noble Foods", domain="noblefoods.in", diablo_company_key="noblefoods.in",
                     diablo_outreach_status="approved", diablo_channel_category="grocery_wholesaler")
    hs.add("contacts", email="buyer@noblefoods.in", diablo_contact_status="opted_out")
    apollo = FakeApollo({"noblefoods.in": [{"id": "p2", "title": "Buyer"}]}, {"p2": ("buyer@noblefoods.in", "verified")})
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    statuses = [c["diablo_contact_status"] for c in hs.records["contacts"].values()]
    assert statuses == ["opted_out"]
    assert hs.records["companies"][company]["diablo_outreach_status"] == "contacts_found"


def test_find_contacts_suppressed_and_credit_cap(settings):
    hs = FakeCRM()
    sup = hs.add("companies", name="S", domain="s.in", diablo_company_key="s.in",
                 diablo_outreach_status="approved", diablo_suppress_reason="customer")
    a = hs.add("companies", name="A", domain="a.in", diablo_company_key="a.in", diablo_outreach_status="approved")
    b = hs.add("companies", name="B", domain="b.in", diablo_company_key="b.in", diablo_outreach_status="approved")
    settings["contacts"]["max_credits_per_run"] = 1
    apollo = FakeApollo({"a.in": [{"id": "x"}], "b.in": [{"id": "y"}]},
                        {"x": ("x@a.in", "verified"), "y": ("y@b.in", "verified")})
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert hs.records["companies"][sup]["diablo_outreach_status"] == "suppressed"
    assert hs.records["companies"][a]["diablo_outreach_status"] == "contacts_found"
    assert hs.records["companies"][b]["diablo_outreach_status"] == "approved"  # waits for next run


def test_send_and_sync(settings):
    hs, noble, _ = full_pipeline(settings)
    contact_id = next(iter(hs.records["contacts"]))

    # The email lines skill is not built yet: set the lines as it will.
    c = hs.records["contacts"][contact_id]
    c.update({"diablo_subject_line": "Swiss chocolate, and sugar free",
              "diablo_personal_line": "Your Reliance range has room for sugar free chocolate.",
              "diablo_contact_status": "copy_ready"})

    instantly = FakeInstantly()
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 0  # gate 2 not passed yet

    c["diablo_contact_status"] = "approved_to_send"  # gate 2
    logs = []
    plan = send.run("test", settings, hs, None, dry_run=True, log=logs.append)
    assert plan["queued"] == 0 and plan["campaigns"][0]["leads"] == 1
    shown = "\n".join(logs)  # the whole email, filled in, is printed in the job log
    assert "Subject: Swiss chocolate, and sugar free" in shown or "Subject: Swiss chocolate" in shown
    assert "Hi Firstp2," in shown and "Your Reliance range has room for sugar free chocolate." in shown
    assert "distribution partner in India" in shown and "Team at Diablo" in shown
    assert "{{" not in shown and "<br/>" not in shown
    assert "Email 2 (sent 3 days later if no reply)" in shown

    result = send.run("test", settings, hs, instantly, log=quiet)
    assert result["queued"] == 1
    camp_id, body = next(iter(instantly.campaigns.items()))
    assert body["name"] == "Diablo | " + send.month_label()  # one campaign per month
    assert body["campaign_schedule"]["schedules"][0]["timezone"] == "Europe/Isle_of_Man"  # any time, every day
    assert body["campaign_schedule"]["schedules"][0]["timing"] == {"from": "00:00", "to": "23:59"}
    email = body["sequences"][0]["steps"][0]["variants"][0]["body"]
    assert "Best,<br/>Team at Diablo" in email and "{{privacy_url}}" not in email
    lead = instantly.leads[camp_id][0]
    assert lead["custom_variables"]["personal_line"].startswith("Your Reliance")
    assert c["diablo_contact_status"] == "queued"
    assert hs.records["companies"][noble]["diablo_outreach_status"] == "in_outreach"

    # Sending again does not create a second campaign.
    c["diablo_contact_status"] = "approved_to_send"
    send.run("test", settings, hs, instantly, log=quiet)
    assert len(instantly.campaigns) == 1

    lead["timestamp_last_contact"] = "2026-10-05T05:00:00Z"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c["diablo_contact_status"] == "sent"

    lead["email_reply_count"] = 1
    lead["timestamp_last_reply"] = "2026-10-06T05:00:00Z"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c["diablo_contact_status"] == "replied"
    assert hs.records["companies"][noble]["diablo_outreach_status"] == "replied"

    lead["status"] = -2
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c["diablo_contact_status"] == "opted_out"
    assert hs.records["companies"][noble]["diablo_suppress_reason"] == "opted_out"

    lead["status"] = 1  # nothing moves backwards
    sync.run("test", settings, hs, instantly, log=quiet)
    assert c["diablo_contact_status"] == "opted_out"


def test_send_needs_sending_accounts(settings):
    settings["send"]["sending_accounts"] = []
    with pytest.raises(PipelineError):
        send.campaign_body("Diablo | India | X | 2026-10", "India", settings)


def test_lead_status_mapping():
    assert sync.lead_status({"status": -1}) == ("bounced", "bounced")
    assert sync.lead_status({"lt_interest_status": 1}) == ("interested", "marked_interested")
    assert sync.lead_status({"email_reply_count": 2}) == ("replied", "reply_received")
    assert sync.lead_status({}) == ("queued", "queued")


def test_all_status_values_exist_in_schema():
    from outreach.schema import COMPANY_STATUSES, CONTACT_STATUSES, SUPPRESS_REASONS
    from outreach.common import enum_value

    contact = {enum_value(s) for s in CONTACT_STATUSES}
    company = {enum_value(s) for s in COMPANY_STATUSES}
    assert {k for k in sync.RANK if k} <= contact
    assert set(sync.COMPANY_RANK) <= company
    assert "opted_out" in {enum_value(s) for s in SUPPRESS_REASONS}


def test_hierarchy_levels(settings):
    h = settings["contacts"]["hierarchy"]
    level = lambda t: find_contacts.hierarchy_level(t.lower(), h)[0]
    assert level("Chief Executive Officer") == level("Managing Director") == level("Founder & CEO") == 0
    assert level("COO") == level("Chief Commercial Officer") == 1
    assert level("Regional Director") == level("Director") == level("Vice President Sales") == 2
    assert level("Assistant Director") == level("Head - Procurement") == level("AVP") == 3
    assert level("Purchase Manager") == level("Channel Partner Manager") == 4
    assert level("Sales Executive") == level("Coordinator") == 5


def test_find_contacts_collects_top_three_then_goes_deeper(settings):
    hs = FakeCRM()
    cid = hs.add("companies", name="Big Co", domain="big.in", diablo_company_key="big.in",
                 diablo_market="India", diablo_outreach_status="approved")
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
                                              key=lambda c: int(c["diablo_hierarchy_rank"]))]
    assert ranked() == ["Chief Executive Officer", "COO", "Regional Director"]  # top 3, most senior first
    assert summary["rows"][0]["verified"] == 3 and len(apollo.revealed) == 3
    assert hs.records["companies"][cid]["diablo_outreach_status"] == "contacts_found"

    # Nobody replied: set the company back to Approved and run again for the next three.
    hs.records["companies"][cid]["diablo_outreach_status"] = "approved"
    find_contacts.run("test", settings, hs, apollo, log=quiet)
    assert ranked() == ["Chief Executive Officer", "COO", "Regional Director", "Assistant Director",
                        "Head - Procurement", "Senior Manager"]  # ranks 4 to 6
    assert len(apollo.revealed) == len(set(apollo.revealed)) == 7  # nobody paid for twice (incl. one unverified)
    assert "p5" not in apollo.revealed and "p6" not in apollo.revealed  # interns; no email in Apollo


def test_send_reports_leads_instantly_skipped(settings):
    hs = FakeCRM()
    cid = hs.add("companies", name="Co", domain="co.in", diablo_market="India",
                 diablo_channel_category="grocery_wholesaler", diablo_outreach_status="contacts_found")
    contact = hs.add("contacts", email="old@co.in", firstname="A", diablo_contact_status="approved_to_send",
                     diablo_subject_line="S", diablo_personal_line="L")
    hs.links[contact] = [cid]
    inst = FakeInstantly()
    inst.create_campaign({"name": "Older test"})
    inst.leads["camp1"].append({"email": "old@co.in"})  # already somewhere in the workspace
    logs = []
    result = send.run("test", settings, hs, inst, log=logs.append)
    assert result["queued"] == 0
    assert hs.records["contacts"][contact]["diablo_contact_status"] == "approved_to_send"
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
    assert body.startswith("<p>Hi {{firstName}},</p><p>{{personal_line}}</p>")
    assert "<br/><br/>" not in body and "<p>Best,<br/>Team at Diablo</p>" in body
    assert "\n\nWould you" in send.render(body, {"first_name": "Ann"})
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
    hs, apollo = FakeCRM(), None
    lone = hs.add("contacts", email="solo@x.com", diablo_contact_status="approved_to_send",
                  diablo_personal_line="Line.", diablo_subject_line="Hi there friend")
    messages = []
    send.run("test", settings, hs, None, dry_run=True, log=messages.append)
    assert any("not linked to a company" in m and "s***@x.com" in m for m in messages)
    assert send.mask("buyer@shop.ie") == "b***@shop.ie"
