"""In-memory stand-ins for HubSpot, Apollo and Instantly used by the tests."""

import itertools


class FakeCRM:
    """Implements the HubSpot client methods the jobs use, in memory."""

    def __init__(self, portal=999):
        self.portal = portal
        self.records = {"companies": {}, "contacts": {}}
        self.links = {}  # contact id -> [company id]
        self._ids = itertools.count(1000)
        self.options = {}  # (object, property) -> {value: label}

    def portal_id(self):
        return self.portal

    def add(self, object_type, **props):
        rid = str(next(self._ids))
        self.records[object_type][rid] = dict(props)
        return rid

    def _match(self, props, f):
        val = props.get(f["propertyName"])
        op = f["operator"]
        if op == "HAS_PROPERTY":
            return val not in (None, "")
        if op == "EQ":
            return str(val).lower() == str(f["value"]).lower()
        if op == "IN":
            return val is not None and str(val).lower() in {v.lower() for v in f["values"]}
        raise AssertionError(op)

    def search(self, object_type, filters, properties, limit=100, max_results=1000):
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

    def ensure_option(self, object_type, name, label, value):
        opts = self.options.setdefault((object_type, name), {})
        if value in opts:
            return False
        opts[value] = label
        return True

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

    def batch_create(self, object_type, records):
        if object_type == "companies":
            domains = {r["domain"] for r in records if r.get("domain")}
            existing = {p.get("domain") for p in self.records["companies"].values()}
            assert not (domains & existing), "company with this domain already exists"
        return [{"id": self.add(object_type, **r), "properties": r} for r in records]

    def batch_update(self, object_type, updates):
        for rid, props in updates:
            self.records[object_type][str(rid)].update(props)

    def associate_default(self, from_type, to_type, pairs):
        for a, b in pairs:
            self.links.setdefault(str(a), []).append(str(b))

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


