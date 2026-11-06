#!/usr/bin/env python3
"""Reference only: inspect Upcoming cards in a visible, guarded Circle browser.

Observed on the English Circle UI on 2026-10-27 (five cards). Recheck selectors,
labels and scrolling before reuse. A stable card count is a heuristic, not proof
of complete pagination. This is not a supported event-list CLI command.

From the repository root, with the browser extra installed:
    .venv/bin/python examples/list_upcoming_events_browser.py --path /c/events

The default ProbeSession guard blocks community writes. This script neither
creates events nor changes RSVP state. Browser activity may still be logged.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from circle_client_skill.probe import ProbeSession

EXTRACT_CARDS = r"""() => Array.from(document.querySelectorAll('[data-circle="event-card"]'), card => {
  const group = card.parentElement?.parentElement;
  const heading = group?.innerText.split('\n').map(x => x.trim()).filter(Boolean) || [];
  const link = card.querySelector('a[href]');
  const title = card.querySelector('[data-circle="event-title"]');
  const date = card.querySelector('[data-circle="event-date"]');
  const spans = Array.from(link?.querySelectorAll('span') || [], e => e.innerText.trim());
  const count = card.querySelector('[role="group"][aria-label*="going"]');
  return {
    day: heading[0] || '', weekday: heading[1] || '',
    time: date?.innerText.replace(/\s*Live now\s*/g, '').trim() || '',
    live: !!date?.innerText.includes('Live now'),
    title: title?.innerText.trim() || '', href: link?.getAttribute('href') || '',
    kind: spans.find(s => ['Live stream', 'Virtual', 'In person'].includes(s)) || '',
    host: spans.find(s => s.startsWith('By ')) || '',
    going: count?.getAttribute('aria-label') || ''
  };
})"""


def cell(value: str) -> str:
    return value.replace('|', '\\|').replace('\n', ' ').strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', default='/c/events', help='Community-relative event space path')
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    args = parser.parse_args()
    if not args.path.startswith('/') or args.path.startswith('//'):
        parser.error('--path must be a community-relative path')
    with ProbeSession(env_path=args.env_file, headless=False) as probe:
        page = probe.page
        page.goto(probe.url(args.path), wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        if not probe.looks_logged_in():
            raise RuntimeError('Circle session is not logged in; refresh credentials first')
        stable, previous = 0, -1
        for _ in range(50):
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(1000)
            count = page.locator('[data-circle="event-card"]').count()
            stable = stable + 1 if count == previous else 0
            previous = count
            if stable >= 3:
                break
        else:
            raise RuntimeError('Event list did not stabilize; output would be incomplete')
        cards = page.evaluate(EXTRACT_CARDS)
        if 'Upcoming' not in page.locator('body').inner_text():
            raise RuntimeError('Upcoming view was not found; Circle page may have changed')
        if not cards:
            raise RuntimeError('No event cards found; inspect the visible page before treating it as empty')
        if any(not c['title'] or not c['href'] or not re.match(r'^[A-Za-z]+\s+\d+', c['day']) or not c['time'] for c in cards):
            raise RuntimeError('Could not read an event card or date group; Circle page may have changed')
        print('Observed Upcoming cards · account time zone · completeness not verified')
        print('| Date | Time | Event | Format | Going |')
        print('|---|---|---|---|---|')
        for c in cards:
            title = cell(c['title']).replace(']', '\\]')
            url = urljoin(probe.base_url + '/', c['href'])
            date = cell(f"{c['day']} ({c['weekday']})")
            time = cell(c['time'] + (' · Live now' if c['live'] else ''))
            print(f"| {date} | {time} | [{title}]({url}) | {cell(c['kind']) or '—'} | {cell(c['going']) or '—'} |")
        print(f'\n{len(cards)} observed cards; not a verified total. Draft and past views are not queried.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Could not read events: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
