"""Pull real imagery for drafts:
- arXiv papers → download the PDF, extract the largest figures (attributed
  to the authors on every card/caption)
- articles → the publisher's own social-share image (og:image)
Figures are used in review/commentary context with attribution; many arXiv
papers are CC-BY. The /redo command lets the owner drop any image."""
import re
import requests
from pathlib import Path
from utils import MEDIA


def arxiv_figures(paper: dict, out_dir: Path, max_figs: int = 6) -> list[str]:
    """Extract figures from an arXiv PDF. Anchors on the figure CAPTION text
    ('Figure N', 'Fig. N') so it captures VECTOR diagrams too (architecture /
    pipeline figures drawn with PDF vector commands, which embedded-image
    extraction misses), not only raster photos/plots. Captures the block above
    each caption plus the caption itself. Aspect ratio is always preserved."""
    import fitz
    pid = paper["id"]
    url = f"https://arxiv.org/pdf/{pid}"
    r = requests.get(url, timeout=60, headers={"User-Agent": "RoboPost/1.0"})
    r.raise_for_status()
    doc = fitz.open(stream=r.content, filetype="pdf")
    candidates = []
    cap_re = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.I)

    for page in doc:
        pr = page.rect
        # 1) locate figure captions on the page
        caption_blocks = []
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            if cap_re.match(text or ""):
                caption_blocks.append(fitz.Rect(x0, y0, x1, y1))
        # 2) image rects (for raster figures / to refine bounds)
        img_rects = []
        for img in page.get_images(full=True):
            try:
                for ir in page.get_image_rects(img[0]):
                    if ir.width > 40 and ir.height > 40:
                        img_rects.append(fitz.Rect(ir))
            except Exception:
                continue

        used_imgs = set()
        # For each caption, the figure is the whitespace/content ABOVE it,
        # bounded below by the caption and above by the previous caption or
        # the top of the column. Include any image rects that fall in there.
        for cap in sorted(caption_blocks, key=lambda r: r.y0):
            top = pr.y0 + 40
            for other in caption_blocks:
                if other.y1 < cap.y0 and other.y1 > top:
                    top = other.y1 + 6      # don't cross into a figure above
            # same column horizontally: start from caption's x-span, widen to
            # any image rects sitting above the caption in that band
            left, right = cap.x0, cap.x1
            block_top = cap.y0
            for i, ir in enumerate(img_rects):
                if ir.y1 <= cap.y0 + 4 and ir.y0 >= top - 4 and \
                   ir.x1 > cap.x0 - 40 and ir.x0 < cap.x1 + 40:
                    left = min(left, ir.x0)
                    right = max(right, ir.x1)
                    block_top = min(block_top, ir.y0)
                    used_imgs.add(i)
            block_top = min(block_top, cap.y0)
            # figure region = content above caption + caption text itself
            region = fitz.Rect(min(left, cap.x0) - 6, max(top, block_top) - 6,
                               max(right, cap.x1) + 6, cap.y1 + 4)
            w, h = region.width, region.height
            if w < 120 or h < 90 or w / h > 8 or h / w > 8:
                continue
            candidates.append((w * h, page.number, region))

        # 3) fallback: large image rects with NO caption matched (rare) —
        # keep them so we never lose a real figure
        for i, ir in enumerate(img_rects):
            if i in used_imgs:
                continue
            if ir.width > 200 and ir.height > 150:
                cap = fitz.Rect(ir.x0 - 6, ir.y0 - 6, ir.x1 + 6,
                               min(pr.y1, ir.y1 + 40))
                candidates.append((cap.width * cap.height, page.number, cap))

    # earliest pages first (teaser/method figures), largest first within a page
    candidates.sort(key=lambda c: (c[1], -c[0]))
    paths, used = [], []
    for area, pnum, rect in candidates:
        dup = False
        for pn, r in used:
            if pn == pnum and r.intersects(rect):
                ov = (r & rect).get_area()
                if ov > 0.6 * min(area, r.get_area()):
                    dup = True
                    break
        if dup:
            continue
        pix = doc[pnum].get_pixmap(clip=rect, dpi=200)
        p = out_dir / f"fig_{len(paths):02d}.png"
        p.write_bytes(pix.tobytes("png"))
        paths.append(str(p.relative_to(MEDIA.parent)))
        used.append((pnum, rect))
        if len(paths) >= max_figs:
            break
    doc.close()
    return paths


def og_image(url: str, out_dir: Path) -> list[str]:
    """Publisher's social-share image for articles/news."""
    try:
        r = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (compatible; RoboPost/1.0)"})
        m = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)', r.text) \
            or re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:image', r.text)
        if not m:
            return []
        img = requests.get(m.group(1), timeout=30).content
        p = out_dir / "fig_00.png"
        from PIL import Image
        import io
        Image.open(io.BytesIO(img)).convert("RGB").save(p)
        return [str(p.relative_to(MEDIA.parent))]
    except Exception as e:
        print(f"og:image failed for {url}: {e}")
        return []


def youtube_thumbnail(video_url: str, out_dir: Path) -> list[str]:
    """Thumbnail of a linked YouTube video (used with 'linked video' credit)."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{6,})", video_url or "")
    if not m:
        return []
    for variant in ("maxresdefault", "hqdefault"):
        try:
            r = requests.get(
                f"https://img.youtube.com/vi/{m.group(1)}/{variant}.jpg",
                timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            if r.ok and len(r.content) > 5000:
                p = out_dir / "fig_00.png"
                from PIL import Image
                import io
                Image.open(io.BytesIO(r.content)).convert("RGB").save(p)
                return [str(p.relative_to(MEDIA.parent))]
        except Exception:
            continue
    return []


def get_figures(draft) -> list[str]:
    p = draft["paper"]
    out_dir = MEDIA / draft["draft_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    figs = []
    try:
        if p.get("source") in ("arxiv", "hf_daily", "manual") and re.match(r"\d{4}\.\d{4,5}", str(p["id"])):
            figs = arxiv_figures(p, out_dir)
        if not figs and p.get("video_url"):
            figs = youtube_thumbnail(p["video_url"], out_dir)
        if not figs and p.get("item_type") == "video":
            figs = youtube_thumbnail(p["url"], out_dir)
        if not figs and p.get("url", "").startswith("http"):
            figs = og_image(p["url"], out_dir)
        # Paywalled sources (IEEE, closed journals) often yield no figures.
        # Hunt for an open version of the same paper and pull figures there.
        if not figs:
            paywalled = any(s in (p.get("url", "") + " " + p.get("source", "")).lower()
                            for s in ("ieee", "sciencedirect", "springer",
                                      "wiley", "acm.org", "mdpi"))
            if paywalled or p.get("item_type") == "paper":
                info = find_open_version(p.get("title", ""), p.get("authors"))
                if info and info.get("arxiv_id"):
                    p["open_version"] = f"https://arxiv.org/abs/{info['arxiv_id']}"
                    figs = arxiv_figures({"id": info["arxiv_id"]}, out_dir)
                elif info and info.get("pdf_url"):
                    figs = figures_from_pdf_url(info["pdf_url"], out_dir)
                    if figs:
                        p["open_version"] = info["pdf_url"]

        # GitHub repo: often the most reliable figures + a real demo video.
        # Try it whenever we have an arXiv id, and prefer its video regardless.
        aid = None
        if re.match(r"\d{4}\.\d{4,5}", str(p.get("id", ""))):
            aid = p["id"]
        elif p.get("open_version"):
            mo = re.search(r"arxiv\.org/abs/(\S+)", p["open_version"])
            aid = mo.group(1) if mo else None
        if aid and not p.get("repo_url"):
            repo = find_github_repo(p.get("title", ""), aid)
            if repo:
                mined = mine_github_repo(repo, out_dir)
                p["repo_url"] = mined["repo_url"]
                if mined.get("video_url") and not p.get("video_url"):
                    p["video_url"] = mined["video_url"]
                if mined["figures"]:  # repo figures are clean; prefer them
                    figs = mined["figures"]
                    p["fig_source"] = mined["repo_url"]
        # Last resort: a matching YouTube video's thumbnail
        if not figs:
            from fetch_papers import enrich_youtube
            enrich_youtube([p])
            if p.get("video_url"):
                figs = youtube_thumbnail(p["video_url"], out_dir)
    except Exception as e:
        print(f"Figure extraction failed for {draft['draft_id']} (non-fatal): {e}")
    return figs


def _find_doi(title):
    """Resolve a paper title to a DOI via Crossref (for Unpaywall)."""
    import difflib
    try:
        r = requests.get("https://api.crossref.org/works",
                         params={"query.bibliographic": title[:200], "rows": 3},
                         timeout=30, headers={"User-Agent": "RoboPost/1.0 (mailto:robopost@users.noreply.github.com)"})
        def norm(s):
            return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()
        for it in r.json().get("message", {}).get("items", []):
            ct = " ".join(it.get("title") or [])
            if ct and difflib.SequenceMatcher(None, norm(title), norm(ct)).ratio() >= 0.85:
                return it.get("DOI")
    except Exception as e:
        print(f"Crossref DOI lookup failed: {e}")
    return None


def find_open_version(title, authors=None):
    """Find an open-access version of a paywalled paper. Returns a dict with
    an 'arxiv_id' and/or a direct 'pdf_url' if found, else None.
    Strategy: query arXiv by title; if a close title match exists, use it.
    Then try Crossref/Unpaywall-style OA via the Semantic Scholar public API."""
    import difflib

    def norm(s):
        return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()

    tnorm = norm(title)

    # 1) arXiv title search (author preprints are extremely common)
    try:
        q = requests.utils.quote(f'ti:"{title[:120]}"')
        r = requests.get(
            f"http://export.arxiv.org/api/query?search_query={q}&max_results=5",
            timeout=30, headers={"User-Agent": "RoboPost/1.0"})
        if not r.text.strip().startswith("<"):
            return None
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in ET.fromstring(r.text).findall("a:entry", ns):
            at = e.find("a:title", ns)
            if at is None:
                continue
            cand = re.sub(r"\s+", " ", at.text).strip()
            ratio = difflib.SequenceMatcher(None, tnorm, norm(cand)).ratio()
            if ratio >= 0.85:
                aid = e.find("a:id", ns).text.split("/abs/")[-1].split("v")[0]
                print(f"Open version: arXiv {aid} (title match {ratio:.2f})")
                return {"arxiv_id": aid}
    except Exception as e:
        print(f"arXiv title search failed: {e}")

    # 2) Unpaywall (by DOI): best OA PDF anywhere, incl. institutional repos
    doi = _find_doi(title)
    if doi:
        try:
            r = requests.get(f"https://api.unpaywall.org/v2/{doi}",
                             params={"email": "robopost@users.noreply.github.com"},
                             timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            loc = (r.json() or {}).get("best_oa_location") or {}
            pdf = loc.get("url_for_pdf") or loc.get("url")
            if pdf:
                print(f"Open version: Unpaywall OA {pdf[:60]}")
                return {"pdf_url": pdf}
        except Exception as e:
            print(f"Unpaywall lookup failed: {e}")

    # 3) OpenAlex (by title): also exposes OA PDF locations
    try:
        r = requests.get("https://api.openalex.org/works",
                         params={"search": title[:200], "per_page": 3},
                         timeout=30, headers={"User-Agent": "RoboPost/1.0"})
        for w in r.json().get("results", []):
            if difflib.SequenceMatcher(None, tnorm, norm(w.get("title"))).ratio() >= 0.85:
                oa = (w.get("best_oa_location") or w.get("primary_location") or {})
                pdf = oa.get("pdf_url")
                if pdf:
                    print(f"Open version: OpenAlex OA {pdf[:60]}")
                    return {"pdf_url": pdf}
    except Exception as e:
        print(f"OpenAlex lookup failed: {e}")

    # 4) Semantic Scholar: openAccessPdf if available
    try:
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title[:200], "limit": 3,
                    "fields": "title,openAccessPdf,externalIds"},
            timeout=30, headers={"User-Agent": "RoboPost/1.0"})
        for pap in r.json().get("data", []):
            if difflib.SequenceMatcher(None, tnorm, norm(pap.get("title"))).ratio() >= 0.85:
                ext = pap.get("externalIds") or {}
                if ext.get("ArXiv"):
                    print(f"Open version: arXiv {ext['ArXiv']} (via S2)")
                    return {"arxiv_id": ext["ArXiv"]}
                oa = pap.get("openAccessPdf") or {}
                if oa.get("url"):
                    print(f"Open version: OA PDF {oa['url'][:60]}")
                    return {"pdf_url": oa["url"]}
    except Exception as e:
        print(f"Semantic Scholar lookup failed: {e}")
    return None


def figures_from_pdf_url(pdf_url, out_dir):
    """Extract figures from any direct PDF URL (reuses arxiv_figures logic)."""
    import fitz
    import io
    from PIL import Image
    try:
        r = requests.get(pdf_url, timeout=60, headers={"User-Agent": "RoboPost/1.0"})
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "pdf" not in ct.lower() and not r.content[:4] == b"%PDF":
            print(f"OA link was not a PDF ({ct}); skipping")
            return []
        doc = fitz.open(stream=r.content, filetype="pdf")
        found, seen = [], set()
        for page in doc[:10]:
            for info in page.get_images(full=True):
                x = info[0]
                if x in seen:
                    continue
                seen.add(x)
                try:
                    pix = fitz.Pixmap(doc, x)
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.width < 420 or pix.height < 260:
                        continue
                    found.append((pix.width * pix.height,
                                  Image.open(io.BytesIO(pix.tobytes("png")))))
                except Exception:
                    continue
        found.sort(key=lambda t: -t[0])
        paths = []
        for i, (_, img) in enumerate(found[:4]):
            pth = out_dir / f"fig_{i:02d}.png"
            img.convert("RGB").save(pth)
            paths.append(str(pth.relative_to(MEDIA.parent)))
        doc.close()
        return paths
    except Exception as e:
        print(f"PDF figure extraction failed: {e}")
        return []


def find_github_repo(title, arxiv_id=None):
    """Find the paper's official GitHub repo via Papers with Code, the arXiv
    API 'comment' field, and the abstract page. Validates the repo exists and
    isn't a reference to some other project."""
    def clean_repo(raw):
        raw = raw.rstrip("/").rstrip(".")
        raw = re.sub(r"\.git$", "", raw)
        raw = raw.split("#")[0].split("?")[0].split(")")[0].split("]")[0]
        parts = raw.split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            owner, name = parts[0], parts[1]
            # skip non-repo github paths
            if owner.lower() in ("about", "features", "topics", "sponsors", "orgs"):
                return None
            return f"{owner}/{name}"
        return None

    def repo_exists(repo):
        try:
            import os
            h = {"User-Agent": "RoboPost/1.0"}
            if os.environ.get("GITHUB_TOKEN"):
                h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
            return requests.get(f"https://api.github.com/repos/{repo}",
                                headers=h, timeout=20).status_code == 200
        except Exception:
            return False

    candidates = []

    # 1) Papers with Code
    try:
        if arxiv_id:
            r = requests.get(
                f"https://paperswithcode.com/api/v1/papers/?arxiv_id={arxiv_id}",
                timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            results = r.json().get("results") or []
            if results:
                pid = results[0]["id"]
                r2 = requests.get(
                    f"https://paperswithcode.com/api/v1/papers/{pid}/repositories/",
                    timeout=30, headers={"User-Agent": "RoboPost/1.0"})
                repos = r2.json().get("results") or []
                for x in sorted(repos, key=lambda z: not z.get("is_official")):
                    m = re.search(r"github\.com/([^/\s]+/[^/\s]+)", x.get("url", ""))
                    if m:
                        candidates.append(clean_repo(m.group(1)))
    except Exception as e:
        print(f"PapersWithCode lookup failed: {e}")

    # 2) arXiv API 'comment' field (authors often put the repo here) + abstract
    try:
        if arxiv_id:
            r = requests.get(
                f"http://export.arxiv.org/api/query?id_list={arxiv_id}",
                timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            for m in re.finditer(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", r.text):
                candidates.append(clean_repo(m.group(1)))
            r2 = requests.get(f"https://arxiv.org/abs/{arxiv_id}", timeout=30,
                              headers={"User-Agent": "RoboPost/1.0"})
            for m in re.finditer(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)", r2.text):
                candidates.append(clean_repo(m.group(1)))
    except Exception as e:
        print(f"arXiv repo scan failed: {e}")

    # first candidate that actually exists on GitHub
    for repo in [c for c in candidates if c]:
        if repo_exists(repo):
            print(f"Repo found: {repo}")
            return repo
    if candidates:
        print(f"Repo candidates found but none validated: {[c for c in candidates if c][:3]}")
    return None


def mine_github_repo(repo, out_dir, max_figs=6):
    """Pull figures and a demo video/GIF link from a repo's README + assets.
    Returns {'figures': [paths], 'video_url': str|None, 'repo_url': str}."""
    base = "https://api.github.com"
    headers = {"User-Agent": "RoboPost/1.0", "Accept": "application/vnd.github+json"}
    tok = __import__("os").environ.get("GITHUB_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    out = {"figures": [], "video_url": None, "repo_url": f"https://github.com/{repo}"}
    try:
        meta = requests.get(f"{base}/repos/{repo}", headers=headers, timeout=30).json()
        branch = meta.get("default_branch", "main")
        rm = requests.get(f"{base}/repos/{repo}/readme", headers=headers, timeout=30).json()
        import base64
        readme = base64.b64decode(rm.get("content", "")).decode("utf-8", "ignore")
    except Exception as e:
        print(f"Repo fetch failed for {repo}: {e}")
        return out

    raw = f"https://raw.githubusercontent.com/{repo}/{branch}"
    # video: YouTube link in README wins (real demo, we link not re-host)
    ym = re.search(r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)", readme)
    if ym:
        out["video_url"] = ym.group(1)

    # images in README (markdown ![..](url) and <img src="..">)
    imgs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
    imgs += re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', readme)
    picked = 0
    for src in imgs:
        if picked >= max_figs:
            break
        low = src.lower().split("?")[0]
        if low.endswith((".svg", ".ico")) or "badge" in low or "shields.io" in low:
            continue  # skip badges/logos
        url = src if src.startswith("http") else f"{raw}/{src.lstrip('./')}"
        try:
            rr = requests.get(url, timeout=30, headers={"User-Agent": "RoboPost/1.0"})
            if not rr.ok or len(rr.content) < 8000:
                continue
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(rr.content))
            # animated GIF: grab a representative middle frame (aspect preserved)
            if getattr(im, "is_animated", False):
                im.seek(im.n_frames // 2)
            if im.width < 300 or im.height < 200:
                continue
            p = out_dir / f"fig_{picked:02d}.png"
            im.convert("RGB").save(p)
            out["figures"].append(str(p.relative_to(MEDIA.parent)))
            picked += 1
        except Exception:
            continue
    print(f"Repo {repo}: {len(out['figures'])} figures, video={bool(out['video_url'])}")
    return out
