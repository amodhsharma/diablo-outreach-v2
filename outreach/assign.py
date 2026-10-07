"""Give each approved company a salesperson (its HubSpot company owner).

Rules live in config/settings.yaml under `assignment`. For each company the most
specific matching rule wins (a rule naming the category beats one that does not; a
longer market such as "Mumbai, India" beats "India"). Within a rule, the company goes
to the salesperson who currently owns the fewest pipeline companies in that market,
so work is shared evenly. Companies that already have an owner keep it.
"""

from .common import PipelineError, market_matches


class Assigner:
    def __init__(self, hs, settings, log=print):
        cfg = settings.get("assignment") or {}
        self.hs, self.log = hs, log
        self.rules = cfg.get("rules") or []
        self.default = cfg.get("default_owners") or []
        self.enabled = bool(self.rules or self.default)
        self._ids = {}
        self._load = {}
        if self.enabled:
            missing = []
            for email in self._all_emails():
                oid = hs.owner_id(email)
                if oid:
                    self._ids[email.lower()] = oid
                else:
                    missing.append(email)
            if missing:
                raise PipelineError(
                    "These salespeople are not HubSpot users (check the email in "
                    f"config/settings.yaml, assignment): {', '.join(missing)}"
                )

    def _all_emails(self):
        emails = list(self.default)
        for rule in self.rules:
            emails.extend(rule.get("owners") or [])
        return sorted({e.strip() for e in emails if e and e.strip()})

    def owners_for(self, market, category_label):
        """Salespeople (emails) for a market and category, using the most specific rule."""
        best, best_score = None, -1
        for rule in self.rules:
            rule_market = rule.get("market") or ""
            rule_category = rule.get("category") or ""
            if rule_market and not market_matches(rule_market, market):
                continue
            if rule_category and rule_category.lower() != (category_label or "").lower():
                continue
            score = (1000 if rule_category else 0) + len(rule_market)
            if score > best_score:
                best, best_score = rule, score
        owners = (best or {}).get("owners") if best else self.default
        return [e.strip() for e in (owners or []) if e and e.strip()]

    def _current_load(self, owner_id, market):
        key = (owner_id, market)
        if key not in self._load:
            self._load[key] = self.hs.count("companies", [
                {"propertyName": "hubspot_owner_id", "operator": "EQ", "value": owner_id},
                {"propertyName": "diablo_market", "operator": "EQ", "value": market},
            ])
        return self._load[key]

    def pick(self, market, category_label):
        """Owner ID for a new company, or None if no rule applies."""
        if not self.enabled:
            return None
        emails = self.owners_for(market, category_label)
        if not emails:
            return None
        ids = [self._ids[e.lower()] for e in emails]
        chosen = min(ids, key=lambda oid: (self._current_load(oid, market), ids.index(oid)))
        self._load[(chosen, market)] += 1
        return chosen
