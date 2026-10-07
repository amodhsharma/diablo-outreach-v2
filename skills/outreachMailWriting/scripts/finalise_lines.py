"""Step 3 of an outreach-mail-writing run: check the draft and save the lines file.

Reads work_mail/batch.json and work_mail/draft.json (the lines Claude wrote), adds the company
names and the run details, swaps any em or en dash for a comma, runs the strict check and, if it
passes, saves mail/lines/<date>/<date>_<time>_<number of contacts>.json.

Usage (from the repository's top folder):
    python3 skills/outreachMailWriting/scripts/finalise_lines.py
    python3 skills/outreachMailWriting/scripts/finalise_lines.py --drop-failing

--drop-failing saves only the lines that pass and leaves the rest out; those contacts stay on the
list and get new lines on the next run. Use it only after two fixes have not helped.

Prints PASSED and the file name, or FAILED with one line per problem (nothing is saved).
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))

from check_lines import FORMAT, check_file, check_line  # noqa: E402

WORK = ROOT / "work_mail"
LINES_DIR = ROOT / "mail" / "lines"


def tidy(text):
    text = " ".join(str(text or "").split())
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    return text.replace(",,", ",")


def build(batch, draft):
    """The lines file, from the batch and Claude's draft."""
    names = {str(c["contact_id"]): c["company"]["name"] for c in batch["contacts"]}
    raw = draft.get("lines", draft) if isinstance(draft, dict) else draft
    lines = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            lines.append(item)
            continue
        cid = str(item.get("contact_id", ""))
        lines.append({
            "contact_id": cid,
            "company_name": names.get(cid, ""),
            "subject_line": tidy(item.get("subject_line")),
            "personal_line": tidy(item.get("personal_line")),
        })
    return {
        "format": FORMAT,
        "run_date": batch["run_date"],
        "run_type": batch["run_type"],
        "generated_from": batch["generated_from"],
        "lines": lines,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the draft lines and save the lines file")
    p.add_argument("--drop-failing", action="store_true")
    args = p.parse_args(argv)
    try:
        batch = json.loads((WORK / "batch.json").read_text(encoding="utf-8"))
        draft = json.loads((WORK / "draft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"FAILED\n- work_mail/batch.json or work_mail/draft.json could not be read: {err}")
        return 1
    data = build(batch, draft)
    batch_ids = {str(c["contact_id"]) for c in batch["contacts"]}
    dropped = []
    if args.drop_failing:
        kept = []
        for line in data["lines"]:
            errs = []
            check_line(errs, line, batch_ids)
            (dropped if errs else kept).append(line)
        data["lines"] = kept
    errors = check_file(data, batch_ids)
    if errors:
        print("FAILED")
        for e in errors[:60]:
            print(f"- {e}")
        return 1

    missing = batch_ids - {l["contact_id"] for l in data["lines"]}
    folder = LINES_DIR / batch["run_date"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{batch['run_date']}_{batch['run_time']}_{len(data['lines'])}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("PASSED")
    print(f"Saved {path.relative_to(ROOT)} with lines for {len(data['lines'])} contacts")
    if missing:
        print(f"{len(missing)} contacts have no lines this time and stay on the list for the next run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
