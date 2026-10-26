"""Channels outside Diablo's usual ones (agreed 23 Oct 2026, config/bond_channels.json).

Their first email carries the bold heading "Why we think our bond would be strong" and, under it,
the personal line giving the buyer's reason: who their customers are and why our products suit
those customers. Every other channel keeps the usual email. Standard library only, so the
outreach-mail-writing scripts can use it too.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOND_FILE = ROOT / "config" / "bond_channels.json"

# Words in a typed or research channel that point to one of the channels in the file, for channels
# typed by hand in button 2 ("sports shops", "vending"). Distributors and wholesalers never count,
# whatever else their name says ("kiosk and convenience wholesalers" is a usual channel).
KEYWORDS = {
    "sport": "sports shops and sports nutrition shops",
    "fitness": "sports shops and sports nutrition shops",
    "pharmac": "pharmacy and drugstore chains",
    "drugstore": "pharmacy and drugstore chains",
    "office snack": "office snack and pantry suppliers",
    "pantry": "office snack and pantry suppliers",
    "petrol": "petrol station and convenience chains",
    "vending": "snack vending operators",
    "gifting": "corporate gifting and hamper companies",
    "hamper": "corporate gifting and hamper companies",
    "hospital": "hospital and care home shops",
    "care home": "hospital and care home shops",
    "minibar": "hotel minibar suppliers",
    "leisure": "leisure and venue snack suppliers",
    "venue": "leisure and venue snack suppliers",
    "travel retail": "travel retail",
    "promotional": "promotional merchandise companies",
}
USUAL_WORDS = ("distribut", "wholesal", "importer")


def load(path=None):
    """The file as a dict; an empty set of channels when it is missing or cannot be read."""
    try:
        return json.loads(Path(path or BOND_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"channels": {}}


def bond_channel(channel, config=None):
    """The channel's name in config/bond_channels.json when it is outside our usual channels, else ""."""
    config = load() if config is None else config
    channels = {k.strip().lower(): k for k in (config.get("channels") or {})}
    text = " ".join(str(channel or "").lower().split())
    if not text:
        return ""
    if text in channels:
        return channels[text]
    if any(w in text for w in USUAL_WORDS):
        return ""
    for word, name in KEYWORDS.items():
        if word in text and name.lower() in channels:
            return channels[name.lower()]
    return ""


def bond_reason(channel, config=None):
    """The buyer's reason for a channel outside our usual ones, else ""."""
    config = load() if config is None else config
    name = bond_channel(channel, config)
    return (config.get("channels") or {}).get(name, "") if name else ""


# 26 Oct 2026 (Ariel): only two campaigns a month, one for people and one for everything else. The
# heading and the buyer's reason travel with each contact as its own "bond_paragraph", filled in for
# channels outside our usual ones and empty for every other channel, so the same email suits both.
VARIABLE = "bond_paragraph"


def paragraph(line, config=None):
    """The bold heading with the personal line under it, as its own paragraph of the email (it ends
    the paragraph it sits in and starts the next one, the way the email's other paragraphs are kept).
    Empty when there is no line."""
    import html
    config = load() if config is None else config
    line = " ".join(str(line or "").split())
    if not line:
        return ""
    heading = config.get("heading") or "Why we think our bond would be strong"
    return f"<b>{html.escape(heading, quote=False)}</b><br/>{html.escape(line, quote=False)}</div><div><br></div><div>"
