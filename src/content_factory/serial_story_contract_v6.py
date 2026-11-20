"""Scoped story dependencies; evidence matching is not semantic acceptance."""
from copy import deepcopy
from jsonschema import validate
from .serial_story_contract_v5 import *
from . import serial_story_contract_v1 as old

VERSION = 'serial_story_contract/v6'
READING = obj(chapter_indices=INTS, analysis={'type': 'string', 'minLength': 1},
              open_questions=arr(STR))
# Open questions are retained outside the usable bible. They are never silently
# transformed into facts or included in the writer's usable foundation.
FOUNDATION = obj(bible=BIBLE, questions=arr(obj(id=TEXT, description=STR, source_ids=IDS)))
RESOLUTION = obj(answers=arr(obj(question_id=TEXT, status={'enum': ['answered', 'unknown']},
                              claim={'anyOf': [CLAIM, {'type': 'null'}]}, reason=STR), 1))
BRIEF = deepcopy(old.BRIEF)
BRIEF['properties'].update(required_claim_ids=IDS, required_question_ids=arr(TEXT))
BRIEF['required'] += ['required_claim_ids', 'required_question_ids']
DRAFT_PLAN = deepcopy(old.DRAFT_PLAN)
DRAFT_PLAN['properties']['scenes']['items'] = BRIEF


def reading_groups(source, byte_limit=24000):
    """Preserve complete chapters and order; only split when capacity requires."""
    groups, group, size = [], [], 0
    for ch in source['chapters']:
        n = len(ch['text'].encode('utf-8'))
        if n > byte_limit:
            raise ValueError('single_complete_chapter_exceeds_reading_capacity')
        if group and size+n > byte_limit:
            groups.append(group); group, size = [], 0
        group.append(deepcopy(ch)); size += n
    if group:
        groups.append(group)
    return groups


def reading_valid(raw, chapters):
    validate(raw, READING)
    if raw['chapter_indices'] != [c['index'] for c in chapters]:
        raise ValueError('reading_chapter_coverage')
    return raw


def foundation_valid(raw, source, previous=None):
    validate(raw, FOUNDATION)
    bible_valid(raw['bible'], source, [ch['index'] for ch in source['chapters']])
    if raw['bible']['unresolved']:
        raise ValueError('put_unresolved_in_questions_not_usable_bible')
    unique(raw['questions'], 'id')
    if {q['id'] for q in raw['questions']} & {q['id'] for q in raw['bible']['claims']}:
        raise ValueError('question_claim_id_collision')
    for q in raw['questions']:
        source_refs(q['source_ids'], source)
    # Existing identities cannot be relabelled between episodes. Different
    # evidence lists are allowed, but previously named aliases cannot migrate.
    for kind in ('characters', 'places'):
        existing = {r['id']: r for r in (previous or {}).get(kind, [])}
        by_name = {n: r['id'] for r in existing.values() for n in [r['name']]+r.get('aliases', [])}
        for row in raw['bible'][kind]:
            if row['id'] in existing and row['name'] != existing[row['id']]['name']:
                raise ValueError('stable_entity_identity_changed')
            for name in [row['name']]+row.get('aliases', []):
                if name in by_name and by_name[name] != row['id']:
                    raise ValueError('stable_entity_id_changed')
    return raw


def plain_brief(scene):
    return {k: deepcopy(scene[k]) for k in old.BRIEF['properties']}


def plain_draft(raw):
    return {**deepcopy(raw), 'scenes': [plain_brief(s) for s in raw['scenes']]}


def draft_valid(raw, source, foundation, episode):
    validate(raw, DRAFT_PLAN)
    old.draft_valid(plain_draft(raw), source, foundation['bible'], episode)
    claims = {x['id'] for x in foundation['bible']['claims']}
    questions = {x['id'] for x in foundation['questions']}
    for scene in raw['scenes']:
        if not set(scene['required_claim_ids']) <= claims or not set(scene['required_question_ids']) <= questions:
            raise ValueError('unknown_scene_dependency')
        if len(set(scene['required_question_ids'])) != len(scene['required_question_ids']):
            raise ValueError('duplicate_question_dependency')
    return raw


def scene_packet(scene, foundation):
    """Remove unrelated prose/facts/questions before staging and scope review."""
    required = set(scene['required_claim_ids'])
    return {'scene': plain_brief(scene),
            'claims': [deepcopy(x) for x in foundation['bible']['claims'] if x['id'] in required],
            'questions': [deepcopy(x) for x in foundation['questions'] if x['id'] in scene['required_question_ids']]}


def resolution_valid(raw, questions, source):
    validate(raw, RESOLUTION)
    if unique(raw['answers'], 'question_id') != {q['id'] for q in questions}:
        raise ValueError('resolution_question_coverage')
    for answer in raw['answers']:
        if answer['status'] == 'answered':
            if answer['claim'] is None:
                raise ValueError('resolved_question_requires_source_claim')
            claims_valid([answer['claim']], source)
        elif answer['claim'] is not None:
            raise ValueError('unknown_answer_cannot_be_fact')
    return raw


def apply_resolution(packet, resolution):
    result = deepcopy(packet)
    resolved = {a['question_id'] for a in resolution['answers'] if a['status'] == 'answered'}
    result['questions'] = [q for q in result['questions'] if q['id'] not in resolved]
    result['claims'] += [deepcopy(a['claim']) for a in resolution['answers'] if a['status'] == 'answered']
    unique(result['claims'], 'id')
    return result


def review_schema(name):
    if name.startswith('SCOPE_REVIEW_'):
        schema = deepcopy(REVIEW)
        schema['properties']['issues']['items']['properties']['owner'] = {'enum': ['bible', 'episode']}
        return schema
    schema = old_review_schema(name)
    if name.startswith(('EPISODE_REVIEW_', 'FINAL_CONTENT_', 'FINAL_TIMING_')):
        schema['properties']['issues']['items']['properties']['owner']['enum'] = ['bible', 'outline', 'episode', 'staging']
    return schema


from .serial_story_contract_v5 import review_schema as old_review_schema


def review_valid_for_stage(raw, candidate, source, name):
    validate(raw, review_schema(name))
    return review_valid(raw, candidate, source)


def strict_scene_valid(raw, brief, source, bible, episode, previous_state):
    bound = old.scene_valid(raw, plain_brief(brief), source, bible, episode, previous_state)
    places = {p['id'] for p in bible['places']}
    for frame in bound['continuity']:
        for state in frame['before']+frame['after']:
            if state['kind'] == 'location' and state['value'] not in places:
                raise ValueError('location_value_must_be_place_id')
    return bound
