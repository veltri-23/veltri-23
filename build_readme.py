#!/usr/bin/env python3
"""Regenerate the Building / Contributing sections of the profile README from
live GitHub data. Deterministic, no LLM: blurbs come from repo descriptions or
an overrides file, never invented. Only the text between the START/END markers
is touched; the hand-written bio/header is left alone."""
import json, subprocess, sys, pathlib, re

USER = "veltri-23"
ROOT = pathlib.Path(__file__).resolve().parent
README = ROOT / "README.md"
OVR = json.loads((ROOT / "readme_overrides.json").read_text(encoding="utf-8"))

def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout

def owned_public_repos():
    data = json.loads(gh("api", f"users/{USER}/repos?per_page=100&type=owner",
                         "--paginate"))
    out = []
    for r in data:
        if r["private"] or r["fork"] or r["archived"]:
            continue
        if r["name"] in OVR.get("building_exclude", []):
            continue
        out.append(r)
    out.sort(key=lambda r: (-r["stargazers_count"], r["pushed_at"]), reverse=False)
    out.sort(key=lambda r: r["stargazers_count"], reverse=True)
    return out

def building_block():
    lines = []
    for e in OVR.get("building_extra", []):
        lines.append(f'- **[{e["name"]}]({e["url"]})** - {e["blurb"]}')
    for r in owned_public_repos():
        blurb = OVR.get("building_blurbs", {}).get(r["name"]) or (r["description"] or "").strip()
        lines.append(f'- **[{r["name"]}]({r["html_url"]})** - {blurb}' if blurb
                     else f'- **[{r["name"]}]({r["html_url"]})**')
    return "\n".join(lines)

def merged_pr_repos():
    data = json.loads(gh("search", "prs", "--author", USER, "--merged",
                         "--limit", "200", "--json", "repository,url"))
    repos = {}
    for pr in data:
        full = pr["repository"]["nameWithOwner"]
        if full.split("/")[0] == USER:      # skip own repos
            continue
        if full in OVR.get("contributing_exclude", []):
            continue
        repos.setdefault(full, []).append(pr["url"])
    return repos

def contributing_block():
    lines = []
    for e in OVR.get("contributing_extra", []):
        lines.append(f'- **[{e["name"]}]({e["url"]})** - {e["blurb"]}')
    for full, urls in sorted(merged_pr_repos().items(), key=lambda kv: -len(kv[1])):
        n = len(urls)
        lines.append(f'- **[{full}](https://github.com/{full})** - {n} merged PR{"s" if n>1 else ""}')
    return "\n".join(lines) if lines else "_(nothing yet)_"

def replace(md, key, body):
    s, e = f"<!-- {key}:START -->", f"<!-- {key}:END -->"
    return re.sub(re.escape(s)+r".*?"+re.escape(e),
                  f"{s}\n{body}\n{e}", md, flags=re.S)

md = README.read_text(encoding="utf-8")
md = replace(md, "BUILDING", building_block())
md = replace(md, "CONTRIB", contributing_block())
README.write_text(md, encoding="utf-8")
print(md)
