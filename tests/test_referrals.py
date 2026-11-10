"""Replies that only name someone else, Amodh's daily email, the line copy at open companies, policy bounces
and the backlog's check (agreed 3 Nov 2026, Ariel)."""

import datetime as dt

from outreach import chain, corrupt, find_contacts, referrals, sync
from outreach.common import load_settings
from outreach.stages import LeadStatus

from .fakes import FakeApollo, FakeCRM, FakeInstantly
from .test_chain import settings  # noqa: F401
from .test_corrupt import LS, ORDER, REASON, ago, bounce, company, lead, quiet, rec, started

REDIRECTED = "UNQUALIFIED_REDIRECTED"


def neutral(instantly, emails, address, text):
    lead(instantly, address).update(email_reply_count=1)
    emails.received(address, ago(0.5), subject="Re: A sugar-free brand", text=text)


def test_a_reply_giving_a_new_address_is_switched_by_itself(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "shift.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@shift.example",
            "Hello, my email address has changed. Please write to anna.meier@shift.example from now on.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    new = next(i for i, r in hs.records["contacts"].items() if r.get("email") == "anna.meier@shift.example")
    assert rec(hs, new)["firstname"] == "Anna" and rec(hs, new)["jobtitle"] == "Referred by colleague"
    assert rec(hs, new)["hs_legal_basis"] == "Legitimate interest – prospect/lead"
    assert rec(hs, new)["lead_source"] == "AUTO-OUTREACH" and cid in hs.links[new]
    assert rec(hs, p1)[LS] == REDIRECTED
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"  # back in the loop
    assert referrals.load()["handled"][p1]["outcome"] == "switched"
    # Button 3 makes the new contact number 1, copies the line and puts it on GATE2
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)
    assert rec(hs, new)[ORDER] == "1" and rec(hs, new)[LS] == "APPROVED_TO_SEND"


def test_an_unclear_reply_changes_nothing_and_is_listed_for_amodh(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "vague.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@vague.example", "Thank you, we will look at it and come back to you.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "IN_PROGRESS" and hs.records["companies"][cid][LS] == "In Progress"
    entry = referrals.load()["handled"][p1]
    assert entry["outcome"] == "unsure" and entry["why"] == "no email address in the reply"
    subject, text = referrals.report_text(hs, emails, LeadStatus(hs), entry["day"])
    assert "Left for you: 1" in text and "Vague" in text and "come back to you" in text
    assert "no email address in the reply" in text and subject.startswith("Partner outreach")


def test_not_sure_when_the_address_is_elsewhere_or_already_a_team_contact(settings):
    assert referrals.judge("Please contact bob@gmail.com", "p1@x.example", "x.example")[1] == \
        "the address in the reply is not at the company's own domain"
    assert referrals.judge("Hi, see sam@x.example", "p1@x.example", "x.example")[1] == \
        "no clear wording that it is a redirect"
    assert referrals.judge("Please contact a@x.example, b@x.example, c@x.example, d@x.example", "p1@x.example",
                           "x.example")[1].startswith("more than 3")
    assert referrals.judge("Bitte wenden Sie sich an max@www-x.example", "p1@x.example", "www.x.example")[0] == []
    assert referrals.judge("Bitte wenden Sie sich an max@x.example", "p1@x.example", "www.x.example")[0] == \
        ["max@x.example"]
    hs, instantly, emails, cid, (p1, p2) = started(settings, "team.example", ("Owner", "Buyer"))
    hs.add("contacts", tagged=False, email="boss@team.example")  # the team's own contact
    neutral(instantly, emails, "p1@team.example", "Please contact boss@team.example instead.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "IN_PROGRESS"
    assert "team's own contacts" in referrals.load()["handled"][p1]["why"]


def test_an_automatic_reply_saying_she_left_adds_the_new_address(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "gone.example", ("Owner", "Buyer"))
    lead(instantly, "p1@gone.example").update(email_reply_count=1)
    emails.received("p1@gone.example", ago(0.5), subject="Automatic reply",
                    text="Pia is no longer with the company. Please contact lukas.brand@gone.example.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == REDIRECTED
    assert any(r.get("email") == "lukas.brand@gone.example" for r in hs.records["contacts"].values())


def test_a_reply_a_person_already_dealt_with_is_left_alone_and_the_company_resumes(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "done.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@done.example", "Please contact new@done.example instead.")
    rec(hs, p1)[LS] = REDIRECTED  # the person was quicker
    hs.records["companies"][cid][LS] = "In Progress"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert not any(r.get("email") == "new@done.example" for r in hs.records["contacts"].values())
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"  # nobody left in conversation


def test_a_company_still_in_conversation_stays_paused():
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Talk", "talk.example", ("Owner", "Buyer"))
    hs.records["companies"][cid][LS] = "In Progress"
    rec(hs, p1)[LS], rec(hs, p2)[LS] = REDIRECTED, "IN_PROGRESS"
    assert referrals.release(hs, LeadStatus(hs), quiet) == 0


def test_no_email_when_nothing_happened(settings):
    hs = FakeCRM()
    assert referrals.report_text(hs, None, LeadStatus(hs), "2026-11-03") == (None, None)


def test_a_signature_address_or_a_public_mail_service_is_never_a_redirect():
    """Review, 3 Nov 2026: the right person writing back, with the shop address in the signature."""
    text = ("I am responsible for purchasing. Please send your price list and we will review it.\n\n"
            "Kind regards\nAnna\nPurchasing\n" + "Acme GmbH, Hauptstrasse 1, 10115 Berlin. " * 8 + "info@acme.de")
    assert referrals.judge(text, "anna@acme.de", "acme.de")[0] == []
    assert referrals.judge("Please contact bob@gmail.com", "anna@gmail.com", "acme.de")[0] == []
    assert referrals.judge("Please contact bob@acme.de", "anna@gmail.com", "acme.de")[0] == ["bob@acme.de"]


def test_one_reply_that_fails_does_not_stop_the_others(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "first.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@first.example", "Please contact new.one@first.example from now on.")
    calls = {"n": 0}
    real = hs.create_tagged

    def flaky(kind, records):
        calls["n"] += 1
        raise RuntimeError("HubSpot said no")
    monkeypatch.setattr(hs, "create_tagged", flaky)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert calls["n"] == 1 and p1 not in referrals.load().get("handled", {})  # tried again next run
    monkeypatch.setattr(hs, "create_tagged", real)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert referrals.load()["handled"][p1]["outcome"] == "switched"


def test_an_address_already_at_another_company_is_left_for_a_person(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "move.example", ("Owner", "Buyer"))
    other, (q1,) = company(hs, "Other", "other.example", ("Owner",))
    rec(hs, q1)["email"] = "kim@move.example"
    neutral(instantly, emails, "p1@move.example", "Please contact kim@move.example from now on.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "IN_PROGRESS" and cid not in hs.links.get(q1, [])
    assert "another company" in referrals.load()["handled"][p1]["why"]


def test_colleagues_already_emailed_are_not_set_back_to_gate_2(settings):
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Back", "back.example", ("Owner", "Buyer"))
    hs.records["companies"][cid][LS] = "In Progress"
    rec(hs, p1)[LS], rec(hs, p2)[LS] = REDIRECTED, "COLLEAGUE_REPLIED"
    assert referrals.release(hs, LeadStatus(hs), quiet, leads={"p2@back.example": {}}) == 1
    assert rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"


def test_today_s_unsure_replies_are_not_counted_as_earlier_days(tmp_path):
    hs = FakeCRM()
    cid, (p1,) = company(hs, "Days", "days.example", ("Owner",))
    path = tmp_path / "r.json"
    referrals.save({"handled": {p1: {"day": "2026-11-04", "outcome": "unsure", "company": cid, "why": "x"}}}, path)
    assert referrals.report_text(hs, None, LeadStatus(hs), "2026-11-03", path) == (None, None)


# ---- The line copy at every open company -----------------------------------------------------------

def test_a_contact_added_later_at_an_open_company_gets_the_line_and_gate_2(settings):
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Open", "open.example", ("Owner", "Buyer"))  # person 1 approved, GATE1 company
    rec(hs, p2).update({LS: "NEW"})
    rec(hs, p2).pop("diablo_personal_line")
    assert chain.fill_open(hs, settings, LeadStatus(hs), None, quiet) == 1
    assert rec(hs, p2)[LS] == "APPROVED_TO_SEND" and rec(hs, p2)["diablo_personal_line"] == "Line."
    closed, (q1, q2) = company(hs, "Shut", "shut.example", ("Owner", "Buyer"))
    hs.records["companies"][closed][LS] = "Unqualified"
    rec(hs, q2).update({LS: "NEW"})
    assert chain.fill_open(hs, settings, LeadStatus(hs), None, quiet) == 0  # only open companies


# ---- Bounces --------------------------------------------------------------------------------------

def test_microsoft_access_denied_is_a_dead_address_and_the_message_is_kept(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "ms.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@ms.example", text="550 5.4.1 Recipient address rejected: Access denied. For more "
                                                     "information see https://aka.ms/EXOSmtpErrors")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_CONTACT_CORRUPT"
    assert "Bounce message: 550 5.4.1 Recipient address rejected: Access denied" in rec(hs, p1)[REASON]


def test_a_policy_block_closes_the_company_and_skips_the_colleagues(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "block.example", ("Owner", "Buyer"))
    bounce(instantly, emails, "p1@block.example", text="The user or domain that you are sending to (or from) has a "
                                                        "policy that prohibited the mail that you sent.")
    moved = sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_BOUNCED_OTHER" and "policy that prohibited" in rec(hs, p1)[REASON]
    assert hs.records["companies"][cid][LS] == "Unqualified: Bounced, other reason"
    assert moved["next_contacts_added"] == 0 and rec(hs, p2)[LS] == "APPROVED_TO_SEND"  # not emailed


def test_an_old_bounce_read_again_never_moves_anyone_up_at_a_company_in_conversation(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "talking.example", ("Owner", "Buyer"))
    rec(hs, p1)[LS] = "UNQUALIFIED_BOUNCED_OTHER"
    rec(hs, p1)[REASON] = "Email bounced (1 Nov 2026): not a dead address (for example a full mailbox)."
    rec(hs, p2)[LS] = "NEW_PERSONAL_LINE_FILLED"
    hs.records["companies"][cid][LS] = "In Progress"
    bounce(instantly, emails, "p1@talking.example")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_CONTACT_CORRUPT"  # the address is still marked dead
    assert rec(hs, p2)[LS] == "NEW_PERSONAL_LINE_FILLED" and rec(hs, p2)[ORDER] == "2"  # nobody moves up


# ---- The backlog never reopens a company that already had everything ---------------------------------

def test_the_backlog_skips_a_company_whose_people_already_had_both_emails(settings):
    from .fakes import FakeEmails
    from .test_chain import NOW, closed_company
    hs, instantly, emails = FakeCRM(), FakeInstantly(), FakeEmails()
    cid, (p1,) = closed_company(hs, instantly, "Twice", "twice.example", 25, backups=0)
    emails.campaign_email("p1@twice.example", (NOW - dt.timedelta(days=25)).isoformat())
    emails.campaign_email("p1@twice.example", (NOW - dt.timedelta(days=18)).isoformat())  # the reminder
    assert chain.run_backlog(hs, instantly, settings, log=quiet, now=NOW, emails_api=emails)["reopened"] == 0
    assert str(cid) in chain.load_state()["closed"]


# ---- 10 Nov 2026 (Ariel): copied colleagues, out-of-office stand-ins, paused companies that go on --------

VELO = ("Bonjour, Je serais de retour en magasin le 10/11 et répondrai à vos messages à mon retour. En cas "
        "d'urgence, vous pouvez contacter directement le magasin : shop@velo.example Meilleurs salutations, Yoan")


def test_a_colleague_copied_into_the_reply_is_added_and_emailed(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "bloom.example", ("Owner", "Buyer"))
    lead(instantly, "p1@bloom.example").update(email_reply_count=1)
    emails.received("p1@bloom.example", ago(0.5), subject="Re: hello", cc="kate@bloom.example",
                    text="Thanks so much for reaching out! I'll point you in the direction of our Inventory "
                         "Coordinator Kate, who will be your best point of contact. She has been looped into this thread.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    new = next(i for i, r in hs.records["contacts"].items() if r.get("email") == "kate@bloom.example")
    assert rec(hs, p1)[LS] == REDIRECTED and cid in hs.links[new]
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"


def test_a_copied_colleague_without_redirect_words_is_left_for_a_person():
    new, why = referrals.judge("Thanks, we will look at it.", "p1@x.example", "x.example", copied=["boss@x.example"])
    assert new == [] and "copied in" in why


def test_a_french_out_of_office_is_automatic_and_its_stand_in_is_added(settings):
    assert sync.auto_reply_reason({"subject": "Re: hello", "body": {"text": VELO}})
    hs, instantly, emails, cid, (p1, p2) = started(settings, "velo.example", ("Store Leader", "Buyer"))
    lead(instantly, "p1@velo.example").update(email_reply_count=1)
    emails.received("p1@velo.example", ago(0.5), subject="Re: A sugar-free brand", text=VELO)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    new = next(i for i, r in hs.records["contacts"].items() if r.get("email") == "shop@velo.example")
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT"  # only away: left as they are
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert referrals.load()["handled"][p1]["outcome"] == "added"
    find_contacts.run("test", load_settings(), hs, FakeApollo({}, {}), log=quiet)  # numbered, line copied
    assert rec(hs, new)[ORDER] == "3" and rec(hs, new)[LS] == "APPROVED_TO_SEND"


def test_a_misread_out_of_office_puts_the_company_back_and_is_read_again(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "velo.example", ("Store Leader", "Buyer"))
    lead(instantly, "p1@velo.example").update(email_reply_count=1)
    emails.received("p1@velo.example", ago(2), subject="Re: A sugar-free brand", text=VELO)
    rec(hs, p1)[LS], rec(hs, p2)[LS] = "IN_PROGRESS", "COLLEAGUE_REPLIED"  # read as a real reply before today
    hs.records["companies"][cid][LS] = "In Progress"
    referrals.save({"handled": {p1: {"day": "2026-11-07", "outcome": "unsure", "company": cid, "why": "x"}}})
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert rec(hs, p1)[LS] == "ATTEMPTED_TO_CONTACT" and rec(hs, p2)[LS] == "APPROVED_TO_SEND"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)  # now read as an out-of-office
    assert any(r.get("email") == "shop@velo.example" for r in hs.records["contacts"].values())


def test_old_in_progress_colleagues_do_not_hold_a_redirected_company_back(settings):
    """Vita Drogerie: the replier is Rejected/Redirected, the others were left on In Progress by the old rules."""
    hs, instantly, emails, cid, (p1, p2, p3) = started(settings, "vita.example", ("Owner", "Buyer", "Shop"))
    rec(hs, p1)[LS] = REDIRECTED
    rec(hs, p2)[LS] = rec(hs, p3)[LS] = "IN_PROGRESS"
    hs.records["companies"][cid][LS] = "In Progress"
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert rec(hs, p2)[LS] == rec(hs, p3)[LS] == "APPROVED_TO_SEND"


def test_someone_really_in_conversation_still_holds_the_company(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "talk.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@talk.example", "Thanks, we will look at it and come back to you.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    rec(hs, p2)[LS] = REDIRECTED  # someone else there redirected: the real reply still holds the company
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "In Progress" and rec(hs, p1)[LS] == "IN_PROGRESS"


def test_a_neutral_reply_nobody_acted_on_for_7_days_lets_the_company_go_on(settings, monkeypatch):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "slow.example", ("Owner", "Buyer"))
    neutral(instantly, emails, "p1@slow.example", "Thanks, I will come back to you in a few days.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p2)[LS] == "COLLEAGUE_REPLIED" and hs.records["companies"][cid][LS] == "In Progress"
    state = referrals.load()
    state["handled"][p1]["day"] = (dt.date.fromisoformat(state["handled"][p1]["day"]) - dt.timedelta(days=7)).isoformat()
    referrals.save(state)
    monkeypatch.setenv("GITHUB_RUN_ID", "run2")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert rec(hs, p1)[LS] == "IN_PROGRESS" and referrals.load()["handled"][p1]["parked"]
    assert rec(hs, p2)[LS] == "ATTEMPTED_TO_CONTACT"  # Instantly already holds the colleague: back in the loop
    from outreach.next_in_line import contact_state
    assert contact_state({"id": p1, "properties": rec(hs, p1)}, LeadStatus(hs), {}) == "skipped"
    for days in (4, 9):  # the colleague's turn, then the reminders: never one to the person who replied
        monkeypatch.setenv("GITHUB_RUN_ID", f"run{days}")
        lead(instantly, "p1@slow.example")["timestamp_last_contact"] = ago(days)
        sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "IN_PROGRESS"
    assert not [r for r in emails.replies if "p1@slow.example" in str(r.get("address") or r.get("to"))]
    today = referrals.today_india()
    _, text = referrals.report_text(hs, None, LeadStatus(hs), today)
    assert "BACK IN THE LOOP" in text and "waited 7 days" in text


# ---- Review, 10 Nov 2026 -------------------------------------------------------------------------------

def test_real_answers_that_mention_being_back_are_never_out_of_office():
    for text in ("I will be back in touch next week with our feedback.", "I'll return to you after our review.",
                 "Je vous recontacte à mon retour du salon.", "Ne parlo con il team al mio rientro.",
                 "Lo reviso a mi regreso y le digo.", "I am back in the office on Monday, can you send prices?"):
        assert not sync.auto_reply_reason({"subject": "Re: hello", "body": {"text": text}}), text


def test_ordinary_questions_with_a_signature_address_are_never_a_redirect():
    sig = "\n\nKind regards\nAnna\nShop Srl, Via Roma 1, 20100 Milano\norders@shop.it"
    for text in ("Could you tell me who handles your EU logistics?", "Thanks, I have added your samples request.",
                 "What is the best contact number for you?"):
        assert referrals.judge(text + sig, "anna@shop.it", "shop.it")[0] == [], text
    assert referrals.judge("Who manages your exports?", "anna@shop.it", "shop.it", copied=["boss@shop.it"])[0] == []


def _parked_company(settings, domain):
    hs, instantly, emails, cid, (p1, p2) = started(settings, domain, ("Owner", "Buyer"))
    neutral(instantly, emails, f"p1@{domain}", "Thanks, I will come back to you in a few days.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    state = referrals.load()
    state["handled"][p1]["day"] = "2026-01-01"
    referrals.save(state)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert referrals.load()["handled"][p1]["parked"] and hs.records["companies"][cid][LS] == "Attempted to Contact"
    return hs, instantly, emails, cid, p1, p2


def test_a_parked_reply_never_holds_the_company_back_later(settings):
    hs, instantly, emails, cid, p1, p2 = _parked_company(settings, "park.example")
    hs.records["companies"][cid][LS] = "In Progress"  # the colleague replied, then was redirected by a person
    rec(hs, p2)[LS] = REDIRECTED
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"


def test_a_parked_contact_who_writes_again_pauses_the_company(settings):
    hs, instantly, emails, cid, p1, p2 = _parked_company(settings, "again.example")
    lead(instantly, "p1@again.example").update(email_reply_count=2)
    emails.received("p1@again.example", ago(0.1), text="Sorry for the delay, could you send the price list?")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "In Progress"
    assert p1 not in referrals.load()["handled"] or not referrals.load()["handled"][p1].get("parked")


def test_a_reply_read_again_keeps_its_parked_flag():
    handled = {"1": {"day": "2026-11-01", "outcome": "unsure", "parked": "2026-11-08", "replies": 1}}
    referrals._record(handled, "1", {"day": "2026-11-10", "outcome": "unsure", "why": "x"})
    assert handled["1"]["parked"] == "2026-11-08" and handled["1"]["day"] == "2026-11-01"


def test_someone_who_really_replied_but_left_instantly_is_never_reset(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "moved.example", ("Owner", "Buyer"))
    rec(hs, p1)[LS] = REDIRECTED
    rec(hs, p2)[LS] = "IN_PROGRESS"
    hs.records["companies"][cid][LS] = "In Progress"
    emails.campaign_email("p2@moved.example", ago(5))  # emailed from a campaign outside the Diablo ones
    emails.received("p2@moved.example", ago(4), text="Yes, please send the catalogue.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert hs.records["companies"][cid][LS] == "In Progress" and rec(hs, p2)[LS] == "IN_PROGRESS"


def test_a_buyer_copying_a_colleague_while_asking_for_prices_is_not_redirected():
    text = "Send me prices please. I have cc'd my colleague so she sees it too."
    assert referrals.judge(text, "anna@shop.it", "shop.it", copied=["maria@shop.it"])[0] == []
    for real in ("Merci, je serai de retour au bureau lundi et je vous appelle.",
                 "Grazie, sarò di ritorno in ufficio lunedì e la chiamo."):
        assert not sync.auto_reply_reason({"subject": "Re: hello", "body": {"text": real}}), real
