"""Small HubSpot API client with retries. Only uses the private app token.

Safety (agreed 13 Oct 2026): the pipeline only ever changes companies and contacts whose Lead
Source is AUTO-OUTREACH. Jobs never call HubSpot's write endpoints directly: they go through
TagGuard below, whose create, update and associate methods check the tag on every record first
and stop the whole job if any record lacks it. Reading untagged records is allowed (the
duplicate checks must see every company), changing them is not.
"""

import os
import time

import requests

from .schema import TAG, TAG_PROPERTY

API = "https://api.hubapi.com"


class HubSpotError(RuntimeError):
    pass


class TagGuardError(HubSpotError):
    """A job tried to change a record that does not carry the AUTO-OUTREACH tag."""


def tagged(props):
    """True only when Lead Source is exactly AUTO-OUTREACH."""
    return (props or {}).get(TAG_PROPERTY) == TAG


TAG_FILTER = {"propertyName": TAG_PROPERTY, "operator": "EQ", "value": TAG}


class TagGuard:
    """The only way jobs change HubSpot. Needs the raw methods search, batch_read,
    _batch_create, _batch_update and _associate_default from the class it is mixed into."""

    # ---- reading pipeline records ------------------------------------------

    def tagged_search(self, object_type, filters, properties, max_results=1000):
        """Search AUTO-OUTREACH records only: the tag is always one of the filters, and every
        result is checked again before it is returned."""
        props = sorted(set(properties) | {TAG_PROPERTY})
        rows = self.search(object_type, list(filters) + [TAG_FILTER], props, max_results=max_results)
        return [r for r in rows if tagged(r.get("properties"))]

    def tagged_read(self, object_type, ids, properties, id_property=None):
        """Read records by id (or email); records without the tag are left out."""
        props = sorted(set(properties) | {TAG_PROPERTY})
        rows = self.batch_read(object_type, ids, props, id_property=id_property) if ids else []
        return [r for r in rows if tagged(r.get("properties"))]

    def tagged_count(self, object_type, filters):
        return self.count(object_type, list(filters) + [TAG_FILTER])

    # ---- changing pipeline records -----------------------------------------

    def _check_tags(self, object_type, ids, action):
        ids = sorted({str(i) for i in ids})
        if not ids:
            return
        found = {str(r["id"]): r.get("properties") for r in self.batch_read(object_type, ids, [TAG_PROPERTY])}
        bad = [i for i in ids if not tagged(found.get(i))]
        if bad:
            raise TagGuardError(
                f"SAFETY STOP: tried to {action} {len(bad)} {object_type} without Lead Source "
                f"{TAG} (record IDs {', '.join(bad[:10])}). Nothing was saved. The pipeline only "
                f"changes records it created itself.")

    def create_tagged(self, object_type, records):
        """Create records, always with Lead Source = AUTO-OUTREACH."""
        records = [dict(r, **{TAG_PROPERTY: TAG}) for r in records]
        return self._batch_create(object_type, records) if records else []

    def update_tagged(self, object_type, updates):
        """updates: list of (record_id, properties). Every record is read again first; if any
        lacks the tag, nothing is saved and the job stops."""
        merged = {}
        for i, p in updates:  # one change per record (HubSpot refuses a batch naming a record twice)
            if p:
                merged.setdefault(str(i), {}).update(p)
        updates = list(merged.items())
        if not updates:
            return
        for _, p in updates:
            if TAG_PROPERTY in p:
                raise TagGuardError(f"SAFETY STOP: the pipeline never changes {TAG_PROPERTY}.")
        self._check_tags(object_type, [i for i, _ in updates], "change")
        self._batch_update(object_type, updates)

    def note_tagged(self, object_type, notes):
        """Add a note to the timeline of AUTO-OUTREACH records: [(record id, text)]."""
        notes = [(str(rid), text) for rid, text in notes if text]
        if not notes:
            return []
        self._check_tags(object_type, [rid for rid, _ in notes], "add a note to")
        return [self._create_note(object_type, rid, text) for rid, text in notes]

    def associate_tagged(self, from_type, to_type, pairs):
        """Link records; both sides must carry the tag."""
        pairs = [(str(a), str(b)) for a, b in pairs]
        if not pairs:
            return
        self._check_tags(from_type, [a for a, _ in pairs], "link")
        self._check_tags(to_type, [b for _, b in pairs], "link")
        self._associate_default(from_type, to_type, pairs)


class HubSpot(TagGuard):
    def __init__(self, token=None, session=None):
        self.token = token or os.environ.get("HUBSPOT_TOKEN")
        if not self.token:
            raise HubSpotError(
                "HUBSPOT_TOKEN is not set. Add the private app key as a secret "
                "(GitHub) or an environment variable (your computer)."
            )
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        )

    def request(self, method, path, ok=(200, 201, 204), **kwargs):
        """Call the API, retrying on rate limits and server errors."""
        for attempt in range(6):
            resp = self.session.request(method, API + path, timeout=30, **kwargs)
            if resp.status_code in ok:
                return resp.json() if resp.content else {}
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 30))
                continue
            raise HubSpotError(
                f"{method} {path} failed with {resp.status_code}: {resp.text[:500]}"
            )
        raise HubSpotError(f"{method} {path} kept failing after retries")

    def portal_id(self):
        """Return the account (portal) ID the token belongs to."""
        for path in ("/account-info/v3/details", "/integrations/v1/me"):
            try:
                data = self.request("GET", path)
            except HubSpotError:
                continue
            pid = data.get("portalId") or data.get("hubId")
            if pid:
                return int(pid)
        raise HubSpotError("Could not work out which HubSpot account this key belongs to.")

    # ---- CRM records -------------------------------------------------------

    def search(self, object_type, filters, properties, limit=100, max_results=1000, sorts=None):
        """Search records. filters: list of HubSpot filter dicts (ANDed). HubSpot's search
        never returns more than 10,000 records; use list_all for everything."""
        results, after = [], None
        while len(results) < max_results:
            body = {
                "filterGroups": [{"filters": filters}] if filters else [],
                "properties": properties,
                "limit": min(limit, 100, max_results - len(results)),
            }
            if sorts:
                body["sorts"] = sorts
            if after:
                body["after"] = after
            data = self.request("POST", f"/crm/v3/objects/{object_type}/search", json=body)
            results.extend(data.get("results", []))
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                break
            time.sleep(0.25)  # search API allows about 5 requests a second
        return results[:max_results]

    def count(self, object_type, filters):
        """How many records match the filters."""
        body = {"filterGroups": [{"filters": filters}] if filters else [], "properties": ["hs_object_id"], "limit": 1}
        return int(self.request("POST", f"/crm/v3/objects/{object_type}/search", json=body).get("total", 0))

    def owner_id(self, email):
        """HubSpot owner (user) ID for an email address, or None if no such user."""
        data = self.request("GET", "/crm/v3/owners", params={"email": email, "limit": 1})
        rows = data.get("results", [])
        return str(rows[0]["id"]) if rows else None

    def owner_names(self):
        """{owner ID: "First Last"} for every HubSpot user (read only)."""
        out, after = {}, None
        while True:
            params = {"limit": 100, **({"after": after} if after else {})}
            data = self.request("GET", "/crm/v3/owners", params=params)
            for o in data.get("results", []):
                name = " ".join(x for x in (o.get("firstName"), o.get("lastName")) if x) or o.get("email") or ""
                out[str(o["id"])] = name
            after = ((data.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return out

    def batch_read(self, object_type, ids, properties, id_property=None):
        """Read records by id (or by a unique property such as email). Missing ones are skipped."""
        out = []
        for chunk in _chunks(list(ids), 100):
            body = {"inputs": [{"id": str(i)} for i in chunk], "properties": properties}
            if id_property:
                body["idProperty"] = id_property
            data = self.request(
                "POST", f"/crm/v3/objects/{object_type}/batch/read", ok=(200, 207), json=body
            )
            out.extend(data.get("results", []))
        return out

    def list_all(self, object_type, properties):
        """Every record of a type, with no 10,000 limit (HubSpot's plain list, 100 at a time)."""
        out, after = [], None
        while True:
            params = {"limit": 100, "properties": ",".join(properties), "archived": "false"}
            if after:
                params["after"] = after
            data = self.request("GET", f"/crm/v3/objects/{object_type}", params=params)
            out.extend(data.get("results", []))
            after = (data.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return out
            time.sleep(0.11)  # stay under 10 requests a second

    def _batch_create(self, object_type, records):
        """records: list of property dicts. Returns created records in order."""
        out = []
        for chunk in _chunks(records, 100):
            body = {"inputs": [{"properties": p} for p in chunk]}
            data = self.request("POST", f"/crm/v3/objects/{object_type}/batch/create", json=body)
            out.extend(data.get("results", []))
        return out

    def _batch_update(self, object_type, updates):
        """updates: list of (record_id, properties)."""
        for chunk in _chunks(updates, 100):
            body = {"inputs": [{"id": str(i), "properties": p} for i, p in chunk]}
            self.request("POST", f"/crm/v3/objects/{object_type}/batch/update", json=body)

    # HubSpot's own association types: note to contact and note to company.
    NOTE_ASSOCIATION = {"contacts": 202, "companies": 190}

    def _create_note(self, object_type, record_id, text):
        import datetime as _dt
        body = {"properties": {"hs_timestamp": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "hs_note_body": text},
                "associations": [{"to": {"id": str(record_id)},
                                  "types": [{"associationCategory": "HUBSPOT_DEFINED",
                                             "associationTypeId": self.NOTE_ASSOCIATION[object_type]}]}]}
        return self.request("POST", "/crm/v3/objects/notes", json=body)

    def has_property(self, object_type, name):
        """True when the account has this field (e.g. a field added by a newer button 1 run)."""
        try:
            prop = self.request("GET", f"/crm/v3/properties/{object_type}/{name}", ok=(200, 404))
        except HubSpotError:
            return False
        return bool(prop.get("name"))

    def option_labels(self, object_type, name):
        """{value: label} for a dropdown field."""
        prop = self.request("GET", f"/crm/v3/properties/{object_type}/{name}")
        return {o["value"]: o["label"] for o in prop.get("options", [])}

    def _associate_default(self, from_type, to_type, pairs):
        """pairs: list of (from_id, to_id). Creates HubSpot's default association."""
        for chunk in _chunks(pairs, 100):
            body = {"inputs": [{"from": {"id": str(a)}, "to": {"id": str(b)}} for a, b in chunk]}
            self.request(
                "POST",
                f"/crm/v4/associations/{from_type}/{to_type}/batch/associate/default",
                json=body,
            )

    def associated_ids(self, from_type, to_type, ids):
        """Return {from_id: [to_id, ...]}."""
        out = {}
        for chunk in _chunks(list(ids), 100):
            body = {"inputs": [{"id": str(i)} for i in chunk]}
            data = self.request(
                "POST",
                f"/crm/v4/associations/{from_type}/{to_type}/batch/read",
                ok=(200, 207),
                json=body,
            )
            for row in data.get("results", []):
                out[str(row["from"]["id"])] = [str(t["toObjectId"]) for t in row.get("to", [])]
        return out


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]
