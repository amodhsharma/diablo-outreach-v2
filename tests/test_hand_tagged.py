"""Contacts made AUTO-OUTREACH by hand (Ariel, 26 Oct 2026): general addresses become company inboxes
and everyone gets an Outreach order, people first by seniority."""

from outreach import hand_tagged
from outreach.common import load_settings
from outreach.schema import INBOX_TITLE

from .fakes import FakeCRM


def quiet(_):
    pass


def test_general_addresses_are_recognised():
    g = lambda **p: hand_tagged.is_general({"properties": p}, "Dalchini World food Market")
    assert g(email="info@dalchini.ch", lastname="Dalchini World food Market")
    assert g(email="welcome@orakei.ch", lastname="Orakei Ltd.")
    assert g(email="hallo@laedelishop.ch")
    assert g(email="contactkandykrush@gmail.com", firstname="Dalchini World food Market")  # company name as name
    assert g(email="kirchapo@hin.ch")  # no name at all
    assert not g(email="ashish.kapoor@dalchini.ch", firstname="Ashish Kapoor")
    assert not g(email="klemens@umamisnack.ch", firstname="Klemens Foster")
    assert not g(email="remo.thoeny@sportbenzin.ch", firstname="Remo", lastname="Thöny")


def test_hand_tagged_contacts_get_an_order_and_the_inbox_title():
    hs = FakeCRM()
    orakei = hs.add("companies", name="Orakei Ltd.", domain="orakei.ch")
    ids = {}
    for key, props in {"welcome": dict(email="welcome@orakei.ch", lastname="Orakei Ltd."),
                       "ceo": dict(email="olivier@orakei.ch", firstname="Olivier", jobtitle="CEO"),
                       "buyer": dict(email="patricia@orakei.ch", firstname="Patricia", jobtitle="Purchasing Manager")}.items():
        ids[key] = hs.add("contacts", **props)
        hs.links[ids[key]] = [orakei]
    done = hand_tagged.prepare(hs, load_settings(), quiet)
    assert done == {"contacts": 3, "company_inboxes": 1}
    c = hs.records["contacts"]
    assert (c[ids["ceo"]]["diablo_outreach_order"], c[ids["buyer"]]["diablo_outreach_order"],
            c[ids["welcome"]]["diablo_outreach_order"]) == ("1", "2", "3")
    assert c[ids["welcome"]]["jobtitle"] == INBOX_TITLE and c[ids["ceo"]]["jobtitle"] == "CEO"
    assert c[ids["welcome"]]["lastname"] == "Orakei Ltd."  # nothing else changed
    assert hand_tagged.prepare(hs, load_settings(), quiet) == {"contacts": 0, "company_inboxes": 0}  # once only
    # A later one at the same company comes after the ones already ordered.
    late = hs.add("contacts", email="therese@orakei.ch", firstname="Therese")
    hs.links[late] = [orakei]
    hand_tagged.prepare(hs, load_settings(), quiet)
    assert c[late]["diablo_outreach_order"] == "4"
