"""The channel check: the first filter for every company (HARD RULE, Ariel, 20 Nov 2026).

Before any company is selected, restarted or emailed, its channel is checked first, no matter what. Only the
channels research looks for since 10 Nov 2026 go ahead: distributors, wholesalers, importers and supermarket
chains (common.targeted). Where it is checked:

    button 3   the approved companies (GATE1 or Contact located), before Apollo is searched (find_contacts)
    button 3   the companies ready to restart (restart.auto_queue)
    button 4   every company before anyone there gets an introduction (send)
    button 4   the company of a person a reply pointed us to, before their first email (referral_intro)
    button 4   the old backlog, before a closed company is reopened (chain.run_backlog)

A company's channel is, in this order: config/company_channels.json (set by hand for companies research never
described, decided 20 Nov 2026), its research note in data/company_notes.json, then HubSpot's Industry Type.
    targeted       it goes ahead
    not targeted   it stops for good: the company is set to "Unqualified: Channel no longer targeted" (its contacts
                   follow at button 4's next run) and nobody there is emailed
    not known      it waits: nobody there is emailed, it is named in the run's log and in the daily email's
                   Initial stages (your input needed), until its channel is added to config/company_channels.json
"""

from .common import load_company_notes, targeted


def verdict(props, notes=None):
    """True (targeted), False (not targeted) or None (not known) for a company's properties."""
    return targeted(props.get("properties", props), notes)


def screen(hs, statuses, companies, log=print, close=True, notes=None):
    """companies: [company records] or {id: record}. Returns the set of company IDs that may go ahead. Those from a
    channel we do not target are set to "Unqualified: Channel no longer targeted" (close=False: only left out)."""
    records = list(companies.values()) if isinstance(companies, dict) else list(companies)
    notes = load_company_notes() if notes is None else notes
    allowed, stop, unknown = set(), [], []
    for c in records:
        v = verdict(c.get("properties") or {}, notes)
        if v:
            allowed.add(str(c["id"]))
        elif v is None:
            unknown.append(c)
        else:
            stop.append(c)

    def names(rows):
        return ", ".join(sorted(((r.get("properties") or {}).get("name") or "A company" for r in rows), key=str.lower))
    if stop:
        if close and statuses.has("companies", "channel_paused"):
            hs.update_tagged("companies", [(c["id"], statuses.props("companies", "channel_paused")) for c in stop])
            log(f"Channel check: {len(stop)} companies are not from a channel we target, so they are set to "
                f'"Unqualified: Channel no longer targeted" and nobody there is emailed: {names(stop)}')
        else:
            log(f"Channel check: {len(stop)} companies left out, not from a channel we target: {names(stop)}")
    if unknown:
        log(f"Channel check: {len(unknown)} companies wait, as their channel is not known (nobody there is emailed "
            f"until it is set in config/company_channels.json): {names(unknown)}")
    return allowed
