"""Build lukeofwales.github.io — a self-updating portfolio hub.

Discovers the owner's public repositories that have a live (built) GitHub Pages
site, gathers rich metadata for each, and renders a static index.html.

Runs in CI (see .github/workflows/deploy.yml) on a daily schedule, so newly
published Pages sites appear automatically. Uses the GitHub REST API via the
`GITHUB_TOKEN` provided in Actions (or a local `gh` token / GITHUB_TOKEN env
var when run by hand).

Usage:  python build.py   [writes ./index.html]
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

OWNER = os.environ.get("GH_OWNER", "LukeOfWales")
SITE_DIR = Path(__file__).resolve().parent / "_site"
OUT = SITE_DIR / "index.html"
API = "https://api.github.com"

# Short tagline for the hero.
TAGLINE = "Tinkering with motorsport, the workshop, and code — a home for the things I build and put online."

# Language -> accent colour (GitHub-ish), for the language dot.
LANG_COLOURS = {
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "HTML": "#e34c26", "CSS": "#563d7c", "Shell": "#89e051", "VBScript": "#15dcdc",
    "Go": "#00ADD8", "Rust": "#dea584", "Java": "#b07219", "C": "#555555",
    "C++": "#f34b7d", "Ruby": "#701516", "Vue": "#41b883", "Svelte": "#ff3e00",
}


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    # Fall back to the local gh CLI token when running by hand.
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def api(path: str) -> object:
    """GET the GitHub API, returning parsed JSON (or [] / {} on 404)."""
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "lukeofwales-hub-builder",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise


def list_owned_public_repos() -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        batch = api(f"/users/{OWNER}/repos?per_page=100&page={page}&type=owner&sort=updated")
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repos if not r.get("private") and not r.get("archived")]


def pages_url(repo: str) -> str | None:
    """Return the live Pages URL for a repo, or None if it isn't serving.

    Deliberately avoids the /repos/{owner}/{repo}/pages API: that endpoint
    requires a token with Pages access on each repo, which the CI GITHUB_TOKEN
    doesn't have for *other* repos. Instead we rely on `has_pages` from the
    (public, unauthenticated) repo listing to know Pages is enabled, then
    confirm the deterministic project-site URL is actually serving with a
    plain HTTP request.
    """
    # A user/org site (owner.github.io) serves at the root; a project site
    # serves at /{repo}/.
    if repo.lower() == f"{OWNER}.github.io".lower():
        url = f"https://{OWNER.lower()}.github.io/"
    else:
        url = f"https://{OWNER.lower()}.github.io/{repo}/"
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "lukeofwales-hub-builder",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if 200 <= r.status < 400:
                return url
    except urllib.error.HTTPError as e:
        # A built site returns 200; some setups 404 the bare path but serve
        # index.html — treat only clear success as live.
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return None


def gather() -> list[dict]:
    """Return metadata for each public repo with a live Pages site."""
    # The user-site repo (owner.github.io) hosts this hub itself — don't list it.
    self_repo = f"{OWNER}.github.io".lower()
    projects: list[dict] = []
    for repo in list_owned_public_repos():
        if repo["name"].lower() == self_repo:
            continue
        if not repo.get("has_pages"):
            continue
        url = pages_url(repo["name"])
        if not url:
            continue  # Pages enabled but not built/live yet
        langs = api(f"/repos/{OWNER}/{repo['name']}/languages") or {}
        total = sum(langs.values()) or 1
        lang_breakdown = sorted(
            ({"name": k, "pct": round(v / total * 100)} for k, v in langs.items()),
            key=lambda x: -x["pct"],
        )
        projects.append({
            "name": repo["name"],
            "title": repo["name"].replace("-", " ").replace("_", " ").title(),
            "description": repo.get("description") or "",
            "site_url": url,
            "repo_url": repo["html_url"],
            "language": repo.get("language"),
            "languages": lang_breakdown,
            "topics": repo.get("topics") or [],
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "updated": repo.get("pushed_at") or repo.get("updated_at"),
            "license": (repo.get("license") or {}).get("spdx_id"),
        })
    # Sort: most recently pushed first.
    projects.sort(key=lambda p: p["updated"] or "", reverse=True)
    return projects


# --- rendering -----------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(s or "")


def rel_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        return f"{days // 30} month{'s' if days // 30 > 1 else ''} ago"
    return f"{days // 365} year{'s' if days // 365 > 1 else ''} ago"


def lang_dot(lang: str | None) -> str:
    if not lang:
        return ""
    colour = LANG_COLOURS.get(lang, "#8b949e")
    return f'<span class="lang-dot" style="background:{colour}"></span>{esc(lang)}'


def render_card(p: dict) -> str:
    topics = "".join(f'<span class="topic">{esc(t)}</span>' for t in p["topics"][:6])
    meta_bits = []
    if p["language"]:
        meta_bits.append(f'<span class="meta-item">{lang_dot(p["language"])}</span>')
    if p["stars"]:
        meta_bits.append(f'<span class="meta-item">★ {p["stars"]}</span>')
    if p["license"] and p["license"] != "NOASSERTION":
        meta_bits.append(f'<span class="meta-item">{esc(p["license"])}</span>')
    if p["updated"]:
        meta_bits.append(f'<span class="meta-item">updated {esc(rel_time(p["updated"]))}</span>')
    meta = "".join(meta_bits)

    # Language bar (proportional).
    bar = ""
    if p["languages"]:
        segs = "".join(
            f'<span style="width:{l["pct"]}%;background:{LANG_COLOURS.get(l["name"], "#8b949e")}" '
            f'title="{esc(l["name"])} {l["pct"]}%"></span>'
            for l in p["languages"]
        )
        bar = f'<div class="langbar">{segs}</div>'

    desc = esc(p["description"]) or '<span class="muted">No description</span>'
    return f"""
      <article class="card">
        <a class="card-main" href="{esc(p['site_url'])}" target="_blank" rel="noopener">
          <h2 class="card-title">{esc(p['title'])}</h2>
          <p class="card-desc">{desc}</p>
        </a>
        <div class="topics">{topics}</div>
        {bar}
        <div class="card-meta">{meta}</div>
        <div class="card-links">
          <a class="btn primary" href="{esc(p['site_url'])}" target="_blank" rel="noopener">Visit site \u2197</a>
          <a class="btn" href="{esc(p['repo_url'])}" target="_blank" rel="noopener">Source</a>
        </div>
      </article>"""


def render(projects: list[dict]) -> str:
    cards = "\n".join(render_card(p) for p in projects) or (
        '<p class="empty">No published GitHub Pages sites found yet.</p>'
    )
    built = datetime.now(timezone.utc).strftime("%d %b %Y")
    count = len(projects)
    return TEMPLATE.format(
        owner=OWNER, tagline=esc(TAGLINE), cards=cards, built=built,
        count=count, count_plural="" if count == 1 else "s",
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en-GB">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{owner} — projects</title>
  <meta name="description" content="A hub of {owner}'s published projects and live web apps." />
  <meta name="theme-color" content="#0d1117" />
  <meta property="og:title" content="{owner} — projects" />
  <meta property="og:description" content="A hub of published projects and live web apps." />
  <meta property="og:type" content="website" />
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%230d1117'/%3E%3Ctext x='8' y='12' font-size='11' text-anchor='middle' fill='%2358a6ff' font-family='sans-serif'%3EL%3C/text%3E%3C/svg%3E" />
  <link rel="stylesheet" href="./style.css" />
</head>
<body>
  <div class="bg"></div>
  <header class="hero">
    <div class="avatar" aria-hidden="true">L</div>
    <h1>{owner}</h1>
    <p class="tagline">{tagline}</p>
    <p class="hero-meta">
      <a href="https://github.com/{owner}" target="_blank" rel="noopener">github.com/{owner}</a>
      <span class="dot">·</span> {count} live project{count_plural}
    </p>
  </header>

  <main class="grid">
    {cards}
  </main>

  <footer>
    <p>Auto-generated from public repositories with a live GitHub Pages site.
       Last built {built}.</p>
  </footer>
</body>
</html>
"""


def main() -> int:
    import shutil
    projects = gather()
    SITE_DIR.mkdir(exist_ok=True)
    OUT.write_text(render(projects))
    # Copy static assets into the output dir.
    shutil.copy(Path(__file__).resolve().parent / "style.css", SITE_DIR / "style.css")
    print(f"Wrote {OUT} with {len(projects)} project(s):")
    for p in projects:
        print(f"  - {p['name']}: {p['site_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
