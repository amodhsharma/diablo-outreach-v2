"""25 Nov 2026 (Ariel): old records (created before October 2026) are checked with Apollo before their first email;
old company inboxes and addresses Apollo does not confirm become "Unqualified: Contact possibly corrupt"."""
from outreach import daily_report, old_records, send
from outreach.schema import STOP_REASON
from outreach.stages import LeadStatus

from .fakes import FakeApollo, FakeCRM, FakeInstantly
from .test_next_in_line import company_with_three, quiet, settings, tmp_runs  # noqa: F401

OLD, NEW = "2026-02-02T10:00:00Z", "2026-11-20T10:00:00Z"
LS = "hs_lead_status"


def world(settings, created=OLD, inbox=False):
    """Noble Foods with three approved people (p1, p2, p3 at noble.in), all old records unless `created` says."""
    hs = FakeCRM()
    cid, _ = company_with_three(hs, "Noble Foods", "noble.in")
    for c in hs.records["contacts"].values():
        c["createdate"] = created
        if inbox and c["email"] == "p1@noble.in":
            c["jobtitle"] = "Company inbox (from website)"
    return hs, cid


def ids(hs):
    return {c["email"]: cid for cid, c in hs.records["contacts"].items()}


def status(hs, email):
    return hs.records["contacts"][ids(hs)[email]][LS]


def apollo(**by_email):
    a = FakeApollo({}, {})
    a.by_email = by_email
    return a


def check(hs, settings, a):
    return old_records.check(hs, a, LeadStatus(hs), settings, log=quiet)


# ---- The check itself ----------------------------------------------------------------------------------

def test_1_a_verified_address_is_kept(settings):
    hs, _ = world(settings)
    out = check(hs, settings, apollo(**{"p1@noble.in": ("p1@noble.in", "verified")}))
    assert out["kept"] == 1 and status(hs, "p1@noble.in") == "APPROVED_TO_SEND"
    assert old_records.cleared(ids(hs)["p1@noble.in"])


def test_2_another_verified_address_is_switched_to(settings):
    hs, _ = world(settings)
    out = check(hs, settings, apollo(**{"p1@noble.in": ("pam@noble.in", "verified")}))
    assert out["switched"] == 1
    assert "pam@noble.in" in ids(hs) and status(hs, "pam@noble.in") == "APPROVED_TO_SEND"


def test_3_unknown_or_unverified_addresses_are_closed_as_possibly_corrupt(settings):
    hs, _ = world(settings)
    out = check(hs, settings, apollo(**{"p2@noble.in": ("p2@noble.in", "unavailable")}))
    assert out["closed"] == 3 and out["credits"] == 1
    for e in ("p1@noble.in", "p2@noble.in", "p3@noble.in"):
        assert status(hs, e) == "UNQUALIFIED_CONTACT_POSSIBLY_CORRUPT"
    reason = hs.records["contacts"][ids(hs)["p1@noble.in"]][STOP_REASON]
    assert reason.startswith("Possibly corrupt: Apollo does not hold this address (")
    assert "does not confirm this address (unavailable)" in hs.records["contacts"][ids(hs)["p2@noble.in"]][STOP_REASON]


def test_4_an_old_company_inbox_is_closed_without_asking_apollo(settings):
    hs, _ = world(settings, inbox=True)
    a = apollo(**{"p2@noble.in": ("p2@noble.in", "verified"), "p3@noble.in": ("p3@noble.in", "verified")})
    out = check(hs, settings, a)
    assert out["inboxes"] == 1 and "p1@noble.in" not in getattr(a, "matched", [])
    assert status(hs, "p1@noble.in") == "UNQUALIFIED_CONTACT_POSSIBLY_CORRUPT"
    assert "old company inbox from before October 2026" in hs.records["contacts"][ids(hs)["p1@noble.in"]][STOP_REASON]


def test_5_contacts_found_by_the_automation_are_never_checked(settings):
    hs, _ = world(settings, created=NEW)
    a = apollo()
    out = check(hs, settings, a)
    assert out == {"kept": 0, "switched": 0, "closed": 0, "inboxes": 0, "credits": 0, "left": 0, "unclear": 0}
    assert not getattr(a, "matched", [])


def test_6_each_address_is_checked_and_paid_for_once(settings):
    hs, _ = world(settings)
    a = apollo(**{e: (e, "verified") for e in ("p1@noble.in", "p2@noble.in", "p3@noble.in")})
    check(hs, settings, a)
    check(hs, settings, a)
    assert sorted(a.matched) == ["p1@noble.in", "p2@noble.in", "p3@noble.in"]


def test_7_an_old_record_already_emailed_is_left_alone(settings):
    from outreach import send_memory
    hs, _ = world(settings)
    memory = send_memory.load()
    memory["contacts"][str(ids(hs)["p1@noble.in"])] = {"introduced": "2026-11-10T10:00:00+00:00"}
    send_memory.save(memory)
    a = apollo()
    check(hs, settings, a)
    assert "p1@noble.in" not in a.matched and status(hs, "p1@noble.in") == "APPROVED_TO_SEND"


def test_8_the_run_limit_leaves_the_rest_for_the_next_run(settings):
    settings["contacts"]["old_records"] = {"per_run": 2}
    hs, _ = world(settings)
    a = apollo(**{e: (e, "verified") for e in ("p1@noble.in", "p2@noble.in", "p3@noble.in")})
    assert check(hs, settings, a)["left"] == 1
    assert check(hs, settings, a)["kept"] == 1


def test_9_without_the_new_status_nothing_is_closed(settings):
    hs, _ = world(settings)
    hs.options[("contacts", "hs_lead_status")].pop("UNQUALIFIED_CONTACT_POSSIBLY_CORRUPT")
    lines = []
    old_records.check(hs, apollo(), LeadStatus(hs), settings, log=lines.append)
    assert status(hs, "p1@noble.in") == "APPROVED_TO_SEND" and any("run button 1" in x for x in lines)


def test_9b_no_status_from_the_match_is_asked_again_by_person_id(settings):
    """25 Nov 2026: the live run got matches with no "email_status"; 88 people were closed by mistake."""
    hs, _ = world(settings)
    a = apollo(**{"p1@noble.in": ("p1@noble.in", None, "a1"), "p2@noble.in": ("p2@noble.in", None, "a2")})
    a.emails = {"a1": ("p1@noble.in", "verified")}  # Apollo's reveal by ID knows p1 only
    out = check(hs, settings, a)
    assert out["kept"] == 1 and status(hs, "p1@noble.in") == "APPROVED_TO_SEND"
    assert out["unclear"] == 1 and status(hs, "p2@noble.in") == "APPROVED_TO_SEND"  # never closed without a status
    assert not old_records.cleared(ids(hs)["p2@noble.in"])  # still held, asked again in 7 days
    a.matched = []
    check(hs, settings, a)
    assert a.matched == []  # not asked again (and not paid for) before then
    assert status(hs, "p3@noble.in") == "UNQUALIFIED_CONTACT_POSSIBLY_CORRUPT"  # Apollo does not hold p3 at all


# ---- Button 4 -------------------------------------------------------------------------------------------

def test_10_button_4_holds_an_old_record_until_it_is_checked(settings):
    hs, _ = world(settings)
    instantly, lines = FakeInstantly(), []
    assert send.run("test", settings, hs, instantly, log=lines.append)["queued"] == 0
    assert any("not checked with Apollo yet" in x for x in lines)
    check(hs, settings, apollo(**{"p1@noble.in": ("p1@noble.in", "verified")}))
    assert send.run("test", settings, hs, instantly, log=quiet)["queued"] == 1


def test_11_the_next_person_moves_up_when_the_first_is_possibly_corrupt(settings):
    hs, _ = world(settings)
    check(hs, settings, apollo(**{"p2@noble.in": ("p2@noble.in", "verified"), "p3@noble.in": ("p3@noble.in", "verified")}))
    instantly = FakeInstantly()
    send.run("test", settings, hs, instantly, log=quiet)
    sent = [lead["email"] for leads in instantly.leads.values() for lead in leads]
    assert sent == ["p2@noble.in"]


def test_12_contacts_found_by_the_automation_are_not_held(settings):
    hs, _ = world(settings, created=NEW)
    assert send.run("test", settings, hs, FakeInstantly(), log=quiet)["queued"] == 1


# ---- The daily email --------------------------------------------------------------------------------------

def test_13_the_daily_email_line(settings):
    old_records.save({"1": {"result": "kept", "on": "2026-11-25"}, "2": {"result": "switched", "on": "2026-11-25"},
                      "3": {"result": "possibly_corrupt", "on": "2026-11-25"},
                      "4": {"result": "possibly_corrupt", "on": "2026-11-24"}})
    assert old_records.on_day("2026-11-25") == {"kept": 1, "switched": 1, "closed": 1}
    assert old_records.on_day("2026-11-26") == {"kept": 0, "switched": 0, "closed": 0}
