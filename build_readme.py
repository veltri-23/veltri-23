#!/usr/bin/env python3
"""Regenerate Building / Contributing sections of the profile README from live
GitHub data. Deterministic, no LLM. Emits a GitHub-stars badge next to any entry
that maps to a real GitHub repo (auto-detected repos, or extras with a "stars":
"owner/repo" field). Only text between the START/END markers is touched."""
import json, subprocess, pathlib, re

USER = "veltri-23"
ROOT = pathlib.Path(__file__).resolve().parent
README = ROOT / "README.md"
OVR = json.loads((ROOT / "readme_overrides.json").read_text(encoding="utf-8"))
_STARS = {}

def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True, check=True).stdout

def star_count(full):
    """Live stargazers_count for owner/repo, cached; 0 when unknown."""
    if not full:
        return 0
    if full not in _STARS:
        try:
            _STARS[full] = int(gh("api", f"repos/{full}", "--jq", ".stargazers_count"))
        except Exception:
            _STARS[full] = 0
    return _STARS[full]

def badge(full):
    return (f'[![GitHub stars](https://img.shields.io/github/stars/{full}'
            f'?style=flat&color=gold)](https://github.com/{full})')

def line(name, url, blurb, stars=None):
    b = f' {badge(stars)}' if stars else ''
    return f'- **[{name}]({url})**{b} - {blurb}' if blurb else f'- **[{name}]({url})**{b}'

def owned_public_repos():
    data = json.loads(gh("api", f"users/{USER}/repos?per_page=100&type=owner", "--paginate"))
    out = [r for r in data if not (r["private"] or r["fork"] or r["archived"])
           and r["name"] not in OVR.get("building_exclude", [])]
    out.sort(key=lambda r: r["stargazers_count"], reverse=True)
    return out

def building_block():
    entries = []
    for e in OVR.get("building_extra", []):
        entries.append((e.get("pin_top", False), star_count(e.get("stars")),
                        line(e["name"], e["url"], e["blurb"], e.get("stars"))))
    for r in owned_public_repos():
        blurb = OVR.get("building_blurbs", {}).get(r["name"]) or (r["description"] or "").strip()
        entries.append((False, r["stargazers_count"],
                        line(r["name"], r["html_url"], blurb, r["full_name"])))
    # pinned entries first, then highest stars first; ties keep configured order
    entries.sort(key=lambda t: (not t[0], -t[1]))
    return "\n".join(l for _, _, l in entries) if entries else ""

def merged_pr_repos():
    data = json.loads(gh("search", "prs", "--author", USER, "--merged",
                         "--limit", "200", "--json", "repository,url"))
    repos = {}
    for pr in data:
        full = pr["repository"]["nameWithOwner"]
        if full.split("/")[0] == USER or full in OVR.get("contributing_exclude", []):
            continue
        repos.setdefault(full, []).append(pr["url"])
    return repos

def contributing_block():
    entries = []
    for e in OVR.get("contributing_extra", []):
        entries.append((star_count(e.get("stars")),
                        line(e["name"], e["url"], e["blurb"], e.get("stars"))))
    for full, urls in merged_pr_repos().items():
        n = len(urls)
        entries.append((star_count(full),
                        line(full, f"https://github.com/{full}",
                             f'{n} merged PR{"s" if n>1 else ""}', full)))
    # highest stars first; ties keep configured order (stable sort)
    entries.sort(key=lambda t: t[0], reverse=True)
    return "\n".join(l for _, l in entries) if entries else ""

def open_prs():
    """Non-draft PRs still awaiting review on repos I don't own."""
    data = json.loads(gh("search", "prs", "--author", USER, "--state", "open",
                         "--limit", "100", "--json", "repository,url,title,number,isDraft"))
    return [p for p in data
            if not p["isDraft"]
            and p["repository"]["nameWithOwner"].split("/")[0] != USER
            and p["repository"]["nameWithOwner"] not in OVR.get("pending_exclude", [])]

def pending_block():
    """Open PRs grouped by repo: repo line, then one bullet per PR."""
    prs = sorted(open_prs(), key=lambda p: (p["repository"]["nameWithOwner"], p["number"]))
    if not prs:
        return ""   # whole section (heading included) disappears
    lines = []
    # group by repo, then order groups by stars desc; PRs by number within
    by_repo = {}
    for p in prs:
        by_repo.setdefault(p["repository"]["nameWithOwner"], []).append(p)
    groups = sorted(by_repo.items(), key=lambda kv: star_count(kv[0]), reverse=True)
    for full, repo_prs in groups:
        # one badge per repo; each PR gets its own sub-bullet
        b = f' {badge(full)}' if full else ''
        lines.append(f'- **{full}**{b}')
        for p in repo_prs:
            o = OVR.get("pending_overrides", {}).get(f'{full}#{p["number"]}', {})
            blurb = o.get("blurb", p["title"])
            link = f'[#{p["number"]}]({p["url"]})'
            lines.append(f'  - {link} - {blurb}' if blurb else f'  - {link}')
    return "\n".join(lines)

def replace(md, key, heading, body):
    s, e = f"<!-- {key}:START -->", f"<!-- {key}:END -->"
    content = f"{heading}\n{body}" if body else ""
    new = f"{s}\n{content}\n{e}"
    return re.sub(re.escape(s)+r".*?"+re.escape(e), new, md, flags=re.S)

md = README.read_text(encoding="utf-8")
md = replace(md, "BUILDING", "#### Building", building_block())
md = replace(md, "CONTRIB", "#### Contributing to", contributing_block())
md = replace(md, "PENDING", "#### Open pull request contributions", pending_block())
README.write_text(md, encoding="utf-8")
