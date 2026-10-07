"""Apollo API client: free people search and paid email reveal."""

import os
import time

import requests

API = "https://api.apollo.io/api/v1"


class ApolloError(RuntimeError):
    pass


class Apollo:
    def __init__(self, api_key=None, session=None):
        self.api_key = api_key or os.environ.get("APOLLO_API_KEY")
        if not self.api_key:
            raise ApolloError("APOLLO_API_KEY is not set.")
        self.session = session or requests.Session()
        self.session.headers.update(
            {"x-api-key": self.api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"}
        )

    def _post(self, path, params=None, body=None):
        for attempt in range(6):
            resp = self.session.post(API + path, params=params, json=body, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(min(float(resp.headers.get("retry-after", 2 ** attempt)), 60))
                continue
            raise ApolloError(f"POST {path} failed with {resp.status_code}: {resp.text[:500]}")
        raise ApolloError(f"POST {path} kept failing after retries")

    def search_people(self, domain, titles, seniorities=None, per_page=25):
        """Free search: people at one company domain. Returns no emails."""
        params = [("q_organization_domains_list[]", domain), ("include_similar_titles", "true"),
                  ("per_page", str(per_page)), ("page", "1")]
        params += [("person_titles[]", t) for t in titles]
        params += [("person_seniorities[]", s) for s in (seniorities or [])]
        data = self._post("/mixed_people/api_search", params=params)
        return data.get("people", [])

    def reveal_emails(self, person_ids):
        """Paid: reveal work emails for up to 10 people. 1 credit per person with data."""
        if not person_ids:
            return []
        if len(person_ids) > 10:
            raise ApolloError("reveal_emails takes at most 10 people per call")
        body = {"details": [{"id": pid} for pid in person_ids]}
        params = {"reveal_personal_emails": "false", "reveal_phone_number": "false"}
        data = self._post("/people/bulk_match", params=params, body=body)
        return [m for m in data.get("matches", []) if m]
