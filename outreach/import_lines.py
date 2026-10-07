"""Import new email lines files into HubSpot.

Runs by itself when the outreach-mail-writing skill saves a file to mail/lines/. Each new file
is checked again with the skill's strict check: a file that fails is rejected whole (nothing
reaches HubSpot). For a file that passes, each contact whose status is still "Contact found"
gets its subject line and personal line and moves to "Copy ready" (gate 2). Contacts that have
moved on in the meantime (for example someone already wrote lines by hand) are left alone.

Every file handled is recorded in mail/imported.txt so it is never imported twice, and the
list of contacts still needing lines (mail/pending.json) is saved again afterwards.

Usage:
    python -m outreach.import_lines --target test        # every file not yet imported
"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

from . import export_for_lines
from .common import ROOT, PipelineError, check_target, now_iso
from .hubspot_client import HubSpot, HubSpotError

SKILL = ROOT / "skills" / "outreachMailWriting"
LINES_DIR = ROOT / "mail" / "lines"
IMPORTED = ROOT / "mail" / "imported.txt"


def _checker():
    spec = importlib.util.spec_from_file_location("check_lines", SKILL / "scripts" / "check_lines.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_lines = _checker()


def relative(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def imported_files(path=None):
    path = path or IMPORTED
    if not path.exists():
        return set()
    return {line.split("\t")[0] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def record(name, result, path=None):
    path = path or IMPORTED
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{name}\t{now_iso()}\t{result}\n")


def pending_files(lines_dir=None, imported_path=None):
    done = imported_files(imported_path)
    files = sorted((lines_dir or LINES_DIR).glob("*/*.json"))
    return [f for f in files if relative(f) not in done]


def import_file(path, hs):
    """Import one file. Returns a short result line."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return f"REJECTED: the file could not be read ({err})"
    errors = check_lines.check_file(data)
    if errors:
        shown = "; ".join(errors[:3]) + (f"; and {len(errors) - 3} more" if len(errors) > 3 else "")
        return f"REJECTED by the strict check, nothing added to HubSpot. {shown}"
    ids = [str(l["contact_id"]) for l in data["lines"]]
    current = {c["id"]: c["properties"] for c in hs.batch_read("contacts", ids, ["diablo_contact_status"])}
    updates, moved_on, missing = [], 0, 0
    for line in data["lines"]:
        cid = str(line["contact_id"])
        if cid not in current:
            missing += 1
        elif (current[cid].get("diablo_contact_status") or "") != "contact_found":
            moved_on += 1
        else:
            updates.append((cid, {
                "diablo_subject_line": line["subject_line"],
                "diablo_personal_line": line["personal_line"],
                "diablo_contact_status": "copy_ready",
            }))
    hs.batch_update("contacts", updates)
    result = f"{len(updates)} contacts now Copy ready"
    if moved_on:
        result += f", {moved_on} skipped (no longer Contact found)"
    if missing:
        result += f", {missing} skipped (not in HubSpot)"
    return result


def run(target, hs, files=None, log=print, imported_path=None, pending_path=None):
    files = [Path(f) if Path(f).is_absolute() else ROOT / f for f in files] if files else \
        pending_files(imported_path=imported_path)
    if not files:
        log("No new email lines files to import.")
        return []
    check_target(hs, target)
    results = []
    for f in files:
        result = import_file(f, hs)
        record(relative(f), result, imported_path)
        line = f"{relative(f)}: {result}"
        log(line)
        results.append(line)
    export_for_lines.run(target, hs, pending_path, log=log)
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Import new email lines into HubSpot")
    p.add_argument("--target", default="test", choices=["test", "live"])
    p.add_argument("--file", action="append", default=[], help="a lines JSON file (default: all new ones)")
    args = p.parse_args(argv)
    try:
        lines = run(args.target, HubSpot(), args.file or None)
        code = 0
    except (PipelineError, HubSpotError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        lines, code = [f"ERROR: {err}"], 1
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Email lines import\n\n" + "\n".join(f"- {l}" for l in lines or ["Nothing to import."])
                     + "\n\nNext: in HubSpot, check each Copy ready contact's subject and personal line, "
                       "then change the status to Approved to send (gate 2).\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
