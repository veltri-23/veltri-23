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

def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True, check=True).stdout

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
    lines = [line(e["name"], e["url"], e["blurb"], e.get("stars"))
             for e in OVR.get("building_extra", [])]
    for r in owned_public_repos():
        blurb = OVR.get("building_blurbs", {}).get(r["name"]) or (r["description"] or "").strip()
        lines.append(line(r["name"], r["html_url"], blurb, r["full_name"]))
    return "\n".join(lines)

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
    lines = [line(e["name"], e["url"], e["blurb"], e.get("stars"))
             for e in OVR.get("contributing_extra", [])]
    for full, urls in sorted(merged_pr_repos().items(), key=lambda kv: -len(kv[1])):
        n = len(urls)
        lines.append(line(full, f"https://github.com/{full}",
                          f'{n} merged PR{"s" if n>1 else ""}', full))
    return "\n".join(lines) if lines else "_(nothing yet)_"

def open_prs():
    """Non-draft PRs still awaiting review on repos I don't own."""
    data = json.loads(gh("search", "prs", "--author", USER, "--state", "open",
                         "--limit", "100", "--json", "repository,url,title,number,isDraft"))
    return [p for p in data
            if not p["isDraft"]
            and p["repository"]["nameWithOwner"].split("/")[0] != USER
            and p["repository"]["nameWithOwner"] not in OVR.get("pending_exclude", [])]

def pending_block():
    prs = sorted(open_prs(), key=lambda p: (p["repository"]["nameWithOwner"], p["number"]))
    if not prs:
        return ""   # whole section (heading included) disappears
    lines = ["#### Open pull request contributions"]
    for p in prs:
        full = p["repository"]["nameWithOwner"]
        o = OVR.get("pending_overrides", {}).get(f'{full}#{p["number"]}', {})
        lines.append(line(o.get("name", f'{full}#{p["number"]}'), p["url"],
                          o.get("blurb", p["title"]), full))
    return "\n".join(lines)

def replace(md, key, body):
    s, e = f"<!-- {key}:START -->", f"<!-- {key}:END -->"
    new = f"{s}\n{body}\n{e}" if body else f"{s}\n{e}"
    return re.sub(re.escape(s)+r".*?"+re.escape(e), new, md, flags=re.S)

md = README.read_text(encoding="utf-8")
md = replace(md, "BUILDING", building_block())
md = replace(md, "CONTRIB", contributing_block())
md = replace(md, "PENDING", pending_block())
README.write_text(md, encoding="utf-8")
