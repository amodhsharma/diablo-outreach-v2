"""A campaign to look at the bond paragraph in Instantly before anyone gets it (26 Oct 2026, Ariel).

It creates "TEST | Bond paragraph preview (delete me)" in Instantly: never launched, with the month's
email as it will be once it has room for the bond paragraph, and three made-up example contacts (on
example.com, which nobody can receive):
  1. a sports shop: the bold heading and its line show;
  2. a distributor: no heading and no empty gap (the paragraph is empty);
  3. a distributor added before the paragraph existed: the same as 2 (it has no paragraph at all).
In Instantly: open the campaign, Sequences, Preview, "Load data for lead", pick each one in turn, and
"Send test email" to your own address. Button 4 deletes this campaign by itself once the two
campaigns get the new email; or press this button again with "delete".
It is not a "Diablo |" campaign, so Sync, Send and the health check never look at it.
"""

import argparse
import copy
import sys

from .common import load_settings
from .instantly_client import Instantly, InstantlyError
from .next_in_line import lead_for
from .other_channels import PREVIEW_NAME
from .schema import COMPANY_NOTE, PERSONAL_LINE

SPORTS_LINE = ("We have great respect for the way your team looks after the runners and cyclists of your city. "
               "Your customers already put real effort into staying active, and we believe sugar free snacks "
               "alongside the equipment they come in for may suit those very same people. We would be grateful "
               "for the opportunity to discuss whether this could be a worthwhile addition to your shop.")


def _lead(email, first, last, note, line, company, channel):
    contact = {"properties": {"email": email, "firstname": first, "lastname": last, "jobtitle": "Owner",
                              PERSONAL_LINE: line, COMPANY_NOTE: note}}
    return contact, {"name": company, "domain": email.split("@")[1], "country": "Switzerland",
                     "industry_type": channel}


def preview_leads():
    from .send import with_bond
    sports = _lead("preview-sports-shop@example.com", "Preview", "Sports Shop",
                   "runs two sports shops for runners and cyclists", SPORTS_LINE, "Example Sports Shop",
                   "Sports shops and sports nutrition shops")
    usual = _lead("preview-distributor@example.com", "Preview", "Distributor",
                  "supplies kiosks and petrol station shops across the country", "A line that is not shown.",
                  "Example Distribution", "Distributors")
    older = _lead("preview-older-lead@example.com", "Preview", "Older Lead",
                  "supplies kiosks and petrol station shops across the country", "A line that is not shown.",
                  "Example Distribution", "Distributors")
    leads = [with_bond(lead_for(c, comp, {}), comp, {}) for c, comp in (sports, usual, older)]
    leads[2]["custom_variables"].pop("bond_paragraph")  # added before the paragraph existed
    return leads


def run(instantly, settings, action="create", log=print):
    from .send import PERSON, campaign_body
    for camp in instantly.list_campaigns():
        if camp.get("name") == PREVIEW_NAME:
            instantly.delete_campaign(camp["id"])
            log(f"Deleted the earlier preview campaign: {PREVIEW_NAME}")
    if action == "delete":
        return None
    s = copy.deepcopy(settings)
    s["send"]["templates"] = dict(s["send"]["templates"], first_email="templates/template_6.json")
    body = campaign_body(PREVIEW_NAME, "", s, kind=PERSON)
    camp_id = instantly.create_campaign(body)["id"]
    results = instantly.add_leads(camp_id, preview_leads())
    added = sum(r.get("leads_uploaded") or 0 for r in results)
    log(f'Created "{PREVIEW_NAME}" (never launched) with {added} example contacts. In Instantly: open it, '
        'Sequences, Preview, "Load data for lead", pick each example in turn, then "Send test email" to '
        "your own address.")
    return camp_id


def main(argv=None):
    p = argparse.ArgumentParser(description="The bond paragraph preview campaign in Instantly")
    p.add_argument("--action", default="create", choices=["create", "delete"])
    args = p.parse_args(argv)
    try:
        run(Instantly(), load_settings(), args.action)
    except InstantlyError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
