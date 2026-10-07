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
LINE_KEYS = ["contact_id", "company_name", "subject_line", "personal_line"]

SUBJECT_WORDS = (3, 7)
PERSONAL_MAX_WORDS = 50
PERSONAL_MAX_SENTENCES = 2

# Words and phrases the lines must never use (health claims, empty flattery, pushy sales talk).
BANNED = [
    "diabetic", "diabetes", "healthy", "guarantee", "guaranteed", "risk free", "risk-free",
    "act now", "limited time", "special offer", "click here", "i was impressed", "i am impressed",
    "i'm impressed", "amazing", "incredible", "game changer", "game-changer", "revolutionary",
]
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+\d{1,3}[\s.-]?\(?\d[\d\s().-]{6,}\d")
_URL = re.compile(r"https?://|www\.", re.I)
_DASHES = ("—", "–")


def _words(text):
    return re.findall(r"[A-Za-z0-9'&%£$€-]+", text)


def _sentences(text):
    parts = [p for p in re.split(r"(?<=[.?])\s+", text.strip()) if p.strip()]
    return len(parts)


def _emoji(text):
    return any(unicodedata.category(ch) == "So" or ord(ch) > 0xFFFF for ch in text)


def check_line(errors, line, pending_ids=None):
    where = "A line"
    if not isinstance(line, dict):
        errors.append(f"{where}: must be an object")
        return
    missing = [k for k in LINE_KEYS if k not in line]
    extra = [k for k in line if k not in LINE_KEYS]
    if missing or extra:
        errors.append(f"{where}: fields must be exactly {', '.join(LINE_KEYS)}")
        return
    cid = str(line["contact_id"])
    where = f"Contact {cid}"
    if pending_ids is not None and cid not in pending_ids:
        errors.append(f"{where}: is not in the list of contacts that need lines")
    company = (line["company_name"] or "").strip()
    subject, personal = line["subject_line"], line["personal_line"]
    if not isinstance(subject, str) or not isinstance(personal, str):
        errors.append(f"{where}: subject_line and personal_line must be text")
        return
    n = len(_words(subject))
    if not SUBJECT_WORDS[0] <= n <= SUBJECT_WORDS[1]:
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
