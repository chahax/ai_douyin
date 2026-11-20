"""Opt-in transport: immutable calls, known-length recovery, independent budgets."""
import json
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import request_args,selected_endpoint
from src.content_factory.creative_workflow_roles import role_config,_response_model_matches
from src.platform_adapter.fanqie_book_corpus import atomic
from .agent_capacity_v2 import validate_profile,capacity_report,deadline_seconds
from .stream_evidence import audit_folder
from . import contracts as c


def normalize_response_envelope(value,schema):
    """Discard only a misplaced JSON-mode marker, never task content."""
    if not c.schema_issues(value,schema,'response'):return value,None
    if isinstance(value,dict) and value.get('type')=='json_object' and 'type' not in schema.get('properties',{}):
        fixed=deepcopy(value);del fixed['type']
        if not c.schema_issues(fixed,schema,'response'):
            return fixed,dict(method='remove_only_json_mode_marker',original_digest=digest(value),normalized_digest=digest(fixed))
    return value,None


class NativeClient:
    def __init__(self,run,plan):self.run,self.plan=Path(run),plan
    def call(self,role,messages,schema):
        n=read(self.run/'STATE.json')['calls_started'];folder=self.run/f'native_{n:03}'
        folder.mkdir(exist_ok=False)
        cfg=role_config(role)
        override=self.plan.get('endpoint_overrides',{}).get(role)
        endpoint=selected_endpoint(role,cfg,override)
        if endpoint.rstrip('/')!=self.plan['routes'][role]['base_url'].rstrip('/'):
            raise ValueError('endpoint_changed')
        spec=dict(role=role,args=request_args(self.plan,role,messages,schema),base_url=endpoint)
        if override:spec['endpoint_override']=override
        freeze(folder/'REQUEST.json',spec)
        worker=Path(__file__).resolve().parents[3]/'scripts/serial_native_worker_v6.py'
        child=subprocess.Popen([sys.executable,str(worker),str(folder)])
        started=time.monotonic()
        while child.poll() is None:
            if time.monotonic()-started>self.plan['inference']['wall_seconds']:
                child.terminate();child.wait(timeout=10)
                freeze(folder/'DEADLINE.json',dict(outcome_unknown=True,reason='total_deadline'))
                raise RuntimeError('total_deadline_unknown')
            time.sleep(.5)
        if child.returncode!=0 or not (folder/'RESPONSE.json').exists():
            raise RuntimeError('native_no_receipt')
        return read(folder/'RESPONSE.json')


class Transport:
    def __init__(self,run,plan,state,client_factory=NativeClient):
        self.run,self.plan,self.state,self.client_factory=Path(run),plan,state,client_factory
    def save(self):atomic(self.run/'STATE.json',self.state)
    def call(self,node,role,prompt,payload,schema,budgets=None):
        if self.state.get('pending') is not None:raise RuntimeError('unknown_call_no_replay')
        key=digest(dict(node=node,role=role,prompt=prompt,payload=payload,schema=schema))
        if self.state.setdefault('nodes',{}).get(node,{}).get('status')=='complete':
            raise ValueError('completed_node_no_replay')
        if node in self.state['nodes']:
            raise ValueError('node_already_dispatched_no_manual_replay')
        profile=self.plan['capabilities'][role]
        budgets=budgets or self.plan['budgets'][role]
        messages=[dict(role='system',content=prompt+(' 只调用submit_result，参数直接符合output_schema。' if role=='writer' else ' 只返回符合output_schema的JSON，不返回推理过程。')),
                  dict(role='user',content=json.dumps({**payload,'output_schema':schema},ensure_ascii=False,separators=(',',':')))]
        for attempt,output_tokens in enumerate(budgets):
            if self.state['calls_started']>=self.plan['max_calls']:raise RuntimeError('run_call_limit')
            if self.state.get('trial_ended'):raise ValueError('ended_run_no_replay')
            if attempt and self.state['nodes'][node]['status']!='known_truncated':raise ValueError('only_known_length_can_expand')
            active=deepcopy(self.plan);opts=active['inference']
            effort=opts['writer_effort'] if role=='writer' else opts['director_effort']
            validate_profile(profile,active['routes'][role]['model'],effort,output_tokens)
            opts['writer_max_tokens' if role=='writer' else 'director_max_tokens']=output_tokens
            opts['wall_seconds']=deadline_seconds(output_tokens)
            cap=capacity_report(messages,schema,profile,output_tokens)
            if cap['decision']!='fits_estimate':raise ValueError('capacity_estimate_uncertain_no_silent_truncation')
            n=self.state['calls_started']+1
            freeze(self.run/f'CALL_{n:03}.json',dict(node=node,role=role,input_digest=key,attempt=attempt,
                capacity=cap,inference=opts,messages=messages,schema=schema,
                recovery_of=self.state['nodes'].get(node,{}).get('call') if attempt else None))
            self.state.update(calls_started=n,pending=n,status='running')
            self.state['nodes'][node]=dict(status='running',input_digest=key,call=n);self.save()
            try:
                native=self.client_factory(self.run,active).call(role,messages,schema)
                evidence=audit_folder(self.run/f'native_{n:03}')
                freeze(self.run/f'STREAM_EVIDENCE_{n:03}.json',evidence)
                if evidence['completion_evidence']!='known':raise RuntimeError('stream_unknown')
            except Exception as exc:
                self.state.update(status='outcome_unknown',trial_ended=True)
                freeze(self.run/f'ERROR_{n:03}.json',dict(type=type(exc).__name__,message=str(exc)[:1000]))
                self.save();raise
            freeze(self.run/f'RESPONSE_{n:03}.json',native)
            self.state.update(pending=None,reported_tokens=self.state['reported_tokens']+native['usage']['total_tokens'])
            expected=active['routes'][role]['model'];actual=native.get('model','')
            if not (actual==expected if role=='writer' else _response_model_matches(role,expected,actual)):
                self.state.update(status='model_mismatch',trial_ended=True);self.save();raise ValueError('model_mismatch')
            choice=native['choices'][0]
            if choice['finish_reason']=='length':
                self.state['nodes'][node].update(status='known_truncated')
                self.state['status']='known_truncated';self.save()
                continue
            try:
                message=choice['message'];tools=message.get('tool_calls') or []
                if role=='writer' and tools:
                    if len(tools)!=1 or tools[0]['function']['name']!='submit_result':raise ValueError('wrong_tool')
                    raw=tools[0]['function']['arguments']
                else:
                    if choice['finish_reason']!='stop' or tools:raise ValueError('wrong_finish')
                    raw=message.get('content') or ''
                    # Whole prose is accepted only at the explicit author text node.
                    if role=='writer' and set(schema.get('properties',{}))=={'text'}:
                        try:json.loads(raw)
                        except json.JSONDecodeError:raw=json.dumps({'text':raw},ensure_ascii=False)
                def unique(pairs):
                    out={}
                    for k,v in pairs:
                        if k in out:raise ValueError('duplicate_json_key')
                        out[k]=v
                    return out
                value=json.loads(raw,object_pairs_hook=unique)
                value,normalization=normalize_response_envelope(value,schema)
                if normalization:freeze(self.run/f'NORMALIZATION_{n:03}.json',normalization)
                faults=c.schema_issues(value,schema,node)
                if faults:raise c.ContractError(faults)
                freeze(self.run/(node+'.json'),value)
            except Exception as exc:
                self.state.update(status='known_invalid_output',trial_ended=True)
                self.state['nodes'][node]['status']='known_invalid_output'
                freeze(self.run/f'ERROR_{n:03}.json',dict(type=type(exc).__name__,message=str(exc)[:2000]))
                self.save();raise
            self.state['nodes'][node].update(status='complete',result_digest=digest(value))
            self.state.update(status='node_complete');self.save();return value
        self.state.update(status='known_truncated',trial_ended=True);self.save()
        raise RuntimeError('known_length_recovery_exhausted')
