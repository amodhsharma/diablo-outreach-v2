"""A reply that hands us to someone else is a referral, whatever label Instantly gave it (agreed 12 Nov 2026, Ariel,
after Taste Organic: the store manager named the head office buyer, Instantly labelled it positive, and the
automation sent it to the sales team instead of emailing the buyer)."""

from outreach import find_contacts, referral_intro, referrals, reply_forward, send, sync
from outreach.common import load_settings
from outreach.stages import LeadStatus

from .fakes import FakeApollo, FakeCRM
from .test_chain import settings  # noqa: F401
from .test_corrupt import LS, ORDER, ago, company, lead, quiet, rec, started

STORE_REPLY = ("Hi Joshua\nThis is Matt, regarding your recent emails the person to contact for new products is the "
               "Unique Wholefood buyer at our head office in Leichhardt\nThe contact is Bishnu Baniya\n"
               "bishnu@unique.example\nBest regards")


def labelled(instantly, emails, address, text, interest=1, sender=None):
    lead(instantly, address).update(email_reply_count=1, lt_interest_status=interest)
    e = emails.received(sender or address, ago(0.5), subject="Re: A sugar-free brand", text=text)
    e["lead"] = address  # Instantly files it under the lead, also when a shared mailbox answers
    return e


def head_office(hs, buyer=True):
    """The head office: its own AUTO-OUTREACH company, the buyer already found by Apollo (New)."""
    hid = hs.add("companies", name="Unique", domain="unique.example", country="Australia",
                 **{LS: "Contact located. Queued for processing"})
    bid = None
    if buyer:
        bid = hs.add("contacts", email="bishnu@unique.example", firstname="Bishnu", lastname="Baniya",
                     jobtitle="Director", **{ORDER: "1", LS: "NEW"})
        hs.links[bid] = [hid]
    return hid, bid


def test_the_taste_organic_case_emails_the_buyer_and_is_not_sent_to_sales(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "unique.example", ("Manager Retail", "Nutritionist"))
    hs.records["companies"][cid].update(name="Taste", domain="taste.example")
    hid, bid = head_office(hs)
    labelled(instantly, emails, "p1@unique.example", STORE_REPLY, interest=1, sender="crowsnest@unique.example")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_REDIRECTED"  # not END: Forwarded to Sales Team
    assert hs.records["companies"][cid][LS] != "END: Forwarded to Sales Team"
    fwd = next(f for f in emails.forwards if f["to"] == "bishnu@unique.example")
    assert fwd["text"].startswith("Hi Bishnu,") and "Your colleague P1 kindly passed on your details" in fwd["text"]
    assert "The contact is Bishnu Baniya" in fwd["text"] and fwd["subject"].startswith("Fwd: ")
    assert rec(hs, bid)[LS] == "FORWARD_SENT" and hs.links[bid] == [hid]
    assert hs.records["companies"][hid][LS] == "Attempted to Contact"
    assert referral_intro.waiting_ids() == set()
    # The next run never turns the label into END afterwards
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "UNQUALIFIED_REDIRECTED"
    assert len([f for f in emails.forwards if f["to"] == "bishnu@unique.example"]) == 1


def test_a_new_address_goes_under_the_company_with_that_website(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "unique.example", ("Manager Retail", "Buyer"))
    hs.records["companies"][cid].update(name="Taste", domain="taste.example")
    hid, _ = head_office(hs, buyer=False)
    labelled(instantly, emails, "p1@unique.example", STORE_REPLY.replace("bishnu@", "kate.lee@"), interest=2)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    new = next(i for i, r in hs.records["contacts"].items() if r.get("email") == "kate.lee@unique.example")
    assert hs.links[new] == [hid] and rec(hs, new)["company"] == "Unique"
    assert rec(hs, new)["hs_legal_basis"] == "Legitimate interest – prospect/lead"
    assert rec(hs, new)[LS] == "FORWARD_SENT" and rec(hs, new)[ORDER] == "1"


def test_a_yes_that_also_names_a_colleague_goes_to_sales_with_the_colleague(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "mix.example", ("Owner", "Buyer"))
    labelled(instantly, emails, "p1@mix.example",
             "Interesting. Please send your price list and samples. Our buyer is kate.lee@mix.example, she will "
             "place the orders.", interest=1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "END_FORWARDED_TO_SALES_TEAM"
    assert hs.records["companies"][cid][LS] == "END: Forwarded to Sales Team"
    kate = next(i for i, r in hs.records["contacts"].items() if r.get("email") == "kate.lee@mix.example")
    assert rec(hs, kate)[LS] == "END_FORWARDED_TO_SALES_TEAM" and cid in hs.links[kate]
    assert rec(hs, kate)["lead_source"] == "AUTO-OUTREACH"
    assert not [f for f in emails.forwards if f["to"] == "kate.lee@mix.example"]  # the sales team takes it
    assert referrals.load()["handled"][p1]["outcome"] == "mixed"


def test_a_plain_yes_still_goes_to_sales(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "yes.example", ("Owner", "Buyer"))
    labelled(instantly, emails, "p1@yes.example", "Yes, very interested. Please send prices.", interest=1)
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "END_FORWARDED_TO_SALES_TEAM"
    assert hs.records["companies"][cid][LS] == "END: Forwarded to Sales Team"


def test_the_team_gets_it_as_a_referral():
    seen = [({"id": "7"}, {}, "replied"), ({"id": "8"}, {}, "marked interested")]
    assert reply_forward.due(seen, {}, referral_ids={"7"}) == [({"id": "7"}, "Referral"), ({"id": "8"}, "Positive")]
    assert reply_forward.SECRET["Referral"] == "REPLY_FORWARD_TO"
    assert reply_forward.due(seen, {"7": ["Referral"]}) == [({"id": "8"}, "Positive")]


def test_the_wording_of_a_hand_over(settings):
    assert referrals.judge(STORE_REPLY, "p1@unique.example", "taste.example")[0] == ["bishnu@unique.example"]
    for text in ("Our buyer is anna@x.example.", "The right person is anna@x.example", "Please speak to "
                 "anna@x.example", "Ihre Ansprechpartnerin ist anna@x.example", "Il referente è anna@x.example"):
        assert referrals.judge(text, "p1@x.example", "x.example")[0] == ["anna@x.example"], text
    # The right person writing back, with a colleague's address in the signature, is still no redirect
    sig = "I look after buying here, please send your prices.\n\nKind regards\n" + "Acme, Main St 1. " * 20
    assert referrals.judge(sig + "info@x.example", "p1@x.example", "x.example")[0] == []


def test_button_4_never_gives_a_referred_person_the_normal_introduction(settings):
    hs = FakeCRM()
    cid, (p1,) = company(hs, "Wait", "wait.example", ("Buyer",))
    referral_intro.queue(p1, "999", cid)
    from .fakes import FakeInstantly
    instantly = FakeInstantly()
    send.run("test", settings, hs, instantly, log=quiet)
    assert not any(l["email"] == "p1@wait.example" for ls in instantly.leads.values() for l in ls)


def test_a_queued_referral_waits_without_the_emails_key_and_goes_once_it_can(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "unique.example", ("Manager Retail", "Buyer"))
    hs.records["companies"][cid].update(name="Taste", domain="taste.example")
    hid, bid = head_office(hs)
    labelled(instantly, emails, "p1@unique.example", STORE_REPLY, interest=1)
    rec(hs, p1)[LS] = "END_FORWARDED_TO_SALES_TEAM"  # handled before 12 Nov 2026
    referral_intro.queue(bid, p1, hid)
    assert referral_intro.send(hs, None, LeadStatus(hs), settings, quiet) == 0
    assert referral_intro.send(hs, emails, LeadStatus(hs), settings, quiet) == 1
    assert rec(hs, bid)[LS] == "FORWARD_SENT" and rec(hs, p1)[LS] == "END_FORWARDED_TO_SALES_TEAM"
    assert referral_intro.send(hs, emails, LeadStatus(hs), settings, quiet) == 0  # never twice


def test_a_referral_is_dropped_when_the_person_opted_out_meanwhile(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "unique.example", ("Manager Retail", "Buyer"))
    hid, bid = head_office(hs)
    labelled(instantly, emails, "p1@unique.example", STORE_REPLY, interest=1)
    rec(hs, bid)["hs_email_optout"] = "true"
    referral_intro.queue(bid, p1, hid)
    assert referral_intro.send(hs, emails, LeadStatus(hs), settings, quiet) == 0
    assert not emails.forwards and "opted out" in referrals.load()["intro"][bid]["dropped"]


def test_every_auto_outreach_contact_gets_the_legal_basis():
    hs = FakeCRM()
    cid, (p1, p2) = company(hs, "Basis", "basis.example", ("Owner", "Buyer"))
    rec(hs, p2)["hs_legal_basis"] = "Legitimate interest – prospect/lead"
    untagged = hs.add("contacts", tagged=False, email="team@basis.example")
    assert find_contacts.fill_legal_basis(hs, quiet) == 1
    assert rec(hs, p1)["hs_legal_basis"] == "Legitimate interest – prospect/lead"
    assert "hs_legal_basis" not in rec(hs, untagged)
    hs2 = FakeCRM()
    company(hs2, "Fresh", "fresh.example", ("Owner",))
    find_contacts.run("test", load_settings(), hs2, FakeApollo({}, {}), log=quiet)
    assert all(r.get("hs_legal_basis") for r in hs2.records["contacts"].values() if r.get("lead_source"))


# ---- Diablo's own domains writing in a prospect's thread (12 Nov 2026, Ariel) ----

def ours(instantly, emails, address, sender="ariel@diablosugarfree.com", interest=1, text="Thanks, adding our "
         "sales team here. Best, Ariel"):
    lead(instantly, address).update(email_reply_count=1, lt_interest_status=interest)
    e = emails.received(sender, ago(0.5), subject="Re: A sugar-free brand", text=text)
    e["lead"] = address
    return e


def test_only_diablo_writing_in_the_thread_is_no_reply(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "own.example", ("Owner", "Buyer"))
    ours(instantly, emails, "p1@own.example")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] not in ("END_FORWARDED_TO_SALES_TEAM", "IN_PROGRESS")
    assert hs.records["companies"][cid][LS] == "Attempted to Contact"
    assert referrals.load().get("handled", {}).get(p1) is None


def test_a_real_reply_still_counts_when_diablo_also_wrote(settings):
    hs, instantly, emails, cid, (p1, p2) = started(settings, "both.example", ("Owner", "Buyer"))
    ours(instantly, emails, "p1@both.example", sender="joshua@meetdiablo.com")
    emails.received("p1@both.example", ago(0.4), subject="Re: A sugar-free brand",
                    text="Yes, very interested. Please send prices.")
    sync.run("test", settings, hs, instantly, log=quiet, emails_api=emails)
    assert rec(hs, p1)[LS] == "END_FORWARDED_TO_SALES_TEAM"


def test_which_addresses_are_diablo():
    from outreach.common import from_us, own_domains
    d = own_domains()
    for a in ("ariel@diablosugarfree.com", "Ariel Mansouri <ariel@diablosugarfree.com>", "x@mail.diablosugarfree.com",
              "sales@diablosnosugar.com", "dana@diabloexport.com", "elize@meetdiablo.com"):
        assert from_us({"from_address_email": a}, d), a
    for a in ("buyer@eldiablofoods.mx", "p1@shop.example", "", None):
        assert not from_us({"from_address_email": a}, d), a
