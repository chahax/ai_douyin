"""Source-bound serial planning, variable-duration episodes and deterministic state.

Structural checks are not semantic acceptance. No network or media operations.
"""
from copy import deepcopy
import math
from jsonschema import validate
from .corpus_screenplay_v1 import digest
from .story_first_contract_v5 import paragraphs, obj, arr, TEXT

VERSION = 'serial_story_contract/v1'
STR = {'type': 'string', 'minLength': 1, 'maxLength': 2000}
IDS = {'type': 'array', 'items': TEXT, 'minItems': 1, 'uniqueItems': True}
INTS = {'type': 'array', 'items': {'type': 'integer', 'minimum': 1}, 'minItems': 1, 'uniqueItems': True}
NUM = {'type': 'number', 'minimum': 0}
EVIDENCE = obj(source_id=TEXT, quote=STR)
CLAIM = obj(id=TEXT, category={'enum': ['world', 'character', 'environment', 'event']},
            statement=STR, evidence=arr(EVIDENCE, 1))
MATERIAL = obj(chapter_index={'type': 'integer'}, claims=arr(CLAIM, 1),
               coverage=arr(obj(source_id=TEXT, claim_ids=arr(TEXT),
                                omission_reason={'type': 'string'}), 1))
BIBLE = obj(chapter_indices=INTS, claims=arr(CLAIM, 1),
            characters=arr(obj(id=TEXT, name=TEXT, aliases=arr(TEXT), source_ids=IDS), 1),
            places=arr(obj(id=TEXT, name=TEXT, source_ids=IDS), 1),
            visual_style=STR, creative_additions=arr(STR), unresolved=arr(STR))
EPISODE = obj(id=TEXT, title=TEXT, chapters=INTS, context_chapters=arr({'type': 'integer', 'minimum': 1}),
              information=STR, conflict=STR, resolution=STR, hook=STR, continuation=STR,
              target_seconds={'type': 'integer', 'minimum': 10, 'maximum': 3600},
              depends_on=arr(TEXT), source_ids=IDS)
OUTLINE = obj(title=TEXT, arc=STR, scope_is_complete_book={'type': 'boolean'},
              episodes=arr(EPISODE, 1),
              omitted_chapters=arr(obj(chapter_index={'type': 'integer'}, reason=STR)))
SLOT = obj(id=TEXT, timeline=TEXT, kind={'enum': ['location', 'prop', 'knowledge']},
           subject=TEXT, item=TEXT, value=STR, source_ids=IDS)
ACTION = obj(id=TEXT, people=IDS, description=STR, start=NUM, end=NUM, source_ids=IDS)
CHANGE = obj(state_id=TEXT, before=STR, after=STR, action_id=TEXT, source_ids=IDS)
AUDIO = obj(id=TEXT, speaker=TEXT, mode={'enum': ['onscreen', 'inner_voice', 'voiceover']},
            text=STR, start=NUM, end=NUM)
SCENE = obj(id=TEXT, timeline=TEXT, story_time=STR, place_id=TEXT, cast=IDS,
            seconds={'type': 'number', 'exclusiveMinimum': 0, 'maximum': 3600},
            information=STR, plot=STR, performance=STR, camera=STR,
            source_ids=IDS, introductions=arr(SLOT), actions=arr(ACTION, 1),
            changes=arr(CHANGE), audio=arr(AUDIO))
SCRIPT = obj(episode_id=TEXT, title=TEXT, scenes=arr(SCENE, 1), creative_additions=arr(STR))
BRIEF = obj(**{k: deepcopy(SCENE['properties'][k]) for k in
               ('id', 'timeline', 'story_time', 'place_id', 'cast', 'seconds', 'information', 'plot', 'source_ids', 'audio')})
DRAFT_PLAN = obj(episode_id=TEXT, title=TEXT, scenes=arr(BRIEF, 1), creative_additions=arr(STR))
REVIEW = obj(candidate_sha256=TEXT, decision={'enum': ['pass', 'revise', 'uncertain']},
             issues=arr(obj(owner={'enum': ['materials', 'bible', 'outline', 'episode', 'staging']},
                            path=TEXT, reason=STR, source_ids=IDS)), rationale=STR)


def unique(rows, key):
    values = [r[key] for r in rows]
    if len(values) != len(set(values)):
        raise ValueError('duplicate_' + key)
    return set(values)


def source_refs(ids, source):
    catalog = {p['id']: p for p in paragraphs(source)}
    if not ids or not set(ids) <= set(catalog):
        raise ValueError('unknown_or_empty_source_reference')
    return catalog


def claims_valid(claims, source):
    unique(claims, 'id')
    for claim in claims:
        for ev in claim['evidence']:
            catalog = source_refs([ev['source_id']], source)
            if ev['quote'] not in catalog[ev['source_id']]['text']:
                raise ValueError('quote_not_in_source')


def material_valid(raw, chapter):
    validate(raw, MATERIAL)
    source = {'chapters': [chapter]}
    if raw['chapter_index'] != chapter['index']:
        raise ValueError('wrong_material_chapter')
    claims_valid(raw['claims'], source)
    coverage = unique(raw['coverage'], 'source_id')
    if coverage != {p['id'] for p in paragraphs(source)}:
        raise ValueError('paragraph_coverage_incomplete')
    facts = {c['id']: c for c in raw['claims']}
    for row in raw['coverage']:
        if row['claim_ids']:
            if row['omission_reason'] or not set(row['claim_ids']) <= set(facts):
                raise ValueError('coverage_claim_mismatch')
            if any(row['source_id'] not in {e['source_id'] for e in facts[c]['evidence']}
                   for c in row['claim_ids']):
                raise ValueError('coverage_without_evidence')
        elif not row['omission_reason'].strip():
            raise ValueError('omission_requires_reason')
    return raw


def bible_valid(raw, source, expected_indices):
    validate(raw, BIBLE)
    if sorted(raw['chapter_indices']) != sorted(expected_indices):
        raise ValueError('bible_chapter_coverage')
    subset = {'chapters': [c for c in source['chapters'] if c['index'] in expected_indices]}
    claims_valid(raw['claims'], subset)
    for kind in ('characters', 'places'):
        unique(raw[kind], 'id')
        names = set()
        for row in raw[kind]:
            catalog = source_refs(row['source_ids'], subset)
            if not any(row['name'] in catalog[x]['text'] for x in row['source_ids']):
                raise ValueError('entity_name_without_source')
            for name in [row['name']] + row.get('aliases', []):
                if name in names:
                    raise ValueError('entity_alias_collision')
                names.add(name)
    return raw


def outline_valid(raw, source):
    validate(raw, OUTLINE)
    unique(raw['episodes'], 'id')
    if raw['scope_is_complete_book'] and not source['manifest'].get('full_book_confirmed', False):
        raise ValueError('unread_ending_claimed')
    available = {c['index'] for c in source['chapters']}
    seen, used = set(), set()
    for episode in raw['episodes']:
        if not set(episode['chapters'] + episode['context_chapters']) <= available:
            raise ValueError('episode_unread_chapter')
        if not set(episode['depends_on']) <= seen:
            raise ValueError('episode_forward_dependency')
        if seen and raw['episodes'][len(seen)-1]['id'] not in episode['depends_on']:
            raise ValueError('previous_episode_dependency_missing')
        catalog = source_refs(episode['source_ids'], source)
        if any(catalog[x]['chapter'] not in episode['chapters'] for x in episode['source_ids']):
            raise ValueError('episode_evidence_outside_chapters')
        seen.add(episode['id']); used.update(episode['chapters'])
    omitted = unique(raw['omitted_chapters'], 'chapter_index')
    if omitted & used or used | omitted != available:
        raise ValueError('outline_source_disposition_incomplete')
    return raw


def select_source(source, episode):
    indices = set(episode['chapters'] + episode['context_chapters'])
    if not indices <= {c['index'] for c in source['chapters']}:
        raise ValueError('episode_unread_chapter')
    return {'manifest': deepcopy(source['manifest']),
            'chapters': [deepcopy(c) for c in source['chapters'] if c['index'] in indices]}


def episode_bible(bible, source):
    """Keep stable identities, but never send unrelated chapter quotes to finals."""
    available = {p['id'] for p in paragraphs(source)}
    result = deepcopy(bible)
    result['chapter_indices'] = [ch['index'] for ch in source['chapters']]
    result['claims'] = [x for x in result['claims'] if
                        all(e['source_id'] in available for e in x['evidence'])]
    for kind in ('characters', 'places'):
        result[kind] = [x for x in result[kind] if set(x['source_ids']) & available]
        for x in result[kind]:
            x['source_ids'] = [ref for ref in x['source_ids'] if ref in available]
    return result


def state_key(slot):
    return tuple(slot[k] for k in ('timeline', 'kind', 'subject', 'item'))


def draft_valid(raw, source, bible, episode):
    validate(raw, DRAFT_PLAN)
    if raw['episode_id'] != episode['id']:
        raise ValueError('episode_identity_changed')
    unique(raw['scenes'], 'id')
    if sum(s['seconds'] for s in raw['scenes']) > episode['target_seconds']:
        raise ValueError('episode_over_budget')
    for scene in raw['scenes']:
        source_refs(scene['source_ids'], source)
        if not set(scene['cast']) <= {p['id'] for p in bible['characters']} or scene['place_id'] not in {p['id'] for p in bible['places']}:
            raise ValueError('scene_unknown_entity')
        for audio in scene['audio']:
            if not 0 <= audio['start'] < audio['end'] <= scene['seconds']:
                raise ValueError('interval_out_of_scene')
            if sum(ch.isalnum() for ch in audio['text']) > (audio['end']-audio['start'])*4:
                raise ValueError('dialogue_over_budget')
    return raw


def scene_valid(raw, brief, source, bible, episode, previous_state):
    validate(raw, SCENE)
    if any(raw[key] != brief[key] for key in BRIEF['properties']):
        raise ValueError('staging_changed_fixed_story')
    candidate = {'episode_id': episode['id'], 'title': episode['title'],
                 'creative_additions': [], 'scenes': [raw]}
    return script_valid(candidate, source, bible, episode, previous_state)


def script_valid(raw, source, bible, episode, previous_state=None):
    validate(raw, SCRIPT)
    if raw['episode_id'] != episode['id']:
        raise ValueError('episode_identity_changed')
    unique(raw['scenes'], 'id')
    if sum(s['seconds'] for s in raw['scenes']) > episode['target_seconds']:
        raise ValueError('episode_over_budget')
    people = {c['id'] for c in bible['characters']}
    places = {p['id'] for p in bible['places']}
    state = deepcopy(previous_state or [])
    unique(state, 'id')
    frames = []
    for scene in raw['scenes']:
        source_refs(scene['source_ids'], source)
        if not set(scene['cast']) <= people or scene['place_id'] not in places:
            raise ValueError('scene_unknown_entity')
        for slot in scene['introductions']:
            source_refs(slot['source_ids'], source)
            if slot['subject'] not in people or slot['timeline'] != scene['timeline']:
                raise ValueError('state_timeline_or_subject_mismatch')
            if any(s['id'] == slot['id'] or state_key(s) == state_key(slot) for s in state):
                raise ValueError('state_reintroduced_or_overwritten')
            state.append(deepcopy(slot))
        before = deepcopy(state)
        actions = {a['id']: a for a in scene['actions']}
        unique(scene['actions'], 'id'); unique(scene['audio'], 'id')
        for action in scene['actions']:
            source_refs(action['source_ids'], source)
            if not set(action['people']) <= set(scene['cast']):
                raise ValueError('action_person_not_present')
        for row in scene['actions'] + scene['audio']:
            if not all(math.isfinite(row[k]) for k in ('start', 'end')) or not 0 <= row['start'] < row['end'] <= scene['seconds']:
                raise ValueError('interval_out_of_scene')
        for audio in scene['audio']:
            if audio['speaker'] not in people or (audio['mode'] == 'onscreen' and audio['speaker'] not in scene['cast']):
                raise ValueError('audio_unknown_or_absent_speaker')
            if sum(c.isalnum() for c in audio['text']) > (audio['end']-audio['start'])*4:
                raise ValueError('dialogue_over_budget')
        audio = sorted(scene['audio'], key=lambda a: a['start'])
        if any(b['start'] < a['end'] for a, b in zip(audio, audio[1:])):
            raise ValueError('audio_overlap')
        if any(c['action_id'] not in actions for c in scene['changes']):
            raise ValueError('change_without_action')
        changes = sorted(scene['changes'], key=lambda c: (actions[c['action_id']]['end'], actions[c['action_id']]['start']))
        for change in changes:
            source_refs(change['source_ids'], source)
            slots = [s for s in state if s['id'] == change['state_id']]
            if not slots or slots[0]['timeline'] != scene['timeline']:
                raise ValueError('change_wrong_timeline_or_slot')
            slot = slots[0]
            if slot['kind'] in ('knowledge', 'location') and slot['subject'] not in actions[change['action_id']]['people']:
                raise ValueError('state_subject_not_in_action')
            if change['before'] != slot['value'] or change['after'] == change['before']:
                raise ValueError('state_transition_before_mismatch')
            slot['value'] = change['after']
        for person in scene['cast']:
            locations = [s for s in before if s['timeline'] == scene['timeline'] and s['kind'] == 'location' and s['subject'] == person]
            if not locations:
                raise ValueError('cast_location_missing')
            reachable = {s['value'] for s in locations}
            reachable.update(c['after'] for c in changes if any(s['id'] == c['state_id'] for s in locations))
            if scene['place_id'] not in reachable:
                raise ValueError('cast_teleport_without_action')
        frames.append({'scene_id': scene['id'], 'timeline': scene['timeline'],
                       'before': before, 'after': deepcopy(state)})
    return {'script': deepcopy(raw), 'continuity': frames, 'end_state': state,
            'previous_state_sha256': digest(previous_state or [])}


def review_valid(raw, candidate, source):
    validate(raw, REVIEW)
    if raw['candidate_sha256'] != digest(candidate):
        raise ValueError('review_candidate_changed')
    if (raw['decision'] == 'pass' and raw['issues']) or (raw['decision'] == 'revise' and not raw['issues']):
        raise ValueError('review_decision_issue_mismatch')
    for issue in raw['issues']:
        source_refs(issue['source_ids'], source)
        node = candidate
        # JSON Pointer, root is '/'; no model-invented alternate path syntax.
        if not issue['path'].startswith('/'):
            raise ValueError('review_pointer_required')
        if issue['path'] != '/':
            try:
                for part in issue['path'][1:].split('/'):
                    key = part.replace('~1', '/').replace('~0', '~')
                    node = node[int(key)] if isinstance(node, list) else node[key]
            except (KeyError, ValueError, IndexError, TypeError):
                raise ValueError('review_pointer_missing') from None
    return raw


def split_shots(bound, max_seconds):
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError('invalid_shot_duration')
    shots = []
    for scene, frame in zip(bound['script']['scenes'], bound['continuity']):
        occupied = scene['actions'] + scene['audio']
        cursor = 0
        state = deepcopy(frame['before'])
        actions = {a['id']: a for a in scene['actions']}
        changes = sorted(scene['changes'], key=lambda c: actions[c['action_id']]['end'])
        while cursor < scene['seconds']:
            limit = min(cursor + max_seconds, scene['seconds'])
            boundaries = {limit} | {r[k] for r in occupied for k in ('start', 'end') if cursor < r[k] <= limit}
            safe = [b for b in boundaries if not any(r['start'] < b < r['end'] for r in occupied)]
            if not safe:
                raise ValueError('continuous_action_or_audio_exceeds_model_duration')
            end = max(safe); before = deepcopy(state)
            for change in changes:
                if cursor < actions[change['action_id']]['end'] <= end:
                    next(s for s in state if s['id'] == change['state_id'])['value'] = change['after']
            shots.append({'id': f"{bound['script']['episode_id']}-SHOT{len(shots)+1:04}",
                          'scene_id': scene['id'], 'start': cursor, 'end': end,
                          'state_before': before, 'state_after': deepcopy(state),
                          'audio_ids': [r['id'] for r in scene['audio'] if cursor <= r['start'] < end],
                          'action_ids': [r['id'] for r in scene['actions'] if cursor <= r['start'] < end]})
            cursor = end
    return shots


def descendants(outline, episode_id):
    affected = {episode_id}
    if episode_id not in {e['id'] for e in outline['episodes']}:
        raise ValueError('unknown_episode')
    for episode in outline['episodes']:
        if set(episode['depends_on']) & affected:
            affected.add(episode['id'])
    return [e['id'] for e in outline['episodes'] if e['id'] in affected]
