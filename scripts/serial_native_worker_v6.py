"""A single native request. Credentials stay in this process, never in argv/files."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read, freeze
from src.content_factory.creative_workflow_roles import role_config
from src.content_factory.serial_story_transport_v6 import selected_endpoint


def run(folder):
    from openai import OpenAI
    spec = read(folder/'REQUEST.json'); cfg = role_config(spec['role'])
    endpoint = selected_endpoint(spec['role'], cfg, spec.get('endpoint_override'))
    if endpoint != spec['base_url']:
        raise ValueError('route_changed')
    content, reasoning, tools = [], [], {}
    model = rid = finish = None; usage = None
    started = time.monotonic()
    try:
        with OpenAI(api_key=cfg.api_key, base_url=endpoint, max_retries=0, timeout=90) as client:
            with (folder/'CHUNKS.jsonl').open('x',encoding='utf-8') as log:
                with client.chat.completions.create(**spec['args']) as stream:
                    for chunk in stream:
                        log.write(json.dumps(chunk.model_dump(mode='json'),ensure_ascii=False)+'\n'); log.flush()
                        rid = chunk.id or rid; model = chunk.model or model
                        if chunk.usage: usage = chunk.usage.model_dump(mode='json')
                        for c in chunk.choices:
                            if c.index != 0: raise ValueError('multiple_choices')
                            if c.finish_reason: finish = c.finish_reason
                            if c.delta.content: content.append(c.delta.content)
                            r = getattr(c.delta,'reasoning_content',None)
                            if r: reasoning.append(r)
                            for t in c.delta.tool_calls or []:
                                row=tools.setdefault(t.index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                                if t.id: row['id']=t.id
                                if t.function:
                                    if t.function.name: row['function']['name']+=t.function.name
                                    if t.function.arguments: row['function']['arguments']+=t.function.arguments
        freeze(folder/'RESPONSE.json',{'id':rid,'model':model,'usage':usage,'choices':[{'index':0,'finish_reason':finish,
            'message':{'content':''.join(content),'reasoning_content':''.join(reasoning),'tool_calls':[tools[i] for i in sorted(tools)]}}]})
        freeze(folder/'METRICS.json',{'elapsed_seconds':time.monotonic()-started})
    except Exception as e:
        freeze(folder/'ERROR.json',{'type':type(e).__name__,'pending':True,'usage':usage})
        raise SystemExit(1) from None


if __name__ == '__main__':
    run(Path(sys.argv[1]))
