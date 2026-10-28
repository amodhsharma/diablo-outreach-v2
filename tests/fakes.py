"""In-memory stand-ins for HubSpot, Apollo and Instantly used by the tests."""

import itertools

from outreach.hubspot_client import TagGuard
from outreach.schema import TAG, TAG_PROPERTY

# Lead Status choices as in the live account (value: label), plus the three the setup adds.
LIVE_COMPANY_STATUS = {"New": "New", "Missing Info": "Missing Info", "Emailed": "Emailed",
                       "In Progress": "In Progress", "Unqualified": "Unqualified",
                       "Attempted to Contact": "Attempted to Contact", "Won": "Won",
                       "GATE1: Approved for outreach": "GATE1: Approved for outreach",
                       "Contacted, but no response, unqualified": "Contacted, but no response, unqualified",
                       "Missing info on Apollo": "Missing info on Apollo",
                       "Contact exists, not AUTO-OUTREACH": "Contact exists, not AUTO-OUTREACH",
                       "Invalid inbox: Mail bounced, need input": "Invalid inbox: Mail bounced, need input"}
LIVE_CONTACT_STATUS = {"NEW": "New", "MISSING INFO": "Missing Info", "Emailed": "Emailed",
                       "IN_PROGRESS": "In Progress", "UNQUALIFIED": "Unqualified",
                       "ATTEMPTED_TO_CONTACT": "Attempted to Contact", "WON": "WON",
                       "NEW_PERSONAL_LINE_FILLED": "New, Personal line filled", "APPROVED_TO_SEND": "GATE2: Approved to send",
                       "FORWARD_SENT": "Forward sent", "REMINDER_SENT": "Reminder sent",
                       "COLLEAGUE_REPLIED_POSITIVE": "Colleague replied: positive",
                       "COLLEAGUE_REPLIED_NEGATIVE": "Colleague replied: negative",
                       "COLLEAGUE_REPLIED": "Colleague replied", "COLLEAGUE_OPTED_OUT": "Colleague opted out",
                       "UNQUALIFIED_COMPANY": "Unqualified company",
                       "CONTACTED_NO_RESPONSE_UNQUALIFIED": "Contacted, but no response, unqualified",
                       "UNQUALIFIED_CONTACT_CORRUPT": "Unqualified Contact: Contact corrupt"}


class FakeCRM(TagGuard):
    """Implements the HubSpot client methods the jobs use, in memory. The real TagGuard runs on
    top of it, so the tests check the safety rules themselves."""

    def __init__(self, portal=999):
        self.portal = portal
        self.records = {"companies": {}, "contacts": {}}
        self.links = {}  # contact id -> [company id]
        self._ids = itertools.count(1000)
        self.options = {("companies", "hs_lead_status"): dict(LIVE_COMPANY_STATUS),
                        ("contacts", "hs_lead_status"): dict(LIVE_CONTACT_STATUS)}
        self.writes = []  # (action, object, ids) for every change, to check what was touched

    def portal_id(self):
        return self.portal

    def add(self, object_type, tagged=True, **props):
        """Put a record straight in (as research or a person would). tagged=False makes it one
        of the team's own records."""
        rid = str(next(self._ids))
        self.records[object_type][rid] = dict(props, **({TAG_PROPERTY: TAG} if tagged else {}))
        return rid

    def _match(self, props, f):
        val = props.get(f["propertyName"])
        op = f["operator"]
        if op == "HAS_PROPERTY":
            return val not in (None, "")
        if op == "NOT_HAS_PROPERTY":
            return val in (None, "")
        if op == "EQ":
            return str(val).lower() == str(f["value"]).lower()
        if op in ("GTE", "LT") and f["propertyName"] in ("createdate", "hs_lastmodifieddate"):
            from outreach.next_in_line import parse_time
            when, limit = parse_time(val), parse_time(f["value"])
            if when is None:
                return False
            return when >= limit if op == "GTE" else when < limit
        if op == "GTE":
            return val is not None and int(val) >= int(f["value"])
        if op == "IN":
            return val is not None and str(val).lower() in {v.lower() for v in f["values"]}
        raise AssertionError(op)

    def search(self, object_type, filters, properties, limit=100, max_results=1000, sorts=None):
        out = []
        for rid, props in self.records[object_type].items():
            if all(self._match(props, f) for f in filters):
                out.append({"id": rid, "properties": dict(props)})
        return out[:max_results]

    def count(self, object_type, filters):
        return len(self.search(object_type, filters, []))

    owners = {"sam@diablosugarfree.com": "11", "ria@diablosugarfree.com": "22", "kai@diablosugarfree.com": "33"}

    def option_labels(self, object_type, name):
        return dict(self.options.get((object_type, name), {}))

    missing_properties = set()  # e.g. {("contacts", "diablo_contact_source")} for an account without it

    def has_property(self, object_type, name):
        return (object_type, name) not in self.missing_properties

    def list_all(self, object_type, properties):
        return [{"id": rid, "properties": dict(p)} for rid, p in self.records[object_type].items()]

    def owner_id(self, email):
        return self.owners.get(email.lower())

    def batch_read(self, object_type, ids, properties, id_property=None):
        out = []
        for i in ids:
            for rid, props in self.records[object_type].items():
                key = props.get(id_property) if id_property else rid
                if key is not None and str(key).lower() == str(i).lower():
                    out.append({"id": rid, "properties": dict(props)})
        return out

    def _batch_create(self, object_type, records):
        if object_type == "companies":
            domains = {r["domain"] for r in records if r.get("domain")}
            existing = {p.get("domain") for p in self.records["companies"].values()}
            assert not (domains & existing), "company with this domain already exists"
        out = [{"id": self.add(object_type, tagged=False, **r), "properties": r} for r in records]
        self.writes.append(("create", object_type, [o["id"] for o in out]))
        return out

    def _batch_update(self, object_type, updates):
        self.writes.append(("update", object_type, [str(rid) for rid, _ in updates]))
        for rid, props in updates:
            self.records[object_type][str(rid)].update(props)

    def _associate_default(self, from_type, to_type, pairs):
        self.writes.append(("link", from_type, [str(a) for a, _ in pairs]))
        for a, b in pairs:
            self.links.setdefault(str(a), []).append(str(b))

    def _create_note(self, object_type, record_id, text):
        self.notes = getattr(self, "notes", [])
        self.notes.append((object_type, str(record_id), text))
        return {"id": f"note{len(self.notes)}"}

    def _associate_primary(self, pairs):
        self.writes.append(("primary", "contacts", [str(a) for a, _ in pairs]))
        self.primary = getattr(self, "primary", {})
        for a, b in pairs:
            if str(b) not in self.links.setdefault(str(a), []):
                self.links[str(a)].append(str(b))
            self.primary[str(a)] = str(b)

    def history(self, object_type, ids, prop, properties=()):
        """self.past: {(object type, id): [(value, timestamp)]} set by a test, newest first."""
        past = getattr(self, "past", {})
        return {str(i): (dict(self.records[object_type][str(i)]), list(past.get((object_type, str(i)), [])))
                for i in ids if str(i) in self.records[object_type]}

    def associated_types(self, from_type, to_type, ids):
        assert (from_type, to_type) == ("contacts", "companies")
        primary = getattr(self, "primary", {})
        return {str(i): {c: ({279, 1} if primary.get(str(i)) == c else {279}) for c in self.links.get(str(i), [])}
                for i in ids if self.links.get(str(i))}

    def associated_ids(self, from_type, to_type, ids):
        if from_type == "companies":  # links are stored contact -> companies
            return {str(i): [c for c, cos in self.links.items() if str(i) in cos] for i in ids}
        return {str(i): self.links.get(str(i), []) for i in ids}


class FakeApollo:
    def __init__(self, people_by_domain, emails):
        self.people_by_domain = people_by_domain  # everyone Apollo holds per domain
        self.emails = emails  # person id -> (email, status)
        self.revealed = []
        self.searches = []

    def search_people(self, domain, titles, seniorities=None, per_page=25):
        self.searches.append((domain, list(titles), list(seniorities or [])))
        people = list(self.people_by_domain.get(domain, []))
        if seniorities:
            people = [p for p in people if p.get("seniority") in seniorities]
        return people

    def reveal_emails(self, ids):
        assert len(ids) <= 10
        self.revealed.extend(ids)
        out = []
        for pid in ids:
            if pid in self.emails:
                email, status = self.emails[pid]
                person = {"id": pid, "email": email, "email_status": status,
                          "first_name": "First" + pid, "last_name": "Last", "title": "Category Manager"}
                for people in self.people_by_domain.values():
                    for known in people:
                        if known.get("id") == pid and known.get("title"):
                            person["title"] = known["title"]
                out.append(person)
        return out


class FakeInstantly:
    blocked = set()

    def blocklist(self):
        return set(self.blocked)

    def __init__(self):
        self.campaigns = {}
        self.leads = {}

    def list_campaigns(self):
        return [{"id": cid, "name": c["name"], "sequences": c.get("sequences")} for cid, c in self.campaigns.items()]

    def update_campaign(self, campaign_id, body):
        self.campaigns[campaign_id].update(body)
        self.updates = getattr(self, "updates", 0) + 1
        return {"id": campaign_id}

    def create_campaign(self, body):
        cid = f"camp{len(self.campaigns) + 1}"
        self.campaigns[cid] = body
        self.leads[cid] = []
        return {"id": cid}

    def add_leads(self, campaign_id, leads):
        # Mimics skip_if_in_workspace: an email already anywhere is skipped.
        known = {l["email"] for ls in self.leads.values() for l in ls}
        new = [l for l in leads if l["email"] not in known]
        self.leads[campaign_id].extend(new)
        return [{"leads_uploaded": len(new), "skipped_count": len(leads) - len(new),
                 "created_leads": [{"email": l["email"]} for l in new]}]

    def list_leads(self, campaign_id):
        return self.leads.get(campaign_id, [])

    def update_lead(self, lead_id, body):
        for ls in self.leads.values():
            for lead in ls:
                if lead.get("id") == lead_id:
                    lead.update(body)
        return {"id": lead_id}

    def delete_lead(self, lead_id):
        for cid in self.leads:
            self.leads[cid] = [l for l in self.leads[cid] if l.get("id") != lead_id]
        return {}

    def delete_campaign(self, campaign_id):
        self.campaigns.pop(campaign_id)
        self.leads.pop(campaign_id, None)
        return {}




class FakeEmails:
    """Instantly's email threads: what each address was sent (campaign, replies, forwards) and sent back."""

    def __init__(self):
        self.emails, self.replies, self.forwards = [], [], []

    def _add(self, **e):
        e.setdefault("id", f"e{len(self.emails) + 1}")
        e.setdefault("eaccount", "sales@diablosnosugar.com")
        self.emails.append(e)
        return e

    def campaign_email(self, to, when, subject="Partnering to establish Diablo"):
        return self._add(ue_type=1, to_address_email_list=to, lead=to, subject=subject, timestamp_email=when)

    def received(self, sender, when, subject="Re: hello", text=None):
        extra = {"body": {"text": text}} if text is not None else {}
        return self._add(ue_type=2, from_address_email=sender, lead=sender, subject=subject, timestamp_email=when,
                         **extra)

    def thread_emails(self, lead_email):
        lead_email = lead_email.lower()
        return [e for e in self.emails if lead_email in (e.get("lead"), e.get("to_address_email_list"),
                                                        e.get("from_address_email"))]

    def reply(self, email, subject, html, text, keep_subject=False):
        self.replies.append({"to": email, "subject": subject, "html": html, "text": text})
        import datetime as dt
        return self._add(ue_type=3, to_address_email_list=email["to_address_email_list"], lead=email["lead"],
                         subject=subject, timestamp_email=dt.datetime.now(dt.timezone.utc).isoformat())

    def send_in_thread(self, email, to, subject, html, text):
        """Person 1's reminder (20 Oct 2026): sent to their own address, in their thread."""
        self.replies.append({"to": email, "address": to, "subject": subject, "html": html, "text": text})
        import datetime as dt
        return self._add(ue_type=3, to_address_email_list=to, lead=email["lead"], subject=subject,
                         timestamp_email=dt.datetime.now(dt.timezone.utc).isoformat())

    def forward(self, email, to, subject, html, text):
        self.forwards.append({"of": email, "to": to, "subject": subject, "html": html, "text": text})
        import datetime as dt
        # Filed under the address it was forwarded from, as Instantly may do.
        return self._add(ue_type=3, to_address_email_list=to, lead=email["lead"], subject=subject,
                         timestamp_email=dt.datetime.now(dt.timezone.utc).isoformat())
