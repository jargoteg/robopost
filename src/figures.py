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


def arxiv_figures(paper: dict, out_dir: Path, max_figs: int = 4) -> list[str]:
    """Extract figures from an arXiv PDF by rendering whole image REGIONS of
    the page (figure plus its rendered caption stay intact), rather than
    pulling raw embedded image streams which often slice multi-panel figures
    or split captions. Aspect ratio is always preserved."""
    import fitz
    pid = paper["id"]
    url = f"https://arxiv.org/pdf/{pid}"
    r = requests.get(url, timeout=60, headers={"User-Agent": "RoboPost/1.0"})
    r.raise_for_status()
    doc = fitz.open(stream=r.content, filetype="pdf")
    candidates = []
    for page in doc:
        # union image rectangles on the page into figure regions
        rects = []
        for img in page.get_images(full=True):
            try:
                for r_ in page.get_image_rects(img[0]):
                    if r_.width > 60 and r_.height > 60:
                        rects.append(fitz.Rect(r_))
            except Exception:
                continue
        if not rects:
            continue
        # merge overlapping/adjacent rects (multi-panel figures) into blocks
        merged = []
        for rc in sorted(rects, key=lambda r: (round(r.y0), round(r.x0))):
            placed = False
            for i, m in enumerate(merged):
                gap = fitz.Rect(m)
                gap += (-8, -8, 8, 40)  # pad, esp. below for caption
                if gap.intersects(rc):
                    merged[i] = m | rc
                    placed = True
                    break
            if not placed:
                merged.append(fitz.Rect(rc))
        for m in merged:
            # expand downward to capture the rendered caption line(s)
            cap = fitz.Rect(m.x0, m.y0, m.x1, min(page.rect.y1, m.y1 + 46))
            w, h = cap.width, cap.height
            if w < 150 or h < 110 or w / h > 6 or h / w > 6:
                continue
            area = w * h
            candidates.append((area, page.number, cap))
    # earliest pages first (teaser/method figures), largest first
    candidates.sort(key=lambda c: (c[1], -c[0]))
    paths, used = [], []
    for area, pnum, rect in candidates:
        # skip near-duplicates of an already-picked region on same page
        if any(pn == pnum and r.intersects(rect) and (r & rect).get_area() > 0.6 * area
               for pn, r in used):
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
                    figs = arxiv_figures({"id": info["arxiv_id"]}, out_dir)
                    if figs:
                        p["open_version"] = f"https://arxiv.org/abs/{info['arxiv_id']}"
                elif info and info.get("pdf_url"):
                    figs = figures_from_pdf_url(info["pdf_url"], out_dir)
                    if figs:
                        p["open_version"] = info["pdf_url"]
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
