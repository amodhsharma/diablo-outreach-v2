"""Channels outside our usual ones (Ariel, 23 Oct 2026, Unihockey Center): their first email adds the
bold heading "Why we think our bond would be strong" with the buyer's reason under it, from their own
campaign; their note never claims sweets the research does not show. Halal and kosher note endings."""

import json
import sys
from pathlib import Path

import pytest

from outreach import bond, common, send
from outreach.common import load_settings

from .fakes import FakeCRM, FakeInstantly

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "outreachMailWriting"
sys.path.insert(0, str(SKILL / "scripts"))
import check_lines  # noqa: E402
import prepare_lines  # noqa: E402


def quiet(_):
    pass


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)


UNIHOCKEY_LINE = ("We have great respect for the way your team has become a home for the sport. Your customers "
                  "already put real effort into staying active, and we believe sugar free snacks alongside the "
                  "equipment they come in for may suit those very same people. We would be grateful for the "
                  "opportunity to discuss whether this could be a worthwhile addition to your shop.")
UNIHOCKEY_NOTE = "equips floorball players and clubs, a community that takes its fitness seriously"


def test_which_channels_get_the_heading():
    other = ["Sports shops and sports nutrition shops", "sports shops", "Pharmacy and drugstore chains",
             "office snack and pantry suppliers", "Petrol station and convenience chains", "snack vending operators",
             "Corporate gifting and hamper companies", "hospital and care home shops", "hotel minibar suppliers",
             "leisure and venue snack suppliers", "travel retail", "promotional merchandise companies"]
    usual = ["Distributors", "wholesalers", "kiosk and convenience wholesalers", "Retailers", "online sellers",
             "health food and organic retailers", "diabetic, low sugar and keto shops", "gluten free and free from shops",
             "vegan and vegetarian shops", "halal food distributors", "kosher food distributors", "kosher shops",
             "seasonal and gift shops", "snack subscription boxes", "Distributor Wholesaler", "", None]
    for channel in other:
        assert bond.bond_channel(channel), channel
        assert bond.bond_reason(channel), channel
    for channel in usual:
        assert bond.bond_channel(channel) == "", channel
    assert json.loads((ROOT / "config" / "bond_channels.json").read_text())["heading"] == \
        "Why we think our bond would be strong"


def test_the_new_templates_add_the_heading_and_the_line():
    for new, old in (("template_5", "template_4"), ("template_no_info_apollo_4", "template_no_info_apollo_3")):
        body = json.loads((ROOT / "templates" / f"{new}.json").read_text())["body"]
        before = json.loads((ROOT / "templates" / f"{old}.json").read_text())["body"]
        assert "<b>Why we think our bond would be strong</b><br/>{{personal_line}}" in body
        assert "{{personal_line}}" not in before  # the earlier files are kept unchanged
        assert body.replace("<b>Why we think our bond would be strong</b><br/>{{personal_line}}<br/><br/>", "") == before


def _company(hs, name, domain, channel):
    cid = hs.add("companies", name=name, domain=domain, country="Switzerland", industry_type=channel,
                 hs_lead_status="GATE1: Approved for outreach")
    pid = hs.add("contacts", email=f"buyer@{domain}", firstname="Pia", lastname="Muster", jobtitle="Owner",
                 diablo_outreach_order="1", diablo_personal_line=UNIHOCKEY_LINE, diablo_company_note=UNIHOCKEY_NOTE,
                 hs_lead_status="APPROVED_TO_SEND")
    hs.links[pid] = [cid]
    return cid, pid


def test_other_channels_go_to_their_own_campaign_with_the_heading():
    hs, instantly = FakeCRM(), FakeInstantly()
    _company(hs, "Unihockey Center", "unihockey.example", "Sports shops and sports nutrition shops")
    _company(hs, "Beta Foods", "beta.example", "Distributors")
    s = load_settings()
    s["send"]["sending_accounts"] = ["one@getdiablo-test.com", "two@getdiablo-test.com"]
    send.run("test", s, hs, instantly, log=quiet)
    camps = {b["name"]: dict(b, id=cid) for cid, b in instantly.campaigns.items()}
    main = send.campaign_name("Diablo |")
    other = main + " | Other channels"
    assert set(camps) == {main, other}
    assert [l["email"] for l in instantly.leads[camps[other]["id"]]] == ["buyer@unihockey.example"]
    assert [l["email"] for l in instantly.leads[camps[main]["id"]]] == ["buyer@beta.example"]
    assert camps[other]["daily_limit"] == 15
    other_body = camps[other]["sequences"][0]["steps"][0]["variants"][0]["body"]
    main_body = camps[main]["sequences"][0]["steps"][0]["variants"][0]["body"]
    assert "Why we think our bond would be strong" in other_body and "Why we think" not in main_body
    text = send.render(other_body, instantly.leads[camps[other]["id"]][0])
    assert ("we noticed Unihockey Center equips floorball players and clubs, a community that takes its fitness "
            "seriously. We are a UK brand") in text
    assert "Why we think our bond would be strong\n" + UNIHOCKEY_LINE + "\n\nBy way of introduction" in text
    assert send.refresh_campaign_content(instantly, s, log=quiet) == 0  # each campaign keeps its own email
    for kind in send.KINDS:
        name = send.name_for_kind(kind, "Diablo |", s["send"])
        assert send.kind_of_campaign(name, s["send"]) == kind, name
    assert send.name_for_kind(send.INBOX_OTHER, "Diablo |", s["send"]) == main + " | Company inboxes | Other channels"


def _line(**change):
    line = {"contact_id": "1", "company_name": "Unihockey Center", "style": "E", "personal_line": UNIHOCKEY_LINE,
            "company_note": UNIHOCKEY_NOTE}
    line.update(change)
    return line


def _problems(line, info=None):
    errs = []
    check_lines.check_line(errs, line, info=info)
    return errs


def test_style_e_lines_give_the_buyers_reason():
    assert _problems(_line()) == []
    office = ("We have great respect for the way your team keeps offices stocked for the people who work in them. "
              "Many staff look for a lighter choice during the working day, and we believe sugar free snacks may "
              "suit those very same colleagues. We would be grateful for the opportunity to discuss whether this "
              "could be a worthwhile addition to your range.")
    assert _problems(_line(personal_line=office, company_note="keeps offices stocked with snacks and drinks for their staff")) == []
    two = "We have great respect for the way your team works. We would be grateful for the opportunity to discuss whether this could be a worthwhile addition to your shop."
    assert any("exactly three sentences" in e for e in _problems(_line(personal_line=two)))
    no_reason = UNIHOCKEY_LINE.replace("we believe ", "")
    assert any('"we believe"' in e for e in _problems(_line(personal_line=no_reason)))
    assert any("healthy" in e for e in _problems(_line(personal_line=UNIHOCKEY_LINE.replace("sugar free snacks", "healthy sugar free snacks"))))
    assert any("must start" in e for e in _problems(_line(personal_line="Your team " + UNIHOCKEY_LINE[44:])))
    # The usual styles keep their two-sentence rule.
    assert any("one or two sentences" in e for e in _problems(_line(style="D")))


def test_the_note_of_another_channel_says_what_it_does_not_sweets_it_does_not_sell():
    research = {"company": {"distributes": "Floorball sticks, shoes and bags", "what_they_do_well": ["Two shops"],
                            "fit_rationale": "Serves active players", "sf_brands_carried": "", "channels_supplied": ""}}
    assert _problems(_line(), research) == []
    wrong = _problems(_line(company_note="is in the retail space for confectionery products"), research)
    assert any("research names none" in e for e in wrong)
    snacks = dict(research["company"], distributes="Floorball equipment plus protein bars and snacks")
    assert _problems(_line(company_note="sells floorball equipment and snacks to active players"),
                     {"company": snacks}) == []
    # Without the research (the GitHub import) only the usual rules apply.
    assert _problems(_line(company_note="is in the retail space for confectionery products")) == []
    # The usual channels still must name our range.
    assert any("must name our range" in e for e in _problems(_line(style="A", personal_line="x", company_note=UNIHOCKEY_NOTE)))
    assert _problems(_line(company_note="supplies minibars to hotels")) == []  # hotels: who it serves


def test_halal_and_kosher_note_endings():
    def problems(note):
        errs = []
        check_lines.note_problems(errs, "x", note, "Alpha")
        return errs
    assert problems("distributes halal confectionery and snacks, and a significant part of our range is halal certified") == []
    assert problems("supplies kosher sweets and snacks to independent shops, and many of ours are kosher too") == []
    assert any("halal" in e for e in problems("distributes confectionery and snacks, and a significant part of our range is halal certified"))
    assert any("kosher" in e for e in problems("supplies sweets to independent shops, and many of ours are kosher too"))
    assert any('"our"' in e for e in problems("distributes kosher sweets, and our whole range is kosher"))


def test_prepare_gives_other_channels_style_e_and_the_buyers_reason(tmp_path):
    contacts = [{"contact_id": "1", "company": {"name": "Unihockey Center", "channel": "Sports shops and sports nutrition shops"}},
                {"contact_id": "2", "company": {"name": "Beta Foods", "channel": "Distributors"}}]
    prepare_lines.assign_styles(contacts, lines_dir=tmp_path)
    assert contacts[0]["style"]["letter"] == "E" and "active" in contacts[0]["bond"]["buyer_reason"]
    assert contacts[1]["style"]["letter"] in "ABCD" and "bond" not in contacts[1]
    prompt = (SKILL / "prompts" / "lines_prompt_10.md").read_text()
    assert "lines_prompt_10.md" in (SKILL / "scripts" / "prepare_lines.py").read_text()
    assert "Why we think our bond would be strong" in prompt and "**E. Why we think our bond" in prompt
    assert check_lines.HALAL_TAIL.strip(", ") in prompt and check_lines.KOSHER_TAIL.strip(", ") in prompt
    assert "bond" not in (SKILL / "prompts" / "lines_prompt_9.md").read_text()  # kept as it was
