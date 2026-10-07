"""Small HubSpot API client with retries. Only uses the private app token."""

import os
import time

import requests

API = "https://api.hubapi.com"


class HubSpotError(RuntimeError):
    pass


class HubSpot:
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

    def search(self, object_type, filters, properties, limit=100, max_results=1000):
        """Search records. filters: list of HubSpot filter dicts (ANDed)."""
        results, after = [], None
        while len(results) < max_results:
            body = {
                "filterGroups": [{"filters": filters}] if filters else [],
                "properties": properties,
                "limit": min(limit, 100, max_results - len(results)),
            }
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

    def batch_create(self, object_type, records):
        """records: list of property dicts. Returns created records in order."""
        out = []
        for chunk in _chunks(records, 100):
            body = {"inputs": [{"properties": p} for p in chunk]}
            data = self.request("POST", f"/crm/v3/objects/{object_type}/batch/create", json=body)
            out.extend(data.get("results", []))
        return out

    def batch_update(self, object_type, updates):
        """updates: list of (record_id, properties)."""
        for chunk in _chunks(updates, 100):
            body = {"inputs": [{"id": str(i), "properties": p} for i, p in chunk]}
            self.request("POST", f"/crm/v3/objects/{object_type}/batch/update", json=body)

    def option_labels(self, object_type, name):
        """{value: label} for a dropdown field."""
        prop = self.request("GET", f"/crm/v3/properties/{object_type}/{name}")
        return {o["value"]: o["label"] for o in prop.get("options", [])}

    def ensure_option(self, object_type, name, label, value):
        """Add a dropdown option if it is missing. Returns True when it was added."""
        prop = self.request("GET", f"/crm/v3/properties/{object_type}/{name}")
        options = prop.get("options", [])
        if any(o["value"] == value for o in options):
            return False
        options = options + [{"label": label, "value": value, "displayOrder": len(options)}]
        self.request("PATCH", f"/crm/v3/properties/{object_type}/{name}", json={"options": options})
        return True

    def associate_default(self, from_type, to_type, pairs):
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
