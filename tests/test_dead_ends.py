"""The dead ends each with their own "Unqualified:" label, and the contacts marked Rejected/Redirected by
company owner (agreed 2 Nov 2026, Ariel)."""

from outreach import corrupt, find_contacts, redirect, send, sync
from outreach.common import load_settings

from .fakes import FakeApollo, FakeCRM, FakeInstantly
from .test_corrupt import LS, ORDER, REASON, ago, company, lead, quiet, rec, settings, started  # noqa: F401

REDIRECTED = "UNQUALIFIED_REDIRECTED"


def button_3(hs):
    return find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)


def emailed(instantly):
    return {l["email"] for ls in instantly.leads.values() for l in ls}


# ---- Past records get their exact label at the next run of button 4 -------------------------------

def test_a_past_no_gets_its_own_labels_on_the_person_the_company_and_the_others(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "past.example", ("Owner", "Buyer"))
    lead(instantly, "p1@past.example").update(lt_interest_status=-1, email_reply_count=1)
    rec(hs, p1)[LS] = "UNQUALIFIED"  # as before 2 Nov 2026
    rec(hs, p2)[LS] = "UNQUALIFIED_COMPANY"
    hs.records["companies"][cid][LS] = "Unqualified"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_RESPONSE_NEGATIVE"
    assert hs.records["companies"][cid][LS] == "Unqualified: Employee response negative"
    assert rec(hs, p2)[LS] == "COLLEAGUE_REPLIED_NEGATIVE"  # now labelled "Unqualified: Colleague response negative"


def test_the_others_at_a_company_that_never_replied_get_their_own_label(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "quiet.example", ("Owner", "Buyer"))
    rec(hs, p1)[LS] = "CONTACTED_NO_RESPONSE_UNQUALIFIED"
    rec(hs, p2)[LS] = "UNQUALIFIED_COMPANY"  # as before 2 Nov 2026
    hs.records["companies"][cid][LS] = "Contacted, but no response, unqualified"
    sync.run("test", settings, hs, instantly, log=quiet)
    assert rec(hs, p2)[LS] == "COLLEAGUE_CONTACTED_NO_RESPONSE"
    assert rec(hs, p1)[LS] == "CONTACTED_NO_RESPONSE_UNQUALIFIED"


def test_a_company_you_rejected_keeps_plain_unqualified(settings):
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Nope", "nope.example", ("Owner", "Buyer"))
    hs.records["companies"][cid][LS] = "Unqualified"
    instantly = FakeInstantly()
    instantly.create_campaign({"name": "Diablo | NOV2026"})
    instantly.leads[next(iter(instantly.leads))].append({"email": "someone@else.example"})
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["companies"][cid][LS] == "Unqualified"
    assert rec(hs, p1)[LS] == rec(hs, p2)[LS] == "UNQUALIFIED_COMPANY"


def test_the_team_s_own_unqualified_records_are_never_touched(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "team.example", ("Owner", "Buyer"))
    theirs = hs.add("companies", tagged=False, name="Team Co", hs_lead_status="Unqualified")
    lead(instantly, "p1@team.example").update(lt_interest_status=-1, email_reply_count=1)
    sync.run("test", settings, hs, instantly, log=quiet)
    assert hs.records["companies"][theirs][LS] == "Unqualified"


# ---- Rejected/Redirected by company owner ------------------------------------------------------------

def test_redirected_to_someone_added_by_hand(settings, monkeypatch):
    """Ariel's case: the person is unavailable, the automatic reply names someone else. He adds that person
    (AUTO-OUTREACH, linked, nothing else) and marks the original Rejected/Redirected."""
    hs, instantly, emails, cid, (p1, p2) = started(settings, "away.example", ("Owner", "Buyer"))
    new = hs.add("contacts", email="cover@away.example", firstname="C", lastname="Over", jobtitle="Head of Buying")
    hs.links[new] = [cid]
    rec(hs, p1)[LS] = REDIRECTED

    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # button 4 before button 3
    assert "p2@away.example" not in emailed(instantly)  # the backup is held back

    out = button_3(hs)
    assert out is not None
    assert rec(hs, p1)[ORDER] == "0" and rec(hs, p1)[REASON].startswith("Rejected/Redirected")
    assert rec(hs, new)[ORDER] == "1" and rec(hs, new)[LS] == "NEW"  # first, and its line gets written
    assert rec(hs, p2)[ORDER] == "2" and rec(hs, p2)[LS] == "APPROVED_TO_SEND"
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert corrupt.waiting_for_line(new)

    monkeypatch.setenv("GITHUB_RUN_ID", "run2")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    # 2 Nov 2026: person 1's line is copied over, so the person added goes to GATE2 and is emailed at once
    assert rec(hs, new)["diablo_personal_line"] == rec(hs, p1)["diablo_personal_line"]
    assert moved["next_contacts_added"] == 1 and rec(hs, new)[LS] == "ATTEMPTED_TO_CONTACT"
    assert "p2@away.example" not in emailed(instantly)  # the backup comes 3 days later
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"


def test_redirected_with_a_backup_who_has_a_line(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "leave.example", ("Owner", "Buyer"))
    rec(hs, p2)[LS] = "NEW_PERSONAL_LINE_FILLED"
    rec(hs, p1)[LS] = REDIRECTED
    monkeypatch.setenv("GITHUB_RUN_ID", "run1")
    button_3(hs)
    assert rec(hs, p2)[ORDER] == "1" and rec(hs, p2)[LS] == "APPROVED_TO_SEND"
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert moved["next_contacts_added"] == 1 and rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"
    assert rec(hs, p1)[LS] == REDIRECTED  # never changed again


def test_redirected_with_nobody_left(settings):
    hs, instantly, emails, cid, (p1,) = started(settings, "solo.example", ("Owner",))
    rec(hs, p1)[LS] = REDIRECTED
    button_3(hs)
    assert rec(hs, p1)[ORDER] == "0"
    assert hs.records["companies"][cid][LS] == "Unqualified: One contact inputted, which is unavailable"


def test_a_person_added_without_an_email_holds_the_company_back(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "noemail.example", ("Owner", "Buyer"))
    new = hs.add("contacts", firstname="No", lastname="Address", jobtitle="Buyer")
    hs.links[new] = [cid]
    rec(hs, p1)[LS] = REDIRECTED
    out = redirect.run(hs, sync.LeadStatus(hs), log=quiet)
    assert out["no_email"] == ["Noemail"] and "no email address" in redirect.summary(out)
    assert rec(hs, p1)[ORDER] == "1" and hs.records["companies"][cid][LS] == "Attempted to Contact"


def test_a_redirected_contact_is_moved_only_once(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "once.example", ("Owner", "Buyer"))
    rec(hs, p1)[LS] = REDIRECTED
    statuses = sync.LeadStatus(hs)
    assert redirect.run(hs, statuses, log=quiet)["redirected"] == 1
    assert redirect.run(hs, statuses, log=quiet)["redirected"] == 0


def test_send_skips_a_redirected_contact(settings):
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Skip", "skip.example", ("Owner", "Buyer"))
    rec(hs, p1)[LS] = REDIRECTED
    rec(hs, p1)[ORDER] = "0"
    rec(hs, p2)[ORDER] = "1"
    instantly = FakeInstantly()
    send.run("test", settings, hs, instantly, log=quiet)
    assert "p1@skip.example" not in emailed(instantly)


def test_before_button_1_the_old_labels_still_work():
    """Until button 1 renames them, the old labels are still read as the same steps (2 Nov 2026)."""
    from outreach.stages import LeadStatus

    class Old:
        def option_labels(self, obj, _):
            return ({"Contacted, but no response, unqualified": "Contacted, but no response, unqualified",
                     "Unqualified": "Unqualified"} if obj == "companies" else
                    {"COLLEAGUE_REPLIED_NEGATIVE": "Colleague replied: negative", "UNQUALIFIED": "Unqualified"})

    statuses = LeadStatus(Old())
    assert statuses.stage("companies", "Contacted, but no response, unqualified") == "no_response"
    assert statuses.stage("contacts", "COLLEAGUE_REPLIED_NEGATIVE") == "colleague_negative"
    assert statuses.props("contacts", "said_no") == {"hs_lead_status": "UNQUALIFIED"}  # until it is added
