"""Durable native-result reuse and bounded, evidence-adjudicated semantic repair."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json
import os
import re
from jsonschema import ValidationError, validate
from .corpus_screenplay_v1 import read, freeze, digest
from . import serial_story_contract_v1 as c
from .creative_workflow_roles import _response_model_matches
from src.platform_adapter.fanqie_book_corpus import atomic


class PauseRequested(Exception): pass


class RepairRequired(Exception):
    def __init__(self, name, candidate, review, findings):
        self.name, self.candidate, self.review, self.findings = name, candidate, review, findings


@contextmanager
def run_lock(run):
    if not run.is_dir(): raise ValueError('run_not_prepared')
    with (run/'EXECUTION.lock').open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('run_already_executing') from None
        try: yield
        finally:
            handle.seek(0)
            if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Runtime:
    def __init__(self, run, ledger, source):
        self.run, self.ledger, self.source = run, ledger, source
        path = run/'CHECKPOINT.json'
        self.data = read(path) if path.exists() else {'generation': 0, 'corrections': {}, 'requests': {}, 'phases': {}}
        # Separate output folders for batches, repairs, and process resumes.
        self.folder = run/'attempts'/f"{len(list((run/'attempts').glob('*'))) if (run/'attempts').exists() else 0:04}"
        self.folder.mkdir(parents=True)
        self.save()

    def save(self): atomic(self.run/'CHECKPOINT.json', self.data)

    def record(self, name, value):
        freeze(self.folder/name, value)
        index_path = self.run/'ARTIFACT_INDEX.json'
        index = read(index_path) if index_path.exists() else {}
        index[name] = {'path': str((self.folder/name).relative_to(self.run)), 'sha256': digest(value)}
        atomic(index_path, index)

    def native(self, key, name, role, prompt, payload, schema):
        request = {'name': name, 'role': role, 'prompt': prompt, 'payload': payload, 'schema': schema}
        entry = self.data['requests'].get(key)
        if entry:
            n = entry['number']; cp = self.run/f'CALL_{n:03}.json'; rp = self.run/f'RESPONSE_{n:03}.json'
            if entry['request_sha256'] != digest(request): raise ValueError('checkpoint_request_changed')
            if rp.exists():
                call = read(cp); response = read(rp)
                expected_messages = [
                    {'role':'system','content':prompt+(' 只调用submit_result提交结果。' if role=='writer' else ' 只返回符合schema的JSON。')},
                    {'role':'user','content':json.dumps({**payload,'output_schema':schema},ensure_ascii=False,separators=(',',':'))}]
                if call['messages'] != expected_messages or call['role'] != role or call['schema'] != schema:
                    raise ValueError('cached_native_request_mismatch')
                if entry.get('response_sha256') and entry['response_sha256'] != digest(response):
                    raise ValueError('cached_native_response_changed')
                native = response['native']; choice = native['choices'][0]; usage = native['usage']
                if len(native['choices']) != 1 or not native.get('id') or usage['total_tokens'] != usage['prompt_tokens']+usage['completion_tokens']:
                    raise ValueError('cached_native_invalid')
                expected_model = self.ledger.plan['routes'][role]['model']
                if not (native['model']==expected_model if role=='writer' else _response_model_matches(role,expected_model,native['model'])):
                    raise ValueError('cached_native_model_mismatch')
                if choice['finish_reason'] == 'length': raise ValueError('native_truncated_no_replay')
                message = choice['message']
                if role == 'writer':
                    calls = message.get('tool_calls', [])
                    if choice['finish_reason'] != 'tool_calls' or len(calls)!=1 or calls[0]['function']['name']!='submit_result':
                        raise ValueError('cached_native_submission_invalid')
                    text = calls[0]['function']['arguments']
                else:
                    if choice['finish_reason'] != 'stop' or message.get('tool_calls'): raise ValueError('cached_final_invalid')
                    text = message.get('content')
                try: value = json.loads(text)
                except (ValueError, TypeError): value = {'invalid_native_json': text}
                entry['response_sha256'] = digest(response); self.save()
                return value
            if cp.exists(): raise ValueError('cached_request_without_response_no_replay')
            if n != self.ledger.state['calls_started']+1: raise ValueError('checkpoint_call_sequence_changed')
        else:
            n = self.ledger.state['calls_started']+1
            self.data['requests'][key] = {'number': n, 'request_sha256': digest(request)}
            self.save()  # Before any HTTP dispatch.
        actual_name = name+f'_G{self.data["generation"]}_{n:04}'
        value = self.ledger.call(actual_name, role, prompt, payload, schema)
        self.data['requests'][key]['response_sha256'] = digest(read(self.run/f'RESPONSE_{n:03}.json'))
        self.save()
        return value

    def phase(self, name, payload, schema, validator, prompt, role):
        if (self.run/'PAUSE_REQUESTED.json').exists(): raise PauseRequested()
        self.data['phases'][name] = {'payload': payload, 'role': role}
        payload = deepcopy(payload)
        if name in self.data['corrections']:
            payload['required_corrections'] = self.data['corrections'][name]
        self.save()
        for attempt in range(2):
            actual = name+(f'_FORMAT_{attempt}' if attempt else '')
            key = digest({'name': actual, 'role': role, 'prompt': prompt, 'payload': payload, 'schema': schema})
            value = self.native(key, actual, role, prompt, payload, schema)
            try: return validator(value)
            except (ValueError, ValidationError, TypeError, KeyError) as exc:
                self.record(name+f'_INVALID_{attempt}.json', {'reason': str(exc)[:2500], 'value_sha256': digest(value)})
                if attempt: raise
                payload = {**payload, 'invalid_output': value, 'validation_error': str(exc)[:2500]}

    def review_failure(self, name, candidate, source, inputs, review, phase):
        if review['decision']=='uncertain': raise ValueError('review_evidence_insufficient')
        schema = c.obj(candidate_sha256=c.TEXT, review_sha256=c.TEXT,
                       findings=c.arr(c.obj(index={'type':'integer','minimum':0},
                         verdict={'enum':['upheld','rejected','uncertain']}, reason=c.STR, source_ids=c.IDS),1))
        def valid(raw):
            validate(raw,schema)
            if raw['candidate_sha256']!=digest(candidate) or raw['review_sha256']!=digest(review): raise ValueError('adjudication_binding_changed')
            if sorted(x['index'] for x in raw['findings'])!=list(range(len(review['issues']))): raise ValueError('adjudication_issue_coverage')
            for x in raw['findings']: c.source_refs(x['source_ids'],source)
            return raw
        findings = phase('ADJUDICATE_'+name, {'candidate':candidate,'candidate_sha256':digest(candidate),
            'review':review,'review_sha256':digest(review),'inputs':inputs},schema,valid,
            '独立裁决每条审核意见。核对字段、原文、动作、时间线，不将未交代当矛盾；不得改稿。', 'writer')
        self.record(name+'_ADJUDICATED.json', findings)
        if any(x['verdict']=='uncertain' for x in findings['findings']): raise ValueError('adjudication_evidence_insufficient')
        upheld = [review['issues'][x['index']] for x in findings['findings'] if x['verdict']=='upheld']
        if not upheld: raise ValueError('review_rejected_requires_independent_resolution')
        raise RepairRequired(name,candidate,review,{'adjudication':findings,'upheld':upheld})

    def invalidate(self, failure):
        if self.data['generation'] >= 2: raise ValueError('semantic_repair_limit_reached')
        targets = set(); phases = self.data['phases']
        for issue in failure.findings['upheld']:
            owner = issue['owner']
            chapters = {int(x.split('-')[0][2:]) for x in issue['source_ids']}
            if owner=='materials': targets.update(f'MATERIAL_{ch:04}' for ch in chapters)
            elif owner=='bible': targets.update(n for n,v in phases.items() if re.fullmatch(r'BIBLE_\d+_\d+',n) and chapters & set(v['payload']['required_chapters']))
            elif owner=='outline': targets.add('OUTLINE')
            else:
                found = re.search(r'(?:EPISODE_REVIEW|FINAL_CONTENT|FINAL_TIMING)_(\d+)',failure.name)
                if not found: raise ValueError('review_owner_unrelated_to_stage')
                prefix = 'EPISODE_'+found[1]
                if owner=='episode': targets.add(prefix+'_STORY')
                else:
                    match = re.match(r'/script/scenes/(\d+)(?:/|$)',issue['path'])
                    targets.update([prefix+f'_SCENE_{int(match[1]):03}'] if match else [n for n in phases if n.startswith(prefix+'_SCENE_')])
        if not targets or not targets<=set(phases): raise ValueError('repair_target_missing')
        correction = {'candidate_sha256':digest(failure.candidate),'review':failure.review,
                      'adjudication':failure.findings['adjudication'],'issues':failure.findings['upheld']}
        for name in targets: self.data['corrections'][name] = correction
        self.record('INVALIDATION.json',{'targets':sorted(targets),'generation':self.data['generation'],
                    'dependency_policy':'reuse only identical phase input; changed output invalidates downstream request keys'})
        # Hide superseded derived artifacts immediately, while retaining all files.
        index = read(self.run/'ARTIFACT_INDEX.json')
        atomic(self.run/'ARTIFACT_INDEX.json', {'INVALIDATION.json':index['INVALIDATION.json']})
        self.data['generation'] += 1; self.save()
        self.folder = self.run/'attempts'/f'{len(list((self.run/"attempts").glob("*"))):04}'
        self.folder.mkdir()
