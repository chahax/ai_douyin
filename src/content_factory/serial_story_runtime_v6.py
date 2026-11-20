"""Reuse v5 receipts/locks; route scoped repairs to their episode foundation."""
import re
from .serial_story_runtime_v5 import Runtime as PreviousRuntime, RepairRequired, PauseRequested, run_lock
from .corpus_screenplay_v1 import digest, read
from src.platform_adapter.fanqie_book_corpus import atomic


class Runtime(PreviousRuntime):
    def invalidate(self, failure):
        if self.data['generation'] >= 2:
            raise ValueError('semantic_repair_limit_reached')
        match = re.search(r'(?:SCOPE_REVIEW|EPISODE_REVIEW|FINAL_CONTENT|FINAL_TIMING)_(\d+)', failure.name)
        if not match:
            return super().invalidate(failure)
        prefix = 'EPISODE_'+match[1]
        targets = set()
        for issue in failure.findings['upheld']:
            if issue['owner'] == 'bible':
                path = re.match(r'/claims/(\d+)(?:/|$)', issue['path'])
                scope = re.fullmatch(r'SCOPE_REVIEW_(\d+)_(\d+)', failure.name)
                facts = failure.candidate.get('claims', [])
                if scope and path and int(path[1]) < len(facts) and facts[int(path[1])]['id'].endswith('_RESOLVED'):
                    targets.add(f'LOOKUP_{scope[1]}_{scope[2]}')
                else:
                    targets.add(prefix+'_FOUNDATION')
            elif issue['owner'] == 'episode':
                targets.add(prefix+'_STORY')
            elif issue['owner'] == 'outline':
                targets.add('OUTLINE')
            elif issue['owner'] == 'staging':
                scene = re.match(r'/script/scenes/(\d+)(?:/|$)', issue['path'])
                targets.update([prefix+f'_SCENE_{int(scene[1]):03}'] if scene else
                               [n for n in self.data['phases'] if n.startswith(prefix+'_SCENE_')])
            else:
                raise ValueError('unrelated_review_owner')
        if not targets or not targets <= set(self.data['phases']):
            raise ValueError('repair_target_missing')
        correction = {'candidate_sha256': digest(failure.candidate), 'review': failure.review,
                      'adjudication': failure.findings['adjudication'], 'issues': failure.findings['upheld']}
        for name in targets:
            self.data['corrections'][name] = correction
        self.record('INVALIDATION.json', {'targets': sorted(targets), 'generation': self.data['generation'],
                    'dependency_policy': 'unchanged inputs reused; changed state invalidates following scenes'})
        index = read(self.run/'ARTIFACT_INDEX.json')
        atomic(self.run/'ARTIFACT_INDEX.json', {'INVALIDATION.json': index['INVALIDATION.json']})
        self.data['generation'] += 1
        self.save()
        self.folder = self.run/'attempts'/f'{len(list((self.run/"attempts").glob("*"))):04}'
        self.folder.mkdir()
