"""Resolve git conflicts in data/*.json by merging semantically instead of
line-by-line. Called by the workflows' commit step when a rebase conflicts
(two workflows updated state at the same time).

Merge rules:
- drafts.json      union by draft_id; on clash keep the more advanced status
- posted.json      union by draft_id
- seen_papers.json set union
- *queue.json      union by item id, ours-first ordering
- anything else    keep OURS (the just-finished run's version)
"""
import json
import subprocess
import sys

RANK = {"pending_media": 0, "pending_video": 1, "pending_review": 2,
        "in_review": 3, "rejected": 4, "approved": 5, "posted": 6}


def stage(path, n):
    """Read a conflict stage (2=ours, 3=theirs) of a file; None if absent."""
    r = subprocess.run(["git", "show", f":{n}:{path}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def merge(path, ours, theirs):
    if ours is None:
        return theirs
    if theirs is None:
        return ours
    name = path.split("/")[-1]
    if name == "drafts.json":
        by_id = {}
        for d in theirs + ours:
            k = d.get("draft_id")
            prev = by_id.get(k)
            if prev is None or RANK.get(d.get("status"), 0) >= RANK.get(prev.get("status"), 0):
                by_id[k] = d
        return list(by_id.values())
    if name == "posted.json":
        by_id = {p.get("draft_id"): p for p in theirs}
        by_id.update({p.get("draft_id"): p for p in ours})
        return list(by_id.values())
    if name == "seen_papers.json":
        return sorted(set(theirs) | set(ours))
    if name.endswith("queue.json"):
        seen, out = set(), []
        for item in ours + theirs:
            k = item.get("id")
            if k not in seen:
                seen.add(k)
                out.append(item)
        return out
    return ours


def main():
    r = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"],
                       capture_output=True, text=True)
    conflicted = [p for p in r.stdout.split() if p]
    if not conflicted:
        print("No conflicted files.")
        return
    for path in conflicted:
        if path.endswith(".json"):
            merged = merge(path, stage(path, 2), stage(path, 3))
            with open(path, "w") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            print(f"Merged {path}")
        else:
            # non-JSON (e.g. feedback.md): keep ours
            r2 = subprocess.run(["git", "show", f":2:{path}"], capture_output=True, text=True)
            if r2.returncode == 0:
                with open(path, "w") as f:
                    f.write(r2.stdout)
            print(f"Kept ours: {path}")
        subprocess.run(["git", "add", path], check=True)


if __name__ == "__main__":
    main()
