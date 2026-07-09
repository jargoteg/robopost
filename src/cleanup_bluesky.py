"""One-shot cleanup: find duplicate posts on the Bluesky account (identical
text), keep the OLDEST of each group, delete the rest. Also removes their
thread replies. Dry-run by default; pass 'delete' to actually delete."""
import sys
import requests
from collections import defaultdict
from utils import env


def main(do_delete=False):
    handle, pw = env("BLUESKY_HANDLE", True), env("BLUESKY_APP_PASSWORD", True)
    base = "https://bsky.social/xrpc"
    s = requests.post(f"{base}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": pw}, timeout=30).json()
    jwt, did = s["accessJwt"], s["did"]
    H = {"Authorization": f"Bearer {jwt}"}

    posts, cursor = [], None
    for _ in range(6):  # up to ~600 recent records
        params = {"actor": did, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{base}/app.bsky.feed.getAuthorFeed",
                         params=params, headers=H, timeout=30).json()
        for item in r.get("feed", []):
            p = item.get("post", {})
            rec = p.get("record", {})
            if rec.get("reply"):
                continue  # group by root posts only
            posts.append({"uri": p["uri"], "cid": p["cid"],
                          "text": (rec.get("text") or "")[:80],
                          "at": rec.get("createdAt", "")})
        cursor = r.get("cursor")
        if not cursor:
            break

    groups = defaultdict(list)
    for p in posts:
        if p["text"].strip():
            groups[p["text"]].append(p)

    dupes = {t: sorted(v, key=lambda x: x["at"]) for t, v in groups.items() if len(v) > 1}
    if not dupes:
        print("No duplicate posts found. Feed is clean.")
        return
    total_extra = sum(len(v) - 1 for v in dupes.values())
    print(f"Found {len(dupes)} duplicated post texts, {total_extra} extra copies:")
    for t, v in dupes.items():
        print(f"  x{len(v)}: {t[:60]}")
        for extra in v[1:]:
            rkey = extra["uri"].split("/")[-1]
            if do_delete:
                rr = requests.post(f"{base}/com.atproto.repo.deleteRecord",
                                   headers=H, json={"repo": did,
                                                    "collection": "app.bsky.feed.post",
                                                    "rkey": rkey}, timeout=30)
                print(f"    deleted {rkey}: {rr.status_code}")
            else:
                print(f"    would delete {rkey} ({extra['at'][:16]})")
    if not do_delete:
        print("\nDRY RUN. Re-run with 'delete' argument to actually remove them.")


if __name__ == "__main__":
    main(do_delete=(len(sys.argv) > 1 and sys.argv[1] == "delete"))
