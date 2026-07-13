"""Repair: any open draft whose media files are missing on disk gets its
cards re-rendered (figures re-fetched if needed). Heals drafts whose media
was generated in a run that failed to commit it."""
from pathlib import Path
from utils import load_json, save_json, load_config, ROOT

OPEN = ("pending_media", "pending_review", "in_review", "approved")


def main():
    cfg = load_config()
    drafts = load_json("drafts.json", [])
    fixed = 0
    for d in drafts:
        if d.get("status") not in OPEN:
            continue
        slides = d.get("media", {}).get("slides") or []
        missing = [s for s in slides if not (ROOT / s).exists()]
        figs = d.get("media", {}).get("figures") or []
        figs_missing = [f for f in figs if not (ROOT / f).exists()]
        if not slides or missing or figs_missing:
            print(f"Repairing media for {d['draft_id']} "
                  f"({len(missing)}/{len(slides)} slides missing)")
            if figs_missing:
                d["media"].pop("figures", None)  # force a fresh figure hunt
            import visuals
            d.setdefault("media", {})["slides"] = visuals.build_carousel(d, cfg)
            if d["status"] == "pending_media":
                if d["media"].get("figures") or d["paper"].get("video_url"):
                    d["status"] = "pending_review"
                else:
                    d["status"] = "rejected"  # consistent with auto-reject rule
            fixed += 1
    if fixed:
        save_json("drafts.json", drafts)
    print(f"Media repair: {fixed} draft(s) re-rendered.")


if __name__ == "__main__":
    main()
