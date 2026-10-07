"""Instantly API v2 client: campaigns, leads and lead status."""

import os
import time

import requests

API = "https://api.instantly.ai/api/v2"


class InstantlyError(RuntimeError):
    pass


class Instantly:
    def __init__(self, api_key=None, session=None):
        self.api_key = api_key or os.environ.get("INSTANTLY_API_KEY")
        if not self.api_key:
            raise InstantlyError("INSTANTLY_API_KEY is not set.")
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )

    def request(self, method, path, **kwargs):
        for attempt in range(6):
            resp = self.session.request(method, API + path, timeout=60, **kwargs)
            if resp.status_code in (200, 201):
                return resp.json() if resp.content else {}
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise InstantlyError(f"{method} {path} failed with {resp.status_code}: {resp.text[:500]}")
        raise InstantlyError(f"{method} {path} kept failing after retries")

    def list_campaigns(self):
        items, cursor = [], None
        while True:
            params = {"limit": 100}
            if cursor:
                params["starting_after"] = cursor
            data = self.request("GET", "/campaigns", params=params)
            batch = data.get("items", [])
            items.extend(batch)
            cursor = data.get("next_starting_after")
            if not cursor or not batch:
                return items

    def create_campaign(self, body):
        return self.request("POST", "/campaigns", json=body)

    def update_campaign(self, campaign_id, body):
        return self.request("PATCH", f"/campaigns/{campaign_id}", json=body)

    def add_leads(self, campaign_id, leads):
        """Add up to 1,000 leads. Leads already anywhere in the workspace are skipped."""
        results = []
        for i in range(0, len(leads), 1000):
            body = {
                "campaign_id": campaign_id,
                "leads": leads[i : i + 1000],
                "skip_if_in_workspace": True,
            }
            results.append(self.request("POST", "/leads/add", json=body))
        return results

    def list_leads(self, campaign_id):
        items, cursor = [], None
        while True:
            body = {"campaign": campaign_id, "limit": 100}
            if cursor:
                body["starting_after"] = cursor
            data = self.request("POST", "/leads/list", json=body)
            batch = data.get("items", [])
            items.extend(batch)
            cursor = data.get("next_starting_after")
            if not cursor or not batch:
                return items
