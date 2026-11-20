"""Read-only image-scoped evidence selection; never bypass a prior unknown claim."""
import json
from pathlib import Path
import re

from .visual_shot_binding_v3 import fingerprint


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _request(folder):
    path=folder/'REQUEST.json'
    if not path.is_file():raise ValueError('first_frame_review_evidence_has_no_request')
    request=_read(path);prepared=request.get('prepared')
    if not isinstance(prepared,list) or not prepared:raise ValueError('first_frame_review_evidence_invalid_request')
    targets={p.get('target',{}).get('sha256') for p in prepared}
    if len(targets)!=1 or not re.fullmatch('[0-9a-f]{64}',next(iter(targets)) or ''):
        raise ValueError('first_frame_review_evidence_mixed_targets')
    return request,prepared,next(iter(targets))


def _known(folder,request,prepared,target):
    """Only an intact, fully completed original batch settles its claim."""
    path=folder/'RESULTS.json'
    if not path.is_file():return False
    result=_read(path);values=result.get('results')
    expected=fingerprint(dict(config=request['config'],**(
        dict(prepared=prepared[0]) if request.get('review_mode') else dict(requests=prepared))))
    if (request.get('request_binding_sha256')!=expected or result.get('request_binding_sha256')!=expected
            or not isinstance(values,list) or len(values)!=len(prepared)
            or result.get('results_sha256')!=fingerprint(values)):
        raise ValueError('first_frame_review_evidence_binding_changed')
    for item,value in zip(prepared,values):
        if value.get('binding_sha256')!=fingerprint(item) or value.get('target_sha256')!=target:
            raise ValueError('first_frame_review_evidence_target_changed')
    claim=folder/'CLAIM.json'
    if claim.exists() and _read(claim).get('request_binding_sha256')!=expected:
        raise ValueError('first_frame_review_evidence_claim_changed')
    return all(v.get('completion_known') is True and v.get('outcome_unknown') is False for v in values)


def _repair_known(history,binding,target):
    return any(row.get('binding_sha256')==binding and row.get('sha256')==target
        and row.get('review',{}).get('target_sha256')==target
        and row['review'].get('decision')=='repair_required'
        and row['review'].get('completion_known') is True
        and row['review'].get('outcome_unknown') is False for row in history)


def select(root,binding_sha256,target_sha256,attempt,*,repair_history=()):
    """Choose <binding>/<image SHA>/<attempt>, preserving compatible legacy IDs.

    Legacy <binding>/<attempt> for this exact image stays authoritative, including
    its unknown claim and immutable input binding. Moving to another image needs
    both fully known original native results and its known repair history. This
    function reads evidence only; the original reviewer still verifies all inputs.
    """
    if (not re.fullmatch('[0-9a-f]{64}',binding_sha256 or '')
            or not re.fullmatch('[0-9a-f]{64}',target_sha256 or '')
            or type(attempt) is not int or attempt<0):
        raise ValueError('invalid_first_frame_review_evidence_key')
    base=Path(root)/binding_sha256;fresh=base/target_sha256/str(attempt)
    ledgers=[]
    if base.exists():
        for entry in base.iterdir():
            if not entry.is_dir():continue
            if entry.name.isdigit():ledgers.append((entry,None,int(entry.name)))
            elif re.fullmatch('[0-9a-f]{64}',entry.name):
                ledgers.extend((p,entry.name,int(p.name)) for p in entry.iterdir() if p.is_dir() and p.name.isdigit())
    chosen=None
    for folder,image_key,index in ledgers:
        if not any(folder.iterdir()):continue
        request,prepared,target=_request(folder)
        if image_key is not None and image_key!=target:raise ValueError('first_frame_review_evidence_path_target_changed')
        if target==target_sha256 and index==attempt:
            if chosen is not None and chosen!=folder:raise ValueError('first_frame_review_duplicate_image_evidence')
            chosen=folder
            # Do not replace a same-image claim/result when expectations changed.
            # The client must see its original directory and reject/reuse it.
            continue
        known=_known(folder,request,prepared,target)
        if not known:raise ValueError('first_frame_review_prior_outcome_unknown')
        if target!=target_sha256 and not _repair_known(repair_history,binding_sha256,target):
            raise ValueError('first_frame_review_prior_image_not_known_repair')
    return chosen if chosen is not None else fresh
