import datetime as dt
import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_stats', ROOT / 'scripts/update_profile.py')
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def calendar_html(year, count=1):
    day, end = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
    cells = []
    while day < end:
        name = day.isoformat()
        cells.append(f'<td id="day-{name}" data-date="{name}"></td><tool-tip for="day-{name}">{count} contribution on example date.</tool-tip>')
        day += dt.timedelta(days=1)
    return f'<h2 id="js-contribution-activity-description">{len(cells) * count} contributions in {year}</h2>' + ''.join(cells)


class CalendarTests(unittest.TestCase):
    def test_leap_year_counts_each_day_once(self):
        days = stats.parse_calendar(calendar_html(2024), 2024)
        self.assertEqual(len(days), 366)
        self.assertEqual(sum(days.values()), 366)

    def test_bad_total_is_not_published(self):
        source = calendar_html(2025).replace('365 contributions in', '999 contributions in')
        with self.assertRaises(ValueError):
            stats.parse_calendar(source, 2025)

    def test_changed_or_missing_tooltip_fails(self):
        source = calendar_html(2025).replace('1 contribution on', 'Unknown value', 1)
        with self.assertRaises(ValueError):
            stats.parse_calendar(source, 2025)

    def test_duplicate_date_fails(self):
        source = calendar_html(2025) + '<td id="dupe" data-date="2025-01-01"></td><tool-tip for="dupe">1 contribution on example.</tool-tip>'
        with self.assertRaises(ValueError):
            stats.parse_calendar(source, 2025)

    def test_mobile_grid_keeps_every_day(self):
        days = [{'date': (dt.date(2025, 11, 11) + dt.timedelta(days=i)).isoformat(), 'count': i} for i in range(365)]
        columns = stats.weeks(days)
        flattened = [d for col in columns[:27] + columns[27:] for d in col if d]
        self.assertEqual(flattened, days)


class SourceAndUpdateTests(unittest.TestCase):
    def test_unchanged_counts_do_not_create_timestamp_churn(self):
        old = {'updated_at': 'old', 'count': 10}
        self.assertEqual(stats.preserve_data_timestamp({'updated_at': 'new', 'count': 10}, old), old)
        self.assertEqual(stats.preserve_data_timestamp({'updated_at': 'new', 'count': 11}, old)['updated_at'], 'new')

    def test_lifetime_panel_uses_all_visibility_metrics(self):
        data = dict(years=[2026], lifetime_contributions=1000, lifetime_merged_prs=362, lifetime_commits=5840, upstream_merged=9)
        svg = stats.lifetime_svg(data)
        self.assertIn('MERGED PRs', svg)
        self.assertIn('COMMITS', svg)
        self.assertNotIn('UPSTREAM PRs', svg)
        self.assertNotIn('ACTIVE DAYS', svg)
    def test_public_query_and_allowlisted_output(self):
        raw = dict(repository_url='https://api.github.com/repos/example/tool', number=1,
                   title='Fix', html_url='https://github.com/example/tool/pull/1', state='closed',
                   pull_request={'merged_at': '2026-01-02'}, created_at='2026-01-01',
                   body='DO NOT EXPORT raw body', extra='not an output field')
        with patch.object(stats, 'gh_json', return_value={'total_count': 1, 'incomplete_results': False, 'items': [raw]}) as api:
            result = stats.public_prs(dt.date(2026, 1, 1), dt.date(2026, 1, 2))
        self.assertIn('is:public', ' '.join(api.call_args.args))
        self.assertNotIn('DO NOT EXPORT', json.dumps(result))
        self.assertNotIn('body', result[0])

    def test_incomplete_search_fails(self):
        with patch.object(stats, 'gh_json', return_value={'incomplete_results': True}):
            with self.assertRaises(ValueError):
                stats.public_prs(dt.date(2026, 1, 1), dt.date(2026, 1, 2))

    def test_missing_marker_fails_instead_of_silent_staleness(self):
        with self.assertRaises(ValueError):
            stats.replace_block('no marker', 'PENDING', 'new')

    def test_marked_update_preserves_handwritten_copy(self):
        source = 'Approved art\n<!-- PENDING:START -->old<!-- PENDING:END -->\nPersonal biography'
        result = stats.replace_block(source, 'PENDING', 'fresh')
        self.assertEqual(result, 'Approved art\n<!-- PENDING:START -->\nfresh\n<!-- PENDING:END -->\nPersonal biography')

    def test_release_credit_is_separate_from_direct_merge(self):
        prs = [dict(repository='garrytan/gbrain', number=7380, title='Relink index', state='closed', merged_at=None, created_at='2026-10-22', url='https://github.com/garrytan/gbrain/pull/7380', draft=False),
               dict(repository='garrytan/gbrain', number=7136, title='Title search', state='closed', merged_at=None, created_at='2026-10-20', url='https://github.com/garrytan/gbrain/pull/7136', draft=False),
               dict(repository='NousResearch/hermes-agent', number=82649, title='Memory providers', state='open', merged_at=None, created_at='2026-08-09', url='https://github.com/NousResearch/hermes-agent/pull/82649', draft=False)]
        data = dict(upstream_prs=prs, updated_at='2026-11-11 00:00 UTC', upstream_merged=0, credited_releases=2,
                    credited_contributions=[dict(repository='garrytan/gbrain', original=7380, kind='implementation'), dict(repository='garrytan/gbrain', original=7136, kind='diagnosis')])
        source = '\n'.join(f'<!-- {key}:START --><!-- {key}:END -->' for key in ['PENDING', 'COUNTS', 'MEMORY_STATUS', 'RECENT'])
        result = stats.readme_updates(source, data)
        self.assertIn('incorporated in release with credit', result)
        self.assertIn('diagnosis credited in release', result)
        self.assertIn('0 directly merged upstream PRs', result)


if __name__ == '__main__':
    unittest.main()
