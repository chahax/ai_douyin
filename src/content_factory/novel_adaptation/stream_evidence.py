"""Offline stream/receipt consistency evidence; never settles or retries a call."""
import json
from pathlib import Path
from src.content_factory.corpus_screenplay_v1 import digest


def audit(rows, receipt):
    issues=[];ids=set();models=set();finishes=[];usages=[];arguments={};names={}
    for row in rows:
        if row.get('id'):ids.add(row['id'])
        if row.get('model'):models.add(row['model'])
        if row.get('usage') is not None:usages.append(row['usage'])
        for choice in row.get('choices',[]):
            if choice.get('index')!=0:issues.append('multiple_choices')
            if choice.get('finish_reason'):finishes.append(choice['finish_reason'])
            for tool in (choice.get('delta') or {}).get('tool_calls') or []:
                index=tool.get('index')
                if type(index) is not int or index<0:
                    issues.append('invalid_tool_index');continue
                function=tool.get('function') or {}
                arguments[index]=arguments.get(index,'')+(function.get('arguments') or '')
                names[index]=names.get(index,'')+(function.get('name') or '')
    if not rows:issues.append('empty_stream')
    if len(ids)!=1 or receipt.get('id') not in ids:issues.append('stream_identity_mismatch')
    if len(models)!=1 or receipt.get('model') not in models:issues.append('stream_model_mismatch')
    choices=receipt.get('choices') or []
    choice=choices[0] if len(choices)==1 else {}
    if len(choices)!=1:issues.append('receipt_choice_count')
    if not finishes:issues.append('terminal_marker_missing')
    elif len(set(finishes))!=1 or choice.get('finish_reason')!=finishes[-1]:issues.append('terminal_marker_mismatch')
    usage=usages[-1] if usages else None
    valid_usage=(isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0
        for k in ('prompt_tokens','completion_tokens','total_tokens')))
    if not valid_usage or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:
        issues.append('valid_usage_missing')
    if receipt.get('usage')!=usage:issues.append('receipt_usage_mismatch')
    tools=(choice.get('message') or {}).get('tool_calls') or []
    if len(tools)!=len(arguments):issues.append('assembled_tool_count_mismatch')
    else:
        for index,tool in zip(sorted(arguments),tools):
            f=tool.get('function') or {}
            if f.get('arguments')!=arguments[index] or f.get('name')!=names[index]:
                issues.append('assembled_tool_mismatch')
    known=not issues and finishes[-1] in ('stop','tool_calls','length')
    return {'stream_rows':len(rows),'receipt_sha256':digest(receipt),'issues':sorted(set(issues)),
        'completion_evidence':'known' if known else 'unknown','finish_reason':choice.get('finish_reason'),
        'reported_usage':usage if valid_usage else None,'tool_argument_characters':sum(map(len,arguments.values())),
        'semantic_acceptance':False,'may_retry':False,'mutates_original_state':False}


def audit_folder(folder):
    folder=Path(folder)
    rows=[json.loads(line) for line in (folder/'CHUNKS.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    return audit(rows,json.loads((folder/'RESPONSE.json').read_text(encoding='utf-8')))
