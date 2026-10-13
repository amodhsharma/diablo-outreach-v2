"""The strict check for outreach-mail-writing output. Standard library only.

Usage:
    python3 check_lines.py mail/lines/2026-10-09/2026-10-09_1400_25.json [--pending mail/pending.json]

Prints PASSED, or FAILED with one plain line per problem. Exit code 0 or 1.
The GitHub import job runs the same checks before anything reaches HubSpot.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

FORMAT = "outreachMailWriting v1"
FILE_KEYS = ["format", "run_date", "run_type", "generated_from", "lines"]
LINE_KEYS = ["contact_id", "company_name", "personal_line"]
# Older files also carried a subject line; it is still checked if present but no longer used
# (the subject is fixed in the template, agreed 13 Oct 2026). Files from 14 Oct 2026 also say
# which style each line was written in.
OPTIONAL_KEYS = ["subject_line", "style"]

SUBJECT_WORDS = (3, 7)
PERSONAL_MAX_WORDS = 60
PERSONAL_MAX_SENTENCES = 2

# The four styles of personal line (agreed 14 Oct 2026). Each contact is given one at random
# (prepare_lines.py). The parts in [brackets] are filled from that company's research; the rest
# is fixed. A line must start with its style's opening and contain its style's request.
STYLES = {
    "A": {"name": "Respect for their reach",
          "shape": "We have great respect for the way your team [what they do and for whom]. With such "
                   "established reach [across their channels], we would be honoured if you would consider "
                   "whether a sugar free range could have a place in your portfolio.",
          "opening": "We have great respect for the way your team",
          "request": ["we would be honoured if you would consider whether a sugar free range could have a "
                      "place in your portfolio."]},
    "B": {"name": "Their track record",
          "shape": "Your team's work in [a specific achievement from the research] speaks for itself. We would "
                   "value the opportunity to present our sugar free range and to hear whether you feel it could "
                   "sit alongside [the brands you already represent / the products you already offer].",
          "opening": "Your team's work in",
          "request": ["We would value the opportunity to present our sugar free range and to hear whether you "
                      "feel it could sit alongside the brands you already represent.",
                      "We would value the opportunity to present our sugar free range and to hear whether you "
                      "feel it could sit alongside the products you already offer."]},
    "C": {"name": "Their range",
          "shape": "Your range, [from X to Y], reflects a careful choice of [brands or products] for [their "
                   "market]. We would welcome the chance to present our sugar free range for your "
                   "consideration, should you see a place for it.",
          "opening": "Your range,",
          "request": ["We would welcome the chance to present our sugar free range for your consideration, "
                      "should you see a place for it."]},
    "D": {"name": "Partnership",
          "shape": "We hold your team in high regard for [a specific achievement or position from the "
                   "research]. We would be grateful for the opportunity to discuss whether our sugar free "
                   "range could be a worthwhile addition to your business.",
          "opening": "We hold your team in high regard for",
          "request": ["We would be grateful for the opportunity to discuss whether our sugar free range could "
                      "be a worthwhile addition to your business."]},
}

# Words and phrases the lines must never use: health claims, over-the-top praise, casual words,
# pushy sales talk and guesses about what the company has or has not thought of (14 Oct 2026).
BANNED = [
    "diabetic", "diabetes", "healthy", "guarantee", "guaranteed", "risk free", "risk-free",
    "act now", "limited time", "special offer", "click here", "i was impressed", "i am impressed",
    "i'm impressed", "amazing", "incredible", "incredibly", "game changer", "game-changer", "revolutionary",
    "outstanding", "world-class", "world class", "fantastic", "awesome", "wonderful",
    "fun", "enjoy", "enjoyed", "enjoying", "lovely", "love", "loved", "chat", "exciting", "excited",
    "started asking", "doesn't have", "does not have", "don't have", "do not have", "no sugar free",
    "missing", "lacks", "lacking", "gap",
]
# The personal line pitches Diablo, so it always speaks as "we", never "I" (14 Oct 2026).
_FIRST_PERSON = re.compile(r"(?<![A-Za-z'’])(i|i'm|i’m|i'd|i’d|i've|i’ve|i'll|i’ll|me|my|myself)(?![A-Za-z'’])",
                           re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+\d{1,3}[\s.-]?\(?\d[\d\s().-]{6,}\d")
_URL = re.compile(r"https?://|www\.", re.I)
_DASHES = ("—", "–")


def _words(text):
    return re.findall(r"[A-Za-z0-9'&%£$€-]+", text)


def _sentences(text):
    # A full stop after a single capital letter (the "R.C." in "R.C. Andreae") does not end a sentence.
    parts = [p for p in re.split(r"(?<=[.?])(?<!\b[A-Z]\.)\s+", text.strip()) if p.strip()]
    return len(parts)


def _plain(text):
    """For comparing with a style: straight apostrophes, single spaces, any case."""
    return " ".join(str(text).replace("’", "'").split()).lower()


def style_problems(style, personal):
    """What is wrong with a line for its style, as plain sentences (empty when it fits)."""
    rule = STYLES.get(str(style))
    if rule is None:
        return [f'style must be one of {", ".join(STYLES)}, not "{style}"']
    out = []
    line = _plain(personal)
    if not line.startswith(_plain(rule["opening"])):
        out.append(f'style {style} lines must start "{rule["opening"]}"')
    if not any(_plain(r) in line for r in rule["request"]):
        out.append(f'style {style} lines must include "{rule["request"][0]}"' if len(rule["request"]) == 1
                   else f'style {style} lines must end with one of: ' + " / ".join(f'"{r}"' for r in rule["request"]))
    return out


def _emoji(text):
    return any(unicodedata.category(ch) == "So" or ord(ch) > 0xFFFF for ch in text)


def check_line(errors, line, pending_ids=None):
    where = "A line"
    if not isinstance(line, dict):
        errors.append(f"{where}: must be an object")
        return
    missing = [k for k in LINE_KEYS if k not in line]
    extra = [k for k in line if k not in LINE_KEYS + OPTIONAL_KEYS]
    if missing or extra:
        errors.append(f"{where}: fields must be exactly {', '.join(LINE_KEYS)}")
        return
    cid = str(line["contact_id"])
    where = f"Contact {cid}"
    if pending_ids is not None and cid not in pending_ids:
        errors.append(f"{where}: is not in the list of contacts that need lines")
    company = (line["company_name"] or "").strip()
    subject, personal = line.get("subject_line") or "", line["personal_line"]
    if not isinstance(subject, str) or not isinstance(personal, str):
        errors.append(f"{where}: personal_line must be text")
        return
    n = len(_words(subject))
    if subject and not SUBJECT_WORDS[0] <= n <= SUBJECT_WORDS[1]:
        errors.append(f"{where}: subject line must be {SUBJECT_WORDS[0]} to {SUBJECT_WORDS[1]} words (found {n})")
    if "?" in subject or "!" in subject:
        errors.append(f"{where}: no question marks or exclamation marks in the subject line")
    if re.match(r"^\s*(re|fwd?|fw)\s*:", subject, re.I):
        errors.append(f"{where}: the subject line must not start with Re: or Fwd:")
    letters = [ch for ch in subject if ch.isalpha()]
    if len(letters) > 4 and all(ch.isupper() for ch in letters):
        errors.append(f"{where}: the subject line must not be in capitals")
    n = len(_words(personal))
    if n == 0:
        errors.append(f"{where}: personal line is empty")
    elif n > PERSONAL_MAX_WORDS:
        errors.append(f"{where}: personal line is {n} words; the limit is {PERSONAL_MAX_WORDS}")
    if _sentences(personal) > PERSONAL_MAX_SENTENCES:
        errors.append(f"{where}: personal line must be one or two sentences")
    if "!" in personal:
        errors.append(f"{where}: no exclamation marks")
    if _FIRST_PERSON.search(personal):
        errors.append(f'{where}: the personal line must say "we", never "I", "me" or "my"')
    if "style" in line:
        for problem in style_problems(line["style"], personal):
            errors.append(f"{where}: {problem}")
    if company and len(re.findall(re.escape(company), personal, re.I)) > 1:
        errors.append(f"{where}: the company name appears more than once in the personal line")
    for text, label in ((subject, "subject line"), (personal, "personal line")):
        low = text.lower()
        for word in BANNED:
            if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", low):
                errors.append(f'{where}: the {label} uses "{word}", which is not allowed')
        if any(d in text for d in _DASHES):
            errors.append(f"{where}: the {label} contains an em or en dash; use a comma, full stop or hyphen")
        if _EMAIL.search(text) or _PHONE.search(text) or _URL.search(text):
            errors.append(f"{where}: the {label} must not contain emails, phone numbers or links")
        if "{{" in text or "}}" in text:
            errors.append(f"{where}: the {label} contains a {{{{placeholder}}}}")
        if _emoji(text):
            errors.append(f"{where}: no emojis in the {label}")


def check_file(data, pending_ids=None):
    errors = []
    if not isinstance(data, dict):
        return ["The file: must be an object"]
    missing = [k for k in FILE_KEYS if k not in data]
    extra = [k for k in data if k not in FILE_KEYS]
    if missing:
        errors.append(f"The file: missing field(s): {', '.join(missing)}")
    if extra:
        errors.append(f"The file: field(s) that are not allowed: {', '.join(extra)}")
    if missing:
        return errors
    if data["format"] != FORMAT:
        errors.append(f'The file: format must be "{FORMAT}"')
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data["run_date"])):
        errors.append("The file: run_date must be a date like 2026-10-09")
    if data["run_type"] not in ("scheduled", "manual"):
        errors.append("The file: run_type must be scheduled or manual")
    lines = data["lines"]
    if not isinstance(lines, list) or not lines:
        errors.append("The file: lines must list at least one contact")
        return errors
    seen = set()
    for line in lines:
        check_line(errors, line, pending_ids)
        cid = str(line.get("contact_id")) if isinstance(line, dict) else None
        if cid in seen:
            errors.append(f"Contact {cid}: appears twice")
        seen.add(cid)
    return errors


def main(argv=None):
    p = argparse.ArgumentParser(description="Strict check for email lines")
    p.add_argument("file")
    p.add_argument("--pending", default="")
    args = p.parse_args(argv)
    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"FAILED\n- The file could not be read as JSON: {err}")
        return 1
    pending_ids = None
    if args.pending:
        pending = json.loads(Path(args.pending).read_text(encoding="utf-8"))
        pending_ids = {str(c["contact_id"]) for c in pending.get("contacts", [])}
    errors = check_file(data, pending_ids)
    if errors:
        print("FAILED")
        for e in errors[:60]:
            print(f"- {e}")
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
