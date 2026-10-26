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


def test_the_october_templates_add_the_heading_and_the_line():
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


def _two_companies():
    hs, instantly = FakeCRM(), FakeInstantly()
    _company(hs, "Unihockey Center", "unihockey.example", "Sports shops and sports nutrition shops")
    _company(hs, "Beta Foods", "beta.example", "Distributors")
    s = load_settings()
    s["send"]["sending_accounts"] = ["one@getdiablo-test.com", "two@getdiablo-test.com"]
    return hs, instantly, s


def _without_paragraph(s):
    """The settings as they were before the preview was checked (26 Oct 2026)."""
    s["send"]["templates"] = dict(s["send"]["templates"], first_email="templates/template_4.json",
                                  first_email_company_inbox="templates/template_no_info_apollo_3.json")
    return s


def test_the_two_campaigns_have_room_for_the_paragraph():
    s = load_settings()
    assert send.bond_ready(s, send.PERSON) and send.bond_ready(s, send.INBOX)


def _with_paragraph(s):
    s["send"]["templates"] = dict(s["send"]["templates"], first_email="templates/template_6.json",
                                  first_email_company_inbox="templates/template_no_info_apollo_5.json")
    return s


def test_the_paragraph_templates_are_the_usual_ones_with_room_for_it():
    for new, old in (("template_6", "template_4"), ("template_no_info_apollo_5", "template_no_info_apollo_3")):
        body = json.loads((ROOT / "templates" / f"{new}.json").read_text())["body"]
        before = json.loads((ROOT / "templates" / f"{old}.json").read_text())["body"]
        assert body.replace("{{bond_paragraph}}", "") == before
        assert "<br/><br/>{{bond_paragraph}}By way of introduction" in body


def test_only_two_campaigns_and_other_channels_wait_until_the_email_has_room():
    """Ariel, 26 Oct 2026: two campaigns a month. Until the email has room for the bond paragraph, a
    channel outside our usual ones waits rather than going out without it."""
    hs, instantly, s = _two_companies()
    send.run("test", _without_paragraph(s), hs, instantly, log=quiet)
    camps = {b["name"]: cid for cid, b in instantly.campaigns.items()}
    main = send.campaign_name("Diablo |")
    assert set(camps) == {main}
    assert [l["email"] for l in instantly.leads[camps[main]]] == ["buyer@beta.example"]


def test_both_go_to_the_month_campaign_and_only_the_other_channel_gets_the_paragraph():
    hs, instantly, s = _two_companies()
    _with_paragraph(s)
    send.run("test", s, hs, instantly, log=quiet)
    camps = {b["name"]: cid for cid, b in instantly.campaigns.items()}
    main = send.campaign_name("Diablo |")
    assert set(camps) == {main}
    leads = {l["email"]: l for l in instantly.leads[camps[main]]}
    assert set(leads) == {"buyer@unihockey.example", "buyer@beta.example"}
    body = instantly.campaigns[camps[main]]["sequences"][0]["steps"][0]["variants"][0]["body"]
    text = send.render(body, leads["buyer@unihockey.example"])
    assert ("we noticed Unihockey Center equips floorball players and clubs, a community that takes its fitness "
            "seriously. We are a UK brand") in text
    assert "together.\n\nWhy we think our bond would be strong\n" + UNIHOCKEY_LINE + "\n\nBy way of introduction" in text
    # The usual channel gets exactly the usual email: no heading and no empty gap.
    usual = send.render(body, leads["buyer@beta.example"])
    assert "Why we think" not in usual and "together.\n\nBy way of introduction" in usual
    old_body = send.sequence_steps(load_settings()["send"])[0]["variants"][0]["body"]
    assert usual == send.render(old_body, leads["buyer@beta.example"])
    # The HTML is the same as the October "Other channels" email had.
    filled = body.replace("{{bond_paragraph}}", leads["buyer@unihockey.example"]["custom_variables"]["bond_paragraph"])
    assert "<div><b>Why we think our bond would be strong</b><br/>" + UNIHOCKEY_LINE + "</div><div><br></div><div>By way" in filled


def test_the_other_channels_campaigns_are_deleted_and_their_contacts_go_back_to_gate_2(tmp_path):
    """Ariel, 26 Oct 2026: delete the new campaigns and put their contacts back on gate 2."""
    hs, instantly, s = _two_companies()
    main = send.campaign_name("Diablo |")
    main_id = instantly.create_campaign({"name": main})["id"]
    other_id = instantly.create_campaign({"name": main + " | Other channels"})["id"]
    inbox_other_id = instantly.create_campaign({"name": main + " | Company inboxes | Other channels"})["id"]
    preview_id = instantly.create_campaign({"name": "TEST | Bond paragraph preview (delete me)"})["id"]
    instantly.leads[other_id] = [{"id": "L1", "email": "buyer@unihockey.example"}]
    instantly.leads[inbox_other_id] = [{"id": "L2", "email": "x@somewhere.example", "timestamp_last_contact": "2026-10-24"}]
    uni = next(cid for cid, r in hs.records["contacts"].items() if r["email"] == "buyer@unihockey.example")
    hs.records["contacts"][uni]["hs_lead_status"] = "ATTEMPTED_TO_CONTACT"
    notes = tmp_path / "timeline_notes.json"
    notes.write_text(json.dumps({"queued": [uni, "other"]}))
    from outreach import other_channels
    done = other_channels.retire(hs, instantly, _without_paragraph(s), quiet, notes_path=notes)
    assert done == {"back_to_gate2": 1, "kept": 1, "deleted": [main + " | Other channels"]}
    assert hs.records["contacts"][uni]["hs_lead_status"] == "APPROVED_TO_SEND"
    assert other_id not in instantly.campaigns and main_id in instantly.campaigns
    assert instantly.leads[inbox_other_id][0]["id"] == "L2"  # already emailed: never touched
    assert preview_id in instantly.campaigns  # kept until the two campaigns have room for the paragraph
    assert json.loads(notes.read_text())["queued"] == ["other"]  # its "added" note is written again later
    # Back on GATE2, it waits for the paragraph, then goes to the month's campaign with it.
    send.run("test", _with_paragraph(s), hs, instantly, log=quiet)
    assert [l["email"] for l in instantly.leads[main_id]] == ["buyer@unihockey.example", "buyer@beta.example"]
    assert preview_id not in instantly.campaigns


def test_leads_already_waiting_get_an_empty_paragraph_before_the_email_changes():
    hs, instantly, s = _two_companies()
    main = send.campaign_name("Diablo |")
    main_id = instantly.create_campaign({"name": main})["id"]
    instantly.leads[main_id] = [{"id": "B1", "email": "buyer@beta.example", "payload": {"personal_line": "x"}},
                                {"id": "B2", "email": "sent@beta.example", "timestamp_last_contact": "2026-10-25"}]
    from outreach import other_channels
    assert other_channels.fill_waiting(hs, instantly, _without_paragraph(s), quiet) == 0  # no room yet: nothing changes
    assert other_channels.fill_waiting(hs, instantly, _with_paragraph(s), quiet) == 1
    first = instantly.leads[main_id][0]
    assert first["custom_variables"]["bond_paragraph"] == "" and first["custom_variables"]["company_note"]
    assert "custom_variables" not in instantly.leads[main_id][1]  # already emailed: left alone
    assert other_channels.fill_waiting(hs, instantly, _with_paragraph(s), quiet) == 0  # once only


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


def test_the_preview_campaign_shows_the_three_cases():
    from outreach import bond_preview, other_channels
    instantly = FakeInstantly()
    s = load_settings()
    s["send"]["sending_accounts"] = ["one@getdiablo-test.com"]
    cid = bond_preview.run(instantly, s, log=quiet)
    camp = instantly.campaigns[cid]
    assert camp["name"] == other_channels.PREVIEW_NAME and not camp["name"].startswith("Diablo |")
    body = camp["sequences"][0]["steps"][0]["variants"][0]["body"]
    assert "{{bond_paragraph}}By way of introduction" in body
    sports, usual, older = instantly.leads[cid]
    assert all(l["email"].endswith("@example.com") for l in (sports, usual, older))
    assert "Why we think our bond would be strong\n" + bond_preview.SPORTS_LINE in send.render(body, sports)
    assert usual["custom_variables"]["bond_paragraph"] == "" and "bond_paragraph" not in older["custom_variables"]
    bond_preview.run(instantly, s, log=quiet)
    assert len(instantly.campaigns) == 1  # replaced, not added
    bond_preview.run(instantly, s, action="delete", log=quiet)
    assert instantly.campaigns == {}
