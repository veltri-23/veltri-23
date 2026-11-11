# Updating the workshop profile

The profile uses checked-in images and aggregate GitHub data. The updater changes only designated README blocks, the data snapshot and four stats images. The masthead, conveyor artwork and personal copy are preserved.

## Run locally

With GitHub CLI authenticated as `veltri-23` and authorized to read the relevant private repositories:

```sh
python -m unittest discover -s tests -v
python scripts/update_profile.py
git diff --check
```

Only commit `README.md`, `data/profile-stats.json`, `assets/work-log*.svg` and `assets/lifetime*.svg` after reviewing the diff. When data is unchanged, the updater retains the previous timestamp and produces no timestamp-only commit. `build_readme.py` delegates to the new updater; the legacy `readme_overrides.json` is unused.

## Run on a schedule

Use one scheduled writer: either an owner-authenticated external runner or the included GitHub Actions workflow.

For GitHub Actions:

1. Configure `PROFILE_STATS_TOKEN` as a repository Actions secret, authenticated as the owner with read access to the private repositories being counted. Never place a credential in source or an image URL.
2. Run `Update workshop profile` manually and verify the resulting data and commit.
3. Set repository Actions variable `PROFILE_STATS_ENABLED` to `true` to enable its scheduled job. The target cadence is every ten minutes, at minutes 3, 13, 23, 33, 43 and 53. Leave the variable unset or false when an external runner owns maintenance.

The default `GITHUB_TOKEN` handles repository writes but cannot supply owner-wide private totals. Scheduled execution is deliberately gated until owner authentication is configured. Do not claim the schedule is running merely because the workflow file exists.

## What the numbers mean

- Contributions: daily contribution-calendar totals across the account's GitHub contribution years, including anonymized private activity already shared on the public profile.
- Merged PRs: PRs authored by this account, across public and private repositories, including owned repositories.
- Commits: GitHub-indexed authored commits across public and private repositories accessible to the owner's credential. This does not claim every local or non-indexed branch commit.
- Upstream: the separately labeled public contribution section excludes repositories owned by this account. Direct merges and curated release credits are separate.

Only aggregate counts are retained for private activity. The public snapshot contains public upstream PR metadata, not private repository names, private PR titles or private commit messages. Curated release credits require evidence in `data/credited-releases.json`.

Calendar parsing, incomplete API responses and inconsistent totals fail the refresh before output files are written. Retain the last valid snapshot on failures. GitHub indexing, scheduled execution and image caching can lag; this profile does not guarantee instant updates on each page view.
