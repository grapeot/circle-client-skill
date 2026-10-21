"""Read-only chat change detection; delivery and checkpoint commits are separate."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .rich_text import rich_text_message_text


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
        if (state['version'] != 1 or not isinstance(state['targets'], dict)
                or not isinstance(state['source'], str)):
            raise ValueError
        for target in state['targets'].values():
            if not isinstance(target['roots'], dict) or not target['checked_at']:
                raise ValueError
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('Invalid watch state; refusing to reset baseline') from exc


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.watch-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def commit(path: Path, result: dict) -> None:
    """Compare-and-swap local checkpoint. Caller must hold its consumer lock."""
    if digest(load_state(path)) != result['base_digest']:
        raise ValueError('Watch state changed since scan; refusing stale commit')
    atomic_write(path, result['next_state'])


def _page(payload: dict, flag: str) -> list[dict]:
    if (not isinstance(payload, dict) or not isinstance(payload.get('records'), list)
            or type(payload.get(flag)) is not bool):
        raise ValueError('Invalid chat pagination response')
    records = payload['records']
    if any(not isinstance(r, dict) or type(r.get('id')) is not int for r in records):
        raise ValueError('Invalid chat message record')
    return records


def _roots(client: Any, room: str) -> list[dict]:
    """Bounded complete scan; never equate total_count with root count."""
    found: dict[int, dict] = {}
    cursor = None
    cursors: set[int] = set()
    for _ in range(100):
        payload = client.list_chat_messages(room, previous_per_page=200, cursor=cursor)
        records = _page(payload, 'has_previous_page')
        before = len(found)
        found.update({r['id']: r for r in records if r.get('parent_message_id') is None})
        if not payload['has_previous_page']:
            return list(found.values())
        cursor = payload.get('first_id')
        if type(cursor) is not int or cursor in cursors or len(found) == before:
            raise ValueError('Incomplete root scan: pagination did not progress')
        cursors.add(cursor)
    raise ValueError('Incomplete root scan: page limit reached')


def scan(client: Any, *, source: str, member_id: int, targets: list[dict],
         state: dict | None, now: str | None = None) -> dict:
    """Compute events and a candidate state, without any file or remote writes.

    Each target supplies space_id and the current member's per-room participant_id.
    Persisting this mapping avoids an unbounded participants lookup every run.
    """
    source = source.rstrip('/')
    identity = f'{source}:{member_id}'
    if state is not None and state['source'] != identity:
        raise ValueError('Watch state belongs to a different community or member')
    checked = now or datetime.now(UTC).isoformat()
    next_state = json.loads(json.dumps(state)) if state else {
        'version': 1, 'source': identity, 'targets': {}}
    events = []
    for spec in targets:
        sid, pid = int(spec['space_id']), int(spec['participant_id'])
        key = f'chat:{sid}'
        old = next_state['targets'].get(key)
        if old and old['participant_id'] != pid:
            raise ValueError('Participant mapping changed; use a new consumer state')
        space = client.get_space(sid) if not old else old['space']
        room = space.get('chat_room_uuid')
        if not room:
            raise ValueError('Target has no chat room')
        roots = _roots(client, room)
        current = {'space': {'chat_room_uuid': room, 'slug': space['slug'],
                             'name': space.get('name', key)},
                   'participant_id': pid, 'roots': {}, 'checked_at': checked}

        def public(message: dict, slug: str = space['slug']) -> dict:
            return {'id': message['id'], 'participant_id': message.get('chat_room_participant_id'),
                    'body_text': rich_text_message_text(message),
                    'url': f'{source}/c/{slug}#message_{message["id"]}'}

        for root in roots:
            rid = str(root['id'])
            previous = old['roots'].get(rid) if old else None
            snapshot = {'replies_count': root.get('replies_count', 0),
                        'last_reply_at': root.get('last_reply_at'),
                        'seen': previous.get('seen', []) if previous else []}
            current['roots'][rid] = snapshot
            if root.get('deleted_at'):
                continue
            if old and previous is None and root.get('chat_room_participant_id') != pid:
                events.append({'kind': 'new_root', 'target': key, **public(root)})
            dirty = old and (previous is None or any(
                snapshot[k] != previous[k] for k in ('replies_count', 'last_reply_at')))
            if not dirty or not snapshot['replies_count']:
                continue
            replies = _replies(client, room, root['id'])
            involved = (root.get('chat_room_participant_id') == pid or any(
                r.get('chat_room_participant_id') == pid for r in replies))
            seen = set(snapshot['seen'])
            for reply in replies:
                # Baseline never fetched old bodies: first dirty read uses the
                # previous scan's timestamp to exclude pre-existing replies.
                fresh = (str(reply['id']) not in seen and
                         (bool(seen) or _time(reply['created_at']) > _time(
                             (previous or {}).get('last_reply_at') or old['checked_at'])))
                if involved and fresh and not reply.get('deleted_at') and reply.get('chat_room_participant_id') != pid:
                    events.append({'kind': 'new_reply', 'target': key,
                                   'root_id': root['id'], **public(reply)})
            snapshot['seen'] = sorted(seen | {str(r['id']) for r in replies})
        next_state['targets'][key] = current
    return {'changed': bool(events), 'events': events, 'base_digest': digest(state),
            'next_state': next_state, 'checked_at': checked}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Message timestamp has no timezone')
    return parsed


def _replies(client: Any, room: str, root: int) -> list[dict]:
    found: dict[int, dict] = {}
    cursor = root
    used = set()
    for _ in range(100):
        page = client.fetch_chat_replies(room, root, next_per_page=200, cursor=cursor)
        records = _page(page, 'has_next_page')
        if type(page.get('has_previous_page')) is not bool:
            raise ValueError('Invalid thread pagination response')
        if not used and page['has_previous_page']:
            raise ValueError('Incomplete thread start; refusing checkpoint')
        before = len(found)
        found.update({r['id']: r for r in records if r.get('parent_message_id') == root})
        if not page['has_next_page']:
            return list(found.values())
        cursor = page.get('last_id')
        if type(cursor) is not int or cursor in used or len(found) == before:
            raise ValueError('Incomplete thread pagination: no progress')
        used.add(cursor)
    raise ValueError('Incomplete thread scan: page limit reached')
