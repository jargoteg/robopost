"""Mechanical enforcement of SYSTEM.md invariants. Runs in CI on every push:
if a change violates a rule that once caused a production incident, the build
fails before the bug ships again."""
import glob
import re
import yaml

WF = sorted(glob.glob(".github/workflows/*.yml"))


def _read(p):
    return open(p).read()


def test_no_rebase_skip_anywhere():
    """Invariant 1: rebase --skip discards commits (lost-media incident)."""
    for p in WF:
        assert "rebase --skip" not in _read(p), f"{p} uses git rebase --skip"


def test_commits_include_media():
    """Invariant 2: committing only data/ orphaned card URLs in issues."""
    for p in WF:
        s = _read(p)
        for m in re.finditer(r"git add ([^\n]+)", s):
            line = m.group(1)
            if line.strip().startswith("data") and "media" not in line:
                # allowed only as the fallback branch of 'add media || add data'
                ctx = s[max(0, m.start() - 80):m.start()]
                assert "|| git add data" in s[m.start() - 40:m.end() + 10] or \
                    "media" in ctx, f"{p}: 'git add data' without media"


def test_shared_concurrency_group():
    """Invariant 5: separate groups let runs post duplicates."""
    exempt = {"ack.yml", "ci.yml"}
    for p in WF:
        name = p.split("/")[-1]
        if name in exempt:
            continue
        wf = yaml.safe_load(_read(p))
        conc = wf.get("concurrency")
        group = conc if isinstance(conc, str) else (conc or {}).get("group", "")
        assert "robopost" in str(group), f"{p} missing shared concurrency group"


def test_github_env_on_api_steps():
    """Invariant 9: missing GITHUB env crashed posting after Bluesky posted."""
    needs = ("post_all.py", "github_review.py")
    for p in WF:
        s = _read(p)
        for step in re.split(r"\n      - name:", s)[1:]:
            if any(n in step for n in needs):
                assert "GITHUB_TOKEN" in step, \
                    f"{p}: step running {needs} lacks GITHUB_TOKEN env:\n{step[:120]}"


def test_render_steps_have_anthropic_key():
    """Invariant 10: vision vetting needs the API key wherever cards render."""
    for p in WF:
        s = _read(p)
        for step in re.split(r"\n      - name:", s)[1:]:
            if re.search(r"(visuals|refill|litreview|media_repair)\.py", step):
                assert "ANTHROPIC_API_KEY" in step, \
                    f"{p}: rendering step lacks ANTHROPIC_API_KEY:\n{step[:120]}"


def test_ack_cannot_fail():
    """Invariant 11: the ack must never produce failure emails or block."""
    s = _read(".github/workflows/ack.yml")
    assert "continue-on-error: true" in s
    assert "|| true" in s


def test_post_all_immediate_persistence_and_idempotency():
    """Invariants 4, 11, 17."""
    s = open("src/post_all.py").read()
    assert "persist IMMEDIATELY" in s, "immediate save after post removed"
    assert "identical recent post" in s, "Bluesky idempotency check removed"
    assert "label skipped" in s, "labels must be non-fatal to posting"


def test_figure_rules():
    """Invariants 12, 13, 14."""
    v = open("src/visuals.py").read()
    assert ".thumbnail(" in v and "ImageOps.fit" not in v, \
        "aspect ratio must be preserved (thumbnail, never fit/crop)"
    f = open("src/figures.py").read()
    assert "def verify_arxiv_id" in f and "verify_arxiv_id(" in f.replace(
        "def verify_arxiv_id", "", 1), "arXiv id title-verification removed"
    assert "def vet_figures" in f, "vision vetting removed"
    assert "arxiv_source_figures" in f, "source-tarball tier removed"


def test_selection_rules():
    """Invariants 18, 19, 20, 21, 22."""
    fp = open("src/fetch_papers.py").read()
    assert "Adaptive floor" in fp, "adaptive floor removed (empty-queue risk)"
    assert "posted_today_news" in fp, "per-day news budget removed"
    assert "norm_title" in fp, "title-based history dedup removed"
    vz = open("src/visuals.py").read()
    assert 'get("journal")' in vz, "journal auto-reject exemption removed"
    rf = open("src/refill.py").read()
    assert "queued" in rf, "manual-queue force-generation removed"


def test_sweep_recovery():
    """Invariants 6, 7, 8."""
    g = open("src/github_review.py").read()
    assert "def sweep" in g
    assert "will retry" in g, "sweep must retry failed manual adds"
    assert g.count("sweep()") >= 1, "handle must sweep siblings' work"


def test_system_md_exists():
    """The document itself is part of the system."""
    s = open("SYSTEM.md").read()
    assert "Hard invariants" in s and "rebase --skip" in s
