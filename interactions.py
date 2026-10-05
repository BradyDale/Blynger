"""Private append-only interaction history for Reader and publication actions.

This module deliberately knows nothing about website generation.  Its records
live only in Reader's private ``reader.json`` file and are never protocol data.
"""
from __future__ import annotations

import copy
from urllib.parse import urlsplit


MARKERS = {
    ('saved', True): 'save', ('saved', False): 'unsave',
    ('liked', True): 'like', ('liked', False): 'unlike',
}
LABELS = {
    'save': 'saved',
    'unsave': 'removed from Saved',
    'like': 'liked',
    'unlike': 'removed Like',
    'reaction': 'reacted',
    'reaction_clear': 'cleared a response',
    'stub': 'responded with a Stub',
    'fork': 'forked',
    'quote': 'quoted',
}


def _same_origin(left, right):
    return str(left or '').rstrip('/') == str(right or '').rstrip('/')


def _target(item):
    doc = item.get('doc', {})
    remote_id = doc.get('id') or item.get('feed_identity') or doc.get('url') or item.get('key')
    return {
        'origin': item.get('origin', ''),
        'remote_id': str(remote_id),
        'version': doc.get('version'),
        'source_type': item.get('source_type', 'blyg'),
        'target_url': doc.get('page') or doc.get('url'),
    }


def append(state, entry):
    """Append one real action, suppressing publication-retry duplicates."""
    rows = state.setdefault('interactions', [])
    event_key = entry.get('event_key')
    if event_key and any(row.get('event_key') == event_key for row in rows):
        return False
    row = copy.deepcopy(entry)
    row['seq'] = int(state.get('interaction_seq', 0)) + 1
    state['interaction_seq'] = row['seq']
    rows.append(row)
    return True


def marker(state, item, field, value, at, label, backfilled=False):
    kind = MARKERS[(field, bool(value))]
    target = _target(item)
    return append(state, {
        'at': at, 'kind': kind, **target, 'label': label,
        'backfilled': bool(backfilled),
    })


def reaction(state, item, value, at, label, previous=None, backfilled=False):
    target = _target(item)
    return append(state, {
        'at': at, 'kind': 'reaction' if value else 'reaction_clear',
        'reaction': value, 'previous_reaction': previous, **target,
        'label': label, 'backfilled': bool(backfilled),
    })


def _refs(doc):
    return [ref for ref in doc.get('transclusions', [])
            if isinstance(ref, dict) and ref.get('origin') and ref.get('id')]


def _citation(doc, field):
    value = doc.get(field)
    return value if isinstance(value, dict) and value.get('origin') and value.get('id') else None


def publication_entries(previous, current, own_origin, label_for, backfilled=False):
    """Return interactions newly made by one successfully published version."""
    previous = previous or {}
    own = {'own_item_id': current.get('id'), 'own_version': current.get('version')}
    at = current.get('updated') or current.get('created')
    before_quotes = {(r['origin'].rstrip('/'), r['id']) for r in _refs(previous)}
    seen = set()
    out = []
    for ref in _refs(current):
        key = (ref['origin'].rstrip('/'), ref['id'])
        if _same_origin(ref['origin'], own_origin) or key in before_quotes or key in seen:
            continue
        seen.add(key)
        out.append({'at': at, 'kind': 'quote', 'origin': ref['origin'],
                    'remote_id': ref['id'], 'version': ref.get('version'), **own})
    stub = _citation(current, 'stub_of')
    old_stub = _citation(previous, 'stub_of')
    if stub and not _same_origin(stub['origin'], own_origin):
        old_key = (old_stub['origin'].rstrip('/'), old_stub['id']) if old_stub else None
        key = (stub['origin'].rstrip('/'), stub['id'])
        if key != old_key:
            out.append({'at': at, 'kind': 'stub', 'origin': stub['origin'],
                        'remote_id': stub['id'], 'version': stub.get('version'), **own})
    fork = _citation(current, 'forked_from')
    if current.get('version') == 1 and fork and not _same_origin(fork['origin'], own_origin):
        out.append({'at': at, 'kind': 'fork', 'origin': fork['origin'],
                    'remote_id': fork['id'], 'version': fork.get('version'), **own})
    for entry in out:
        entry.update(label_for(entry['origin'], entry['remote_id']))
        entry['backfilled'] = bool(backfilled)
        entry['event_key'] = '|'.join(map(str, (
            entry['kind'], entry['origin'].rstrip('/'), entry['remote_id'],
            entry.get('own_item_id'), entry.get('own_version'))))
    return out


def view(rows, query=''):
    query = query.strip().lower()
    result = []
    for row in rows:
        item = copy.deepcopy(row)
        item['action'] = LABELS.get(item.get('kind'), item.get('kind', 'activity'))
        try:
            item['host'] = urlsplit(item.get('origin', '')).netloc or item.get('origin', '')
        except ValueError:
            item['host'] = item.get('origin', '')
        haystack = ' '.join(str(item.get(key, '')) for key in ('label', 'host', 'action', 'origin'))
        if query and query not in haystack.lower():
            continue
        result.append(item)
    return sorted(result, key=lambda row: (row.get('at', ''), row.get('seq', 0)), reverse=True)
