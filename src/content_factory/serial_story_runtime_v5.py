"""Repair only the adjudicator's verified issue, not rejected parts of a review."""
from copy import deepcopy
from jsonschema import validate
from .serial_story_runtime_v4 import Runtime as PreviousRuntime, RepairRequired, PauseRequested, run_lock
from . import serial_story_contract_v5 as c
from .corpus_screenplay_v1 import digest


def adjudication_schema():
    issue=deepcopy(c.REVIEW['properties']['issues']['items'])
    return c.obj(candidate_sha256=c.TEXT,review_sha256=c.TEXT,findings=c.arr(c.obj(
        index={'type':'integer','minimum':0},verdict={'enum':['upheld','rejected','uncertain']},
        reason=c.STR,source_ids=c.IDS,validated_issue={'anyOf':[issue,{'type':'null'}]}),1))


def adjudication_valid(raw,candidate,review,source):
    validate(raw,adjudication_schema())
    if raw['candidate_sha256']!=digest(candidate) or raw['review_sha256']!=digest(review): raise ValueError('adjudication_binding_changed')
    if sorted(x['index'] for x in raw['findings'])!=list(range(len(review['issues']))): raise ValueError('adjudication_issue_coverage')
    for finding in raw['findings']:
        c.source_refs(finding['source_ids'],source)
        issue=finding['validated_issue']; original=review['issues'][finding['index']]
        if finding['verdict']=='upheld':
            if issue is None or any(issue[k]!=original[k] for k in ('owner','path')): raise ValueError('verified_issue_target_changed')
            c.review_valid({'candidate_sha256':digest(candidate),'decision':'revise','issues':[issue],'rationale':finding['reason']},candidate,source)
        elif issue is not None: raise ValueError('rejected_issue_must_not_drive_repair')
    return raw


class Runtime(PreviousRuntime):
    def phase(self,name,payload,schema,validator,prompt,role):
        if name in self.data['corrections']:
            prompt+='\n只执行required_corrections.issues中经裁决重写的成立问题；原review仅作历史证据，不能执行裁决驳回或未确认的部分。'
        return super().phase(name,payload,schema,validator,prompt,role)

    def review_failure(self,name,candidate,source,inputs,review,phase):
        if review['decision']=='uncertain': raise ValueError('review_evidence_insufficient')
        result=phase('ADJUDICATE_'+name,{'candidate':candidate,'candidate_sha256':digest(candidate),
            'review':review,'review_sha256':digest(review),'inputs':inputs},adjudication_schema(),
            lambda x:adjudication_valid(x,candidate,review,source),
            '独立裁决每条意见。若仅部分成立，validated_issue只写经证据确认的缺陷与修复方向，剔除错误反转或未证实判断；owner/path保持原目标。驳回或不确定时validated_issue=null。不要把条件句当已发生事件。','writer')
        self.record(name+'_ADJUDICATED.json',result)
        if any(f['verdict']=='uncertain' for f in result['findings']): raise ValueError('adjudication_evidence_insufficient')
        upheld=[f['validated_issue'] for f in result['findings'] if f['verdict']=='upheld']
        if not upheld: raise ValueError('review_rejected_requires_independent_resolution')
        raise RepairRequired(name,candidate,review,{'adjudication':result,'upheld':upheld})
