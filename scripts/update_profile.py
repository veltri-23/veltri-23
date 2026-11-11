#!/usr/bin/env python3
"""Fetch public GitHub data and render workshop stats. Python standard library only.

Private activity comes from the anonymous contribution calendar, as already shared
on the owner's profile. No private repository API is queried. Nothing is written
until every network response, calendar total, and README marker has been checked.
"""
import argparse
import calendar
import datetime as dt
import html
from html.parser import HTMLParser
import json
import pathlib
import re
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
USER = "veltri-23"
UTC = dt.timezone.utc
C = dict(bg="#181d29", frame="#604936", rail="#9d694b", line="#353d49",
         glass="#101923", cream="#f2deb6", muted="#b7b09e", green="#a7c7a3")
LEVELS = ["#28303a", "#48594b", "#73816a", "#a7ba8c", "#edcf91"]


def gh_json(*args):
    result = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("GitHub API request failed; no profile files were updated.")
    data = json.loads(result.stdout)
    if isinstance(data, dict) and data.get("errors"):
        raise RuntimeError("GitHub returned GraphQL errors; no profile files were updated.")
    return data


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.tips, self.heading = {}, {}, []
        self.tip_id = None
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-date" in attrs:
            self.cells[attrs["id"]] = attrs["data-date"]
        if tag == "tool-tip":
            self.tip_id = attrs.get("for")
        if tag == "h2" and attrs.get("id") == "js-contribution-activity-description":
            self.in_heading = True

    def handle_data(self, data):
        if self.tip_id:
            self.tips[self.tip_id] = self.tips.get(self.tip_id, "") + data
        if self.in_heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "tool-tip":
            self.tip_id = None
        if tag == "h2":
            self.in_heading = False


def parse_calendar(source, year):
    parser = CalendarParser()
    parser.feed(source)
    days = {}
    for cell_id, date in parser.cells.items():
        if not date.startswith(f"{year}-"):
            continue
        text = parser.tips.get(cell_id, "").strip()
        match = re.match(r"(No|[\d,]+) contributions? on\b", text)
        if not match:
            raise ValueError(f"GitHub calendar tooltip format changed for {date}")
        if date in days:
            raise ValueError("Duplicate calendar date")
        days[date] = 0 if match[1] == "No" else int(match[1].replace(",", ""))
    match = re.search(r"([\d,]+)\s+contributions?", " ".join(parser.heading))
    if not match or len(days) != (366 if calendar.isleap(year) else 365):
        raise ValueError("Incomplete GitHub contribution calendar")
    if sum(days.values()) != int(match[1].replace(",", "")):
        raise ValueError("Calendar day counts disagree with GitHub's annual total")
    return days


def fetch_calendar(year):
    url = f"https://github.com/users/{USER}/contributions?from={year}-01-01&to={year}-12-31"
    request = urllib.request.Request(url, headers={"User-Agent": "veltri-profile-workshop", "Accept-Language": "en-US"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return parse_calendar(response.read().decode("utf-8"), year)


def public_prs(start, end):
    """Partition the search window before GitHub's 1000-result ceiling."""
    query = f"is:pr is:public author:{USER} -user:{USER} created:{start}..{end}"

    def page(n):
        result = gh_json("--method", "GET", "search/issues", "-f", f"q={query}", "-f", "per_page=100", "-f", f"page={n}")
        if result.get("incomplete_results"):
            raise ValueError("GitHub search returned incomplete results")
        return result

    first = page(1)
    if first["total_count"] > 1000:
        if start == end:
            raise ValueError("Too many pull requests in one day for exhaustive search")
        mid = start + (end - start) // 2
        return public_prs(start, mid) + public_prs(mid + dt.timedelta(days=1), end)
    items = first["items"]
    for number in range(2, (first["total_count"] + 99) // 100 + 1):
        items.extend(page(number)["items"])
    if len(items) != first["total_count"]:
        raise ValueError("PR search changed during pagination; retry the refresh")
    # Allowlist only public search results and their fields. No raw responses saved.
    return [dict(repository=p["repository_url"].split("/repos/")[1], number=p["number"],
                 title=p["title"], url=p["html_url"], state=p["state"], draft=p.get("draft", False),
                 merged_at=p["pull_request"].get("merged_at"), created_at=p["created_at"])
            for p in items]


def collect():
    now = dt.datetime.now(UTC)
    today = now.date()
    query = 'query { viewer { login } user(login:"veltri-23") { createdAt pullRequests(states:MERGED) { totalCount } contributionsCollection { contributionYears } } }'
    response = gh_json("graphql", "-f", f"query={query}")["data"]
    if response['viewer']['login'].lower() != USER:
        raise ValueError('Private lifetime stats require the owner account. Configure PROFILE_STATS_TOKEN; a repository GITHUB_TOKEN cannot supply these totals.')
    account = response['user']
    years = sorted(set(account["contributionsCollection"]["contributionYears"]))
    if not years or years[-1] > today.year:
        raise ValueError("Invalid contribution years")
    history = {}
    for year in years:
        history.update(fetch_calendar(year))
    history = {d: n for d, n in sorted(history.items()) if d <= today.isoformat()}
    prs = public_prs(dt.date(years[0], 1, 1), today)
    if len({p["url"] for p in prs}) != len(prs):
        raise ValueError("Duplicate PRs across search windows")
    totals = {}
    for visibility in ('public', 'private'):
        for metric, endpoint, qualifiers in [('commits', 'commits', ''), ('merged_prs', 'issues', 'is:pr is:merged')]:
            result = gh_json('--method', 'GET', f'search/{endpoint}', '-f', f'q=author:{USER} is:{visibility} {qualifiers}'.strip(), '-f', 'per_page=1', '--jq', '{total_count,incomplete_results}')
            if result.get('incomplete_results'):
                raise ValueError('Incomplete lifetime-count search; retaining the prior snapshot')
            totals[f'{metric}_{visibility}'] = result['total_count']
    totals['merged_prs'] = totals['merged_prs_public'] + totals['merged_prs_private']
    totals['commits'] = totals['commits_public'] + totals['commits_private']
    if totals['merged_prs'] != account['pullRequests']['totalCount']:
        raise ValueError('PR search and account totals disagree; retry after GitHub finishes indexing')
    # Validate the curated release-adoption ledger, separately from direct merges.
    ledger = json.loads((ROOT / "data" / "credited-releases.json").read_text())
    for item in ledger:
        release = gh_json(f'repos/{item["repository"]}/pulls/{item["release"]}')
        if not release.get("merged_at"):
            raise ValueError("A curated release is no longer verifiably merged")
    start = today - dt.timedelta(days=364)
    recent = [{"date": (start + dt.timedelta(days=i)).isoformat(),
               "count": history.get((start + dt.timedelta(days=i)).isoformat(), 0)} for i in range(365)]
    return dict(schema=2, user=USER, updated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
                account_created=account["createdAt"][:10], years=years,
                scope="Public profile contribution counts, including anonymized private activity shared by the owner",
                history=[{"date": d, "count": n} for d, n in history.items()], recent=recent,
                lifetime_contributions=sum(history.values()), active_days=sum(n > 0 for n in history.values()),
                recent_contributions=sum(d["count"] for d in recent),
                upstream_merged=sum(bool(p["merged_at"]) for p in prs),
                upstream_repositories=len({p["repository"] for p in prs}),
                upstream_prs=prs, credited_releases=len(ledger), credited_contributions=ledger,
                lifetime_merged_prs=totals['merged_prs'], lifetime_commits=totals['commits'], lifetime_breakdown=totals)


def rect(x, y, w, h, color, **attrs):
    extras = " ".join(f'{k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}" {extras}/>'


def text(value, x, y, size=16, color=None, anchor="start"):
    return f'<text x="{x}" y="{y}" font-family="monospace" font-size="{size}" fill="{color or C["cream"]}" text-anchor="{anchor}">{html.escape(str(value))}</text>'


DIGITS = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
}


def counter(value, x, y, width, height=52):
    digits = str(value)
    scale = min(7, (width - 20) / (4 * len(digits)), (height - 14) / 5)
    gap = scale * 4
    start = x + (width - gap * len(digits) + scale) / 2
    result = rect(x, y, width, height, C["glass"])
    for i, digit in enumerate(digits):
        dx = start + i * gap
        result += rect(dx - 2, y + 5, scale * 3 + 4, height - 10, "#1e292c")
        for row, bits in enumerate(DIGITS[digit]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    result += rect(round(dx + col * scale, 2), round(y + 8 + row * scale, 2), round(scale - .8, 2), round(scale - .8, 2), C["cream"])
    return result


def shell(width, height, title, description):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>{html.escape(title)}</title><desc>{html.escape(description)}</desc>'
    svg += rect(0, 0, width, height, C["bg"]) + rect(0, 0, width, 7, C["rail"]) + rect(0, height - 7, width, 7, C["rail"])
    for x in [15, width - 15]:
        for y in [17, height - 17]:
            svg += f'<circle cx="{x}" cy="{y}" r="4" fill="{C["muted"]}"/><path d="M{x-2} {y+2}l4 -4" stroke="{C["glass"]}"/>'
    return svg


def weeks(days):
    first = dt.date.fromisoformat(days[0]["date"])
    cells = [None] * ((first.weekday() + 1) % 7) + list(days)
    cells += [None] * ((-len(cells)) % 7)
    return [cells[i:i+7] for i in range(0, len(cells), 7)]


def grid(columns, x, y, step, thresholds):
    result, last_month = "", None
    for col, column in enumerate(columns):
        valid = next((d for d in column if d), None)
        if valid:
            month = dt.date.fromisoformat(valid["date"]).strftime("%b")
            if month != last_month:
                result += text(month, x + col * step, y - 12, 12, C["muted"])
                last_month = month
        for row, day in enumerate(column):
            count = day["count"] if day else 0
            level = 0 if not count else 1 + sum(count > threshold for threshold in thresholds)
            title = f'{day["date"]}: {count} contributions' if day else "Outside the displayed period"
            result += f'<g><title>{title}</title>' + rect(x + col * step, y + row * step, step - 4, step - 4, LEVELS[level] if day else C["bg"]) + '</g>'
            if count:
                result += rect(x + col * step, y + row * step, step - 4, 2, "#ffffff", opacity=".12")
    return result


def activity_svg(data, mobile=False):
    width, height = (520, 476) if mobile else (1040, 330)
    count = data["recent_contributions"]
    result = shell(width, height, "Work log", f'{count:,} GitHub contributions in the past 365 days. Public and anonymized private activity from the public profile.')
    result += text("THE WORK LOG", 34, 48, 24)
    result += text("PAST 365 DAYS", 34, 73, 13, C["muted"])
    result += counter(count, width - 230, 28, 190, 52)
    result += rect(32, 94, width - 64, 1, C["line"])
    cols = weeks(data["recent"])
    positive = sorted(d["count"] for d in data["recent"] if d["count"])
    thresholds = [positive[(len(positive) - 1) * q // 4] for q in (1, 2, 3)] if positive else [0, 0, 0]
    if mobile:
        result += grid(cols[:27], 34, 133, 17, thresholds)
        result += grid(cols[27:], 34, 287, 17, thresholds)
        result += text("PUBLIC + ANONYMIZED PRIVATE ACTIVITY", 34, 424, 12, C["green"])
        result += text(data["updated_at"], 34, 450, 12, C["muted"])
    else:
        result += grid(cols, 52, 135, 18, thresholds)
        result += text("PUBLIC + ANONYMIZED PRIVATE ACTIVITY", 34, 292, 14, C["green"])
        result += text(data["updated_at"], width - 34, 292, 13, C["muted"], "end")
    return result + '</svg>'


def lifetime_svg(data, mobile=False):
    width, height = (520, 440) if mobile else (1040, 240)
    result = shell(width, height, "Lifetime stats", "Contributions, authored merged PRs, and indexed authored commits. Includes public and private activity available to the owner account. GitHub indexing and access limits apply.")
    result += text("LIFETIME STATS", 34, 48, 24)
    result += text(f'GITHUB HISTORY / {min(data["years"])} ONWARD', 34, 72, 12, C["muted"])
    metrics = [("CONTRIBUTIONS", data["lifetime_contributions"]), ("MERGED PRs", data["lifetime_merged_prs"]),
               ("COMMITS", data["lifetime_commits"])]
    for i, (label, number) in enumerate(metrics):
        x, y = (34, 100 + i * 100) if mobile else (34 + i * 330, 102)
        result += counter(number, x, y, 270 if mobile else 296, 60)
        result += text(label, x + 292 if mobile else x, y + 34 if mobile else y + 83, 13, C["green"])
    result += text("PUBLIC + PRIVATE / GITHUB INDEXED ACTIVITY", 34, height - 26, 11, C["muted"])
    return result + '</svg>'


def replace_block(markdown, key, body):
    begin, end = f'<!-- {key}:START -->', f'<!-- {key}:END -->'
    if markdown.count(begin) != 1 or markdown.count(end) != 1:
        raise ValueError(f'Missing or duplicate README markers: {key}')
    return re.sub(re.escape(begin) + r'.*?' + re.escape(end), lambda _: begin + '\n' + body + '\n' + end, markdown, flags=re.S)


def safe_title(title):
    return html.escape(title.replace('\n', ' ')).replace('[', '&#91;').replace(']', '&#93;').replace('*', '&#42;').replace('_', '&#95;').replace('`', '&#96;')


def readme_updates(markdown, data):
    open_prs = [p for p in data["upstream_prs"] if p["state"] == "open"]
    open_prs.sort(key=lambda p: p["created_at"], reverse=True)
    pending = '\n'.join(f'- [{p["repository"]} #{p["number"]}]({p["url"]}): {safe_title(p["title"])}' + (' (draft)' if p["draft"] else '') for p in open_prs) or 'No open public upstream PRs.'
    markdown = replace_block(markdown, 'PENDING', pending)
    summary = f'<sub>Data updated {data["updated_at"]} · {data["upstream_merged"]} directly merged upstream PRs · {data["credited_releases"]} GBrain contributions credited in releases · {len(open_prs)} open PRs</sub>'
    markdown = replace_block(markdown, 'COUNTS', summary)
    target = next((p for p in data['upstream_prs'] if p['repository'] == 'NousResearch/hermes-agent' and p['number'] == 82649), None)
    if not target:
        raise ValueError('Could not verify Hermes memory-provider support')
    status = 'merged upstream' if target['merged_at'] else ('proposed in an open PR' if target['state'] == 'open' else 'closed without a direct merge; see the discussion for its disposition')
    markdown = replace_block(markdown, 'MEMORY_STATUS', f'Requires [Hermes standalone-provider support](https://github.com/NousResearch/hermes-agent/pull/82649), {status}.')
    latest = sorted(data['upstream_prs'], key=lambda p: p['created_at'], reverse=True)[:3]
    lines = []
    for p in latest:
        status = 'merged' if p['merged_at'] else ('open' if p['state'] == 'open' else 'closed')
        credit = next((c for c in data.get('credited_contributions', []) if c['repository'] == p['repository'] and c['original'] == p['number']), None)
        if credit and not p['merged_at']:
            status = 'diagnosis credited in release' if credit['kind'] == 'diagnosis' else 'incorporated in release with credit'
        lines.append(f'- [{p["repository"]} #{p["number"]}]({p["url"]}): {safe_title(p["title"])} ({status}).')
    return replace_block(markdown, 'RECENT', '\n'.join(lines))


def outputs(data, markdown):
    result = {'README.md': readme_updates(markdown, data), 'data/profile-stats.json': json.dumps(data, indent=2) + '\n'}
    for mobile in [False, True]:
        suffix = '-mobile' if mobile else ''
        result[f'assets/work-log{suffix}.svg'] = activity_svg(data, mobile)
        result[f'assets/lifetime{suffix}.svg'] = lifetime_svg(data, mobile)
    return result


def preserve_data_timestamp(data, previous):
    """A successful poll alone must not produce a public commit every ten minutes."""
    current_values = {k: v for k, v in data.items() if k != 'updated_at'}
    previous_values = {k: v for k, v in previous.items() if k != 'updated_at'}
    if current_values == previous_values:
        data = dict(data, updated_at=previous['updated_at'])
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-snapshot', action='store_true', help='Render the existing snapshot without network requests; its timestamp remains unchanged.')
    args = parser.parse_args()
    data = json.loads((ROOT / 'data/profile-stats.json').read_text()) if args.from_snapshot else collect()
    if not args.from_snapshot and (ROOT / 'data/profile-stats.json').exists():
        data = preserve_data_timestamp(data, json.loads((ROOT / 'data/profile-stats.json').read_text()))
    rendered = outputs(data, (ROOT / 'README.md').read_text())
    for filename, content in rendered.items():
        destination = ROOT / filename
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(destination)
    print(f'Updated public/private aggregate totals and {len(data["upstream_prs"])} public upstream PRs. Only count fields are retained for private activity.')


if __name__ == '__main__':
    main()
