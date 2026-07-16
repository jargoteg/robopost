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
        queued = len(load_json("draft_queue.json", []))
        if have >= target and not queued:
            print(f"Refill: {have} open drafts (>= {target}); done.")
            return
        if queued:
            print(f"Refill: {queued} queued item(s) (manual adds/redos) — "
                  f"generating regardless of buffer.")
        print(f"Refill round {rnd}: {have}/{target} open drafts, fetching more...")
        before = len(load_json("drafts.json", []))
        errors = {}
        for script in ("fetch_papers.py", "generate.py", "visuals.py", "video.py"):
            r = subprocess.run([sys.executable, f"src/{script}"],
                               capture_output=True, text=True)
            sys.stdout.write(r.stdout or "")
            sys.stderr.write(r.stderr or "")
            if r.returncode != 0:
                errors[script] = (r.stderr or "")[-800:]
                print(f"Refill: {script} FAILED (rc={r.returncode})")
        if errors:
            from utils import save_json
            rep = load_json("fetch_report.json", {})
            rep["errors"] = errors
            save_json("fetch_report.json", rep)
        after = len(load_json("drafts.json", []))
        if after == before:
            print("Refill: no new candidates available right now; stopping.")
            return
    print(f"Refill: stopped after {max_rounds} rounds with {open_count()} open.")


def litreview_pass():
    try:
        from litreview import maybe_build
        if maybe_build(load_config()):
            import subprocess
            subprocess.run([sys.executable, "src/github_review.py", "create"])
    except Exception:
        import traceback
        print("litreview pass FAILED:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
    litreview_pass()
