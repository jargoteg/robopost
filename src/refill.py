"""Refill driver: run fetch -> generate -> visuals repeatedly until the
review queue actually has drafts (auto-reject can veto a whole batch for
having no figures, so one pass isn't a guarantee). Bounded attempts."""
import subprocess
import sys
from utils import load_json, load_config

OPEN = ("pending_media", "pending_video", "pending_review", "in_review")


def open_count():
    return sum(1 for d in load_json("drafts.json", [])
               if d.get("status") in OPEN)


def main(max_rounds=3):
    cfg = load_config()
    target = max(1, cfg["pipeline"].get("review_buffer", 6) - 2)
    for rnd in range(1, max_rounds + 1):
        have = open_count()
        if have >= target:
            print(f"Refill: {have} open drafts (>= {target}); done.")
            return
        print(f"Refill round {rnd}: {have}/{target} open drafts, fetching more...")
        before = len(load_json("drafts.json", []))
        for script in ("fetch_papers.py", "generate.py", "visuals.py", "video.py"):
            r = subprocess.run([sys.executable, f"src/{script}"])
            if r.returncode != 0:
                print(f"Refill: {script} failed (rc={r.returncode}); continuing.")
        after = len(load_json("drafts.json", []))
        if after == before:
            print("Refill: no new candidates available right now; stopping.")
            return
    print(f"Refill: stopped after {max_rounds} rounds with {open_count()} open.")


if __name__ == "__main__":
    main()
