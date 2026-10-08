"""Step 1 of an outreach-mail-writing run: pick the contacts that need lines.

Reads mail/pending.json (saved by GitHub after "3 - Find contacts: Apollo to HubSpot" and after every lines import)
and leaves out contacts that already have lines waiting to be imported. Writes:
  work_mail/batch.json    the contacts for this run, with what the research found about each company
  work_mail/prompt.md     the full writing prompt, with the batch filled in

Usage (from the repository's top folder):
    python3 skills/outreachMailWriting/scripts/prepare_lines.py            # scheduled run
    python3 skills/outreachMailWriting/scripts/prepare_lines.py --manual   # someone asked in a chat

Exit code 0 = a batch was written; 3 = nothing to do.
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
ROOT = SKILL.parent.parent
PENDING = ROOT / "mail" / "pending.json"
LINES_DIR = ROOT / "mail" / "lines"
WORK = ROOT / "work_mail"
NOTHING_TO_DO = 3


def ist_now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:  # no time zone data: fall back to UTC + 5:30
        return dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)


def load_settings():
    """settings.yaml holds simple "key: number" lines; read them without needing PyYAML."""
    out = {}
    for line in (SKILL / "settings.yaml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([a-z_]+):\s*(\d+)\s*(#.*)?$", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def already_written(generated_from, lines_dir=None):
    """Contact IDs that have lines in a file made from this same pending list.

    Once GitHub imports a file it saves a fresh pending list, so those contacts drop out by
    themselves. Until then, this stops a second run writing lines for them again."""
    done = set()
    for f in sorted((lines_dir or LINES_DIR).glob("*/*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("generated_from") == generated_from:
            done.update(str(l.get("contact_id")) for l in data.get("lines", []) if isinstance(l, dict))
    return done


def main(argv=None):
    p = argparse.ArgumentParser(description="Pick the contacts that need email lines")
    p.add_argument("--manual", action="store_true")
    args = p.parse_args(argv)

    if not PENDING.exists():
        print("NOTHING TO DO: mail/pending.json does not exist yet. Run \"3 - Find contacts: Apollo to HubSpot\" or "
              "\"4a - HubSpot contacts to email writer (automatic)\" on GitHub first.")
        return NOTHING_TO_DO
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    generated_from = pending.get("generated_at", "")
    skip = already_written(generated_from)
    todo = [c for c in pending.get("contacts", []) if str(c["contact_id"]) not in skip]
    if not todo:
        waiting = f" ({len(skip)} have lines waiting for GitHub to import them)" if skip else ""
        print(f"NOTHING TO DO: no contacts need email lines{waiting}.")
        return NOTHING_TO_DO

    limit = load_settings().get("max_contacts_per_run", 60)
    batch = todo[:limit]
    now = ist_now()
    WORK.mkdir(exist_ok=True)
    for old in WORK.glob("*"):
        if old.is_file():
            old.unlink()
    plan = {
        "run_type": "manual" if args.manual else "scheduled",
        "run_date": now.date().isoformat(),
        "run_time": now.strftime("%H%M"),
        "generated_from": generated_from,
        "contacts": batch,
    }
    (WORK / "batch.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    prompt = (SKILL / "prompts" / "lines_prompt.md").read_text(encoding="utf-8")
    prompt = prompt.replace("{{count}}", str(len(batch)))
    prompt = prompt.replace("{{contacts_json}}", json.dumps(batch, indent=2, ensure_ascii=False))
    (WORK / "prompt.md").write_text(prompt, encoding="utf-8")

    left = len(todo) - len(batch)
    print(f"{len(batch)} contacts to write lines for" + (f"; {left} more wait for the next run" if left else ""))
    print("Read work_mail/prompt.md and save your lines to work_mail/draft.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
