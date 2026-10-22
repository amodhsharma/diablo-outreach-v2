"""One research run at a time, up to max_jobs_per_run jobs in a row (agreed 22 Oct 2026).

A run (the hourly schedule or someone typing /outreach-research) works through the waiting jobs
one after another. Each job stays its own job: its own files, its own commit and its own import
into HubSpot. This script keeps two runs from working at the same time, with a small file in
GitHub, research/run_lock.json, that says which run is working and on which job.

    python3 skills/outreachResearch/scripts/run_lock.py take [--manual]   # start of the run
    python3 skills/outreachResearch/scripts/run_lock.py job J0025         # before each job
    python3 skills/outreachResearch/scripts/run_lock.py done J0025        # after each job (saved in Step 6)
    python3 skills/outreachResearch/scripts/run_lock.py release           # end of the run

take prints TAKEN, or ANOTHER RUN IS WORKING (exit code 3) when a run updated the lock less than
STALE_HOURS ago. A run that stopped without releasing (for example a session that ended) leaves a
lock that goes stale after STALE_HOURS; the job it was working on is still Waiting in the queue
(only GitHub changes the queue), so the next run picks it up again.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LOCK = ROOT / "research" / "run_lock.json"
ID_FILE = ROOT / ".research_run_id"  # this session's run, never committed (.gitignore)
STALE_HOURS = 2
BUSY = 3


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def read_lock(path=None):
    try:
        return json.loads(Path(path or LOCK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def my_run_id(path=None):
    try:
        return Path(path or ID_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_fresh(lock, now=None):
    """True when the lock was updated less than STALE_HOURS ago."""
    try:
        updated = dt.datetime.fromisoformat(lock["updated"])
    except (TypeError, KeyError, ValueError):
        return False
    return (now or now_utc()) - updated < dt.timedelta(hours=STALE_HOURS)


def held_by_other(lock, run_id, now=None):
    """True when another run is working: a fresh lock that is not this run's."""
    return bool(lock) and is_fresh(lock, now) and lock.get("run_id") != run_id


def done_in_this_run(lock_path=None, id_path=None):
    """The job IDs this run has finished, or an empty list when the lock is not this run's."""
    lock, run_id = read_lock(lock_path), my_run_id(id_path)
    if lock and run_id and lock.get("run_id") == run_id:
        return list(lock.get("done") or [])
    return []


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _write(lock):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def _push(message, remove=False):
    """Commit the lock change and push it. False when someone else pushed a conflicting lock."""
    if remove:
        _git("rm", "-q", "--cached", "--ignore-unmatch", str(LOCK.relative_to(ROOT)))
        if LOCK.exists():
            LOCK.unlink()
    else:
        _git("add", str(LOCK.relative_to(ROOT)))
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True  # nothing to commit
    _git("commit", "-q", "-m", message)
    if _git("pull", "--rebase", "-q").returncode != 0:
        # Someone else changed the lock at the same moment: drop only our lock commit and take
        # theirs; no other file is touched.
        rel = str(LOCK.relative_to(ROOT))
        _git("rebase", "--abort")
        _git("reset", "-q", "--mixed", "@{u}")
        if _git("checkout", "-q", "@{u}", "--", rel).returncode != 0 and LOCK.exists():
            LOCK.unlink()
        return False
    return _git("push", "-q").returncode == 0


def take(manual=False):
    _git("pull", "--rebase", "-q")
    lock = read_lock()
    if held_by_other(lock, my_run_id()):
        print(f"ANOTHER RUN IS WORKING: {lock.get('kind', 'a')} run started {lock.get('started')}, "
              f"on job {lock.get('job') or '(between jobs)'}, last update {lock.get('updated')}. "
              "Nothing to do in this run.")
        return BUSY
    run_id = uuid.uuid4().hex[:12]
    stamp = now_utc().isoformat(timespec="seconds")
    _write({"run_id": run_id, "kind": "manual" if manual else "scheduled", "started": stamp,
            "updated": stamp, "job": "", "done": []})
    ID_FILE.write_text(run_id + "\n", encoding="utf-8")
    if not _push("Research run started"):
        lock = read_lock()
        if held_by_other(lock, run_id):
            print("ANOTHER RUN IS WORKING: another run started at the same moment. Nothing to do in this run.")
            return BUSY
        print("WARNING: the lock could not be saved to GitHub; this run carries on.")
    print(f"TAKEN: run {run_id}")
    return 0


def mark(job_id, finished):
    lock = read_lock()
    if not lock or lock.get("run_id") != my_run_id():
        print("WARNING: this run does not hold the lock; carrying on.")
        return 0
    lock["updated"] = now_utc().isoformat(timespec="seconds")
    if finished:
        lock["job"] = ""
        lock["done"] = [*lock.get("done", []), job_id] if job_id not in lock.get("done", []) else lock["done"]
        _write(lock)  # saved to GitHub with the job's files in Step 6
    else:
        lock["job"] = job_id
        _write(lock)
        if not _push(f"Research run: working on {job_id}"):
            print("WARNING: the lock could not be updated on GitHub; carrying on.")
    print(f"OK: {'finished' if finished else 'working on'} {job_id}")
    return 0


def release():
    lock = read_lock()
    if lock and lock.get("run_id") == my_run_id():
        done = ", ".join(lock.get("done") or []) or "no jobs"
        if not _push("Research run finished", remove=True):
            print("WARNING: the lock could not be removed from GitHub; it goes stale by itself.")
        print(f"RELEASED: this run finished {done}")
    else:
        print("RELEASED: this run held no lock")
    if ID_FILE.exists():
        ID_FILE.unlink()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="One research run at a time")
    p.add_argument("action", choices=["take", "job", "done", "release"])
    p.add_argument("job_id", nargs="?", default="")
    p.add_argument("--manual", action="store_true")
    args = p.parse_args(argv)
    if args.action == "take":
        return take(args.manual)
    if args.action in ("job", "done"):
        if not args.job_id:
            p.error("give the job ID, e.g. J0025")
        return mark(args.job_id.strip().upper(), finished=args.action == "done")
    return release()


if __name__ == "__main__":
    sys.exit(main())
