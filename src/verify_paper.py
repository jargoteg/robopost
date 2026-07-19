"""Pre-draft verification: read the paper's actual text and extract facts the
abstract hides — real hardware vs simulation, key numbers, honest caveats.
One Claude call per drafted paper (not per candidate), cached by id."""
import re
import requests
from utils import load_json, save_json, claude_json


def _pdf_text(url: str, max_pages: int = 14) -> str:
    import fitz
    r = requests.get(url, timeout=90, headers={"User-Agent": "RoboPost/1.0"})
    r.raise_for_status()
    if "pdf" not in r.headers.get("content-type", "").lower() \
            and r.content[:4] != b"%PDF":
        return ""
    doc = fitz.open(stream=r.content, filetype="pdf")
    parts = [doc[i].get_text() for i in range(min(max_pages, doc.page_count))]
    # always include the last 2 pages (conclusion/limitations live there)
    if doc.page_count > max_pages:
        parts += [doc[-2].get_text(), doc[-1].get_text()]
    doc.close()
    return re.sub(r"\s+", " ", " ".join(parts))[:60000]


def verify(paper: dict) -> dict | None:
    """Returns {'hardware': 'real'|'sim'|'mixed'|'unknown', 'numbers': [...],
    'caveats': str, 'summary': str} or None if the text is unreachable."""
    pid = str(paper.get("id", ""))
    cache = load_json("verified_papers.json", {})
    if pid in cache:
        return cache[pid]
    url = None
    if re.match(r"\d{4}\.\d{4,5}", pid):
        url = f"https://arxiv.org/pdf/{pid}"
    elif paper.get("open_version", "").endswith(".pdf"):
        url = paper["open_version"]
    elif "arxiv.org/abs/" in paper.get("open_version", ""):
        url = paper["open_version"].replace("/abs/", "/pdf/")
    if not url:
        return None
    try:
        text = _pdf_text(url)
        if len(text) < 3000:
            return None
        result = claude_json(f"""Read this robotics paper and extract ONLY what
the text supports. Title: {paper.get('title', '')}

TEXT: {text}

Return JSON:
{{"hardware": "real" | "sim" | "mixed" | "unknown"
   (real = physical robot experiments; sim = simulation only;
    mixed = both; be strict, demos on hardware count as real/mixed),
 "numbers": ["3-5 most striking concrete results with units"],
 "caveats": "<200 chars: the honest limitations the authors admit>",
 "summary": "<200 chars: what was actually demonstrated, no hype>"}}""")
        if isinstance(result, dict) and result.get("hardware"):
            cache[pid] = result
            save_json("verified_papers.json", cache)
            print(f"Verified {pid}: {result['hardware']} | {result.get('summary','')[:50]}")
            return result
    except Exception as e:
        print(f"verification failed for {pid} (non-fatal): {e}")
    return None
