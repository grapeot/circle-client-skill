from copy import deepcopy
from pathlib import Path

import pytest

from circle_client_skill.watch import atomic_write, commit, load_state, scan


class Client:
    def __init__(self):
        self.roots = [msg(10, None, 2)]
        self.replies = [msg(11, 10, 1)]
        self.more = False
        self.calls = 0

    def get_space(self, sid):
        return {'name': 'Support', 'slug': 'support', 'chat_room_uuid': 'fake-room'}

    def list_chat_messages(self, room, **kw):
        self.calls += 1
        return {'records': deepcopy(self.roots), 'has_previous_page': self.more, 'first_id': 10}

    def fetch_chat_replies(self, room, parent, **kw):
        return {'records': deepcopy(self.replies), 'has_next_page': False, 'has_previous_page': False}


def msg(mid, parent, author):
    return {'id': mid, 'parent_message_id': parent, 'chat_room_participant_id': author,
            'replies_count': 1 if parent is None else 0,
            'last_reply_at': '2026-01-01T00:00:00Z',
            'created_at': '2026-01-01T00:00:00Z', 'body': 'Synthetic message'}


def run(client, state=None):
    return scan(client, source='https://example.test', member_id=99,
                targets=[{'space_id': 9000000, 'participant_id': 1}],
                state=state, now='2026-01-02T00:00:00Z')


def changed():
    c = Client()
    state = run(c)['next_state']
    c.roots[0]['replies_count'] = 2
    reply = msg(12, 10, 2)
    reply['created_at'] = '2026-01-02T00:01:00Z'
    c.replies.append(reply)
    return c, state


def test_baseline_is_silent():
    assert not run(Client())['changed']


def test_new_root():
    c = Client()
    state = run(c)['next_state']
    c.roots.append(msg(20, None, 2))
    assert run(c, state)['events'][0]['kind'] == 'new_root'


def test_new_reply_and_historical_participation_without_preview():
    c, state = changed()
    events = run(c, state)['events']
    assert [e['id'] for e in events] == [12]


def test_same_count_new_timestamp():
    c, state = changed()
    c.roots[0]['replies_count'] = 1
    c.roots[0]['last_reply_at'] = '2026-01-02T00:01:00Z'
    assert run(c, state)['events'][0]['id'] == 12


def test_self_reply_silent():
    c, state = changed()
    c.replies[-1]['chat_room_participant_id'] = 1
    assert not run(c, state)['changed']


def test_other_threads_silent():
    c, state = changed()
    c.replies[0]['chat_room_participant_id'] = 3
    assert not run(c, state)['changed']


def test_repeat_without_commit_keeps_events():
    c, state = changed()
    assert run(c, state)['events'] == run(c, state)['events']


def test_commit_and_stale_commit(tmp_path):
    path = tmp_path / 'state.json'
    c, state = changed()
    atomic_write(path, state)
    result = run(c, state)
    commit(path, result)
    assert not run(c, load_state(path))['changed']
    with pytest.raises(ValueError, match='changed since scan'):
        commit(path, result)


def test_incomplete_roots_fail_closed():
    c = Client()
    c.more = True
    with pytest.raises(ValueError, match='pagination did not progress'):
        run(c)


def test_incomplete_replies_fail_closed():
    c, state = changed()
    c.fetch_chat_replies = lambda *a, **k: {'records': c.replies, 'has_next_page': True}
    with pytest.raises(ValueError, match='thread'):
        run(c, state)


def test_corruption_not_baseline(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text('{}')
    with pytest.raises(ValueError, match='Invalid watch state'):
        load_state(path)


def test_deleted_root_silent():
    c = Client()
    state = run(c)['next_state']
    c.roots = []
    assert not run(c, state)['changed']


def test_source_binding():
    state = run(Client())['next_state']
    state['source'] = 'another-community'
    with pytest.raises(ValueError, match='different community'):
        run(Client(), state)


def test_atomic_private_permissions(tmp_path):
    path = Path(tmp_path) / 'state.json'
    atomic_write(path, run(Client())['next_state'])
    assert path.stat().st_mode & 0o777 == 0o600


def test_root_pagination_deduplicates_anchor():
    c = Client()
    pages = iter([
        {'records': [msg(20, None, 2)], 'has_previous_page': True, 'first_id': 20},
        {'records': [msg(10, None, 2), msg(20, None, 2)], 'has_previous_page': False},
    ])
    c.list_chat_messages = lambda *a, **kw: next(pages)
    assert len(run(c)['next_state']['targets']['chat:9000000']['roots']) == 2


def test_reply_pagination_collects_all_pages():
    c, state = changed()
    pages = iter([
        {'records': [c.replies[0]], 'has_next_page': True, 'has_previous_page': False, 'last_id': 11},
        {'records': c.replies, 'has_next_page': False, 'has_previous_page': True},
    ])
    c.fetch_chat_replies = lambda *a, **kw: next(pages)
    assert run(c, state)['events'][0]['id'] == 12
