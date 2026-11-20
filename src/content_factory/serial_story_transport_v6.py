"""Pinned effort/budget transport with streamed receipts and child-only deadline."""
from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path
import time
from src.platform_adapter.fanqie_book_corpus import atomic
from .creative_workflow_roles import _response_model_matches
from .corpus_screenplay_v1 import digest
from .creative_workflow_roles import role_config
from .corpus_screenplay_v1 import read, freeze


def selected_endpoint(role, cfg, override=None):
    """Explicit per-run opt-in to the official China endpoint; no global change."""
    if override is None:
        return cfg.base_url
    if role != 'writer' or cfg.provider != 'minimax' or override != 'https://api.minimax.cn/v1':
        raise ValueError('unsupported_endpoint_override')
    return override


def request_args(plan, role, messages, schema):
    options = plan['inference']
    args = {'model': plan['routes'][role]['model'], 'messages': messages,
            'stream': True, 'stream_options': {'include_usage': True}}
    if role == 'writer':
        args.update(max_completion_tokens=options['writer_max_tokens'],
                    reasoning_effort=options['writer_effort'],
                    extra_body={'thinking': {'type': 'adaptive'}, 'reasoning_split': True},
                    tools=[{'type': 'function', 'function': {'name': 'submit_result',
                           'description': '提交本阶段完整结果', 'parameters': schema}}])
    elif 'director_max_tokens' in options:
        mode = options.get('director_thinking', 'disabled')
        if mode not in ('enabled', 'disabled'):
            raise ValueError('invalid_director_thinking')
        args.update(max_tokens=options['director_max_tokens'],
                    extra_body={'thinking': {'type': mode}}, response_format={'type': 'json_object'})
        if mode == 'enabled':
            effort = options.get('director_effort', 'high')
            if effort not in ('low', 'high', 'max'):
                raise ValueError('invalid_director_effort')
            args['reasoning_effort'] = effort
    else:
        # Old frozen runs retain their request contract.
        args.update(max_completion_tokens=16384, extra_body={'thinking': {'type': 'disabled'}},
                    response_format={'type': 'json_object'})
    return args


class NativeClient:
    def __init__(self, run, plan):
        self.run, self.plan = Path(run), plan

    def call(self, role, messages, schema):
        n = read(self.run/'STATE.json')['calls_started']
        folder = self.run/f'native_{n:03}'
        folder.mkdir(exist_ok=False)
        cfg = role_config(role)
        override = self.plan.get('endpoint_overrides', {}).get(role, self.plan.get('endpoint_override'))
        endpoint = selected_endpoint(role, cfg, override)
        if override is not None and self.plan['routes'][role]['base_url'] != endpoint:
            raise ValueError('plan_endpoint_mismatch')
        options = self.plan['inference']
        args = request_args(self.plan, role, messages, schema)
        spec = {'role': role, 'args': args, 'base_url': endpoint}
        if override is not None:
            spec['endpoint_override'] = override
        freeze(folder/'REQUEST.json', spec)
        command = [sys.executable, str(Path(__file__).resolve().parents[2]/'scripts/serial_native_worker_v6.py'), str(folder)]
        child = subprocess.Popen(command)
        try:
            child.wait(timeout=options['wall_seconds'])
        except subprocess.TimeoutExpired:
            child.terminate(); child.wait(timeout=10)
            freeze(folder/'DEADLINE.json', {'outcome_unknown': True, 'retry': False})
            raise RuntimeError('native_wall_deadline_unknown') from None
        if child.returncode != 0 or not (folder/'RESPONSE.json').exists():
            raise RuntimeError('native_child_no_complete_receipt')
        return read(folder/'RESPONSE.json')


class Ledger:
    def __init__(self,run,plan,state,client):self.run,self.plan,self.state,self.client=run,plan,state,client
    def save(self):atomic(self.run/'STATE.json',self.state)
    def request_size(self,messages,schema):
        return len(json.dumps(messages,ensure_ascii=False).encode())
    def call(self,name,role,prompt,payload,schema):
        output_tokens=self.plan['inference']['writer_max_tokens'] if role=='writer' else self.plan['inference'].get('director_max_tokens',16384)
        if self.state['pending'] is not None:raise RuntimeError('unknown_call_no_replay')
        if self.state['calls_started']>=self.plan['max_calls']:raise RuntimeError('call_limit')
        if role=='director' and not name.startswith(('FINAL_CONTENT','FINAL_TIMING')):raise ValueError('director_final_only')
        messages=[{'role':'system','content':prompt+(' 只调用submit_result提交结果。' if role=='writer' else ' 只返回符合schema的JSON。')},
                  {'role':'user','content':json.dumps({**payload,'output_schema':schema},ensure_ascii=False,separators=(',',':'))}]
        if self.request_size(messages,schema)+output_tokens+1024>self.plan['context']:raise ValueError('complete_request_exceeds_capacity')
        n=self.state['calls_started']+1
        req={'stage':name,'role':role,'messages':messages,'schema':schema,'route':self.plan['routes'][role],
             'max_completion_tokens':output_tokens,'inference':self.plan['inference'],'automatic_retries':0,'source_sha256':self.plan['source_sha256']}
        freeze(self.run/f'CALL_{n:03}.json',req)
        self.state.update(status='running',stage=name,pending=n,calls_started=n);self.save();start=time.monotonic()
        try:native=self.client.call(role,messages,schema)
        except Exception as exc:
            freeze(self.run/f'ERROR_{n:03}.json',{'type':type(exc).__name__,'status':getattr(exc,'status_code',None)})
            self.state['status']='outcome_unknown';self.save();raise RuntimeError('request_unknown_no_replay') from None
        freeze(self.run/f'RESPONSE_{n:03}.json',{'native':native,'elapsed_seconds':round(time.monotonic()-start,3)})
        choices=native.get('choices') or [];u=native.get('usage') or {}
        known=(native.get('id') and len(choices)==1 and choices[0].get('finish_reason') in ('tool_calls','stop','length')
            and all(type(u.get(k)) is int and u[k]>=0 for k in ('prompt_tokens','completion_tokens','total_tokens'))
            and u['total_tokens']==u['prompt_tokens']+u['completion_tokens'])
        if not known:self.state['status']='outcome_unknown';self.save();raise RuntimeError('native_usage_or_completion_unknown')
        self.state.update(pending=None,reported_tokens=self.state['reported_tokens']+u['total_tokens']);self.save()
        expected=self.plan['routes'][role]['model'];actual=native.get('model','')
        if not (actual==expected if role=='writer' else _response_model_matches(role,expected,actual)):raise RuntimeError('native_model_mismatch')
        choice=choices[0]
        if choice['finish_reason']=='length':raise RuntimeError('native_truncated_no_protocol_retry')
        message=choice.get('message') or {}
        if role=='writer':
            calls=message.get('tool_calls') or []
            if choice['finish_reason']!='tool_calls' or len(calls)!=1 or calls[0].get('function',{}).get('name')!='submit_result':
                raise RuntimeError('native_tool_submission_missing')
            text=calls[0]['function']['arguments']
        else:
            if choice['finish_reason']!='stop' or message.get('tool_calls'):raise RuntimeError('native_final_not_text')
            text=message.get('content')
        try:value=json.loads(text)
        except (json.JSONDecodeError,TypeError):value={'invalid_native_json':text}
        freeze(self.run/(name+'.json'),value)
        return value
