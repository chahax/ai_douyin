"""Opt-in simple wire envelope; semantic schema remains a separate strict gate."""
import json
from src.content_factory.serial_story_transport_v6 import NativeClient,Ledger
from src.content_factory.corpus_screenplay_v1 import freeze

WIRE_SCHEMA={'type':'object','properties':{'result_json':{'type':'string','description':'Complete JSON serialization of the result matching output_schema.'}},'required':['result_json'],'additionalProperties':False}
WIRE_PROMPT='\n本次submit_result工具传输参数只有result_json一个字符串字段。先按用户消息output_schema形成完整结果，再将完整结果序列化为JSON字符串放入result_json。不要把records等业务字段直接作为工具参数，不要省略或截断；语义字段与原output_schema完全相同。'


class StringEnvelopeClient(NativeClient):
    def call(self,role,messages,schema):
        if role!='writer':raise ValueError('string_envelope_writer_only')
        return super().call(role,messages,WIRE_SCHEMA)


class EnvelopeWireLedger(Ledger):
    def request_size(self,messages,schema):
        # Count actual message strings once, not HTTP JSON escaping of those
        # strings. Semantic output_schema is already in the user message.
        # Include the actual simple tool schema as well as the role labels.
        return sum(len(m['content'].encode('utf-8'))+len(m['role'].encode('utf-8')) for m in messages)+len(json.dumps(WIRE_SCHEMA,ensure_ascii=False).encode('utf-8'))


class StringEnvelopeLedger(EnvelopeWireLedger):
    def call(self,name,role,prompt,payload,schema):
        value=super().call(name,role,prompt+WIRE_PROMPT,payload,schema)
        result=decode(value)
        freeze(self.run/(name+'_ENVELOPE_DECODED.json'),result)
        return result


def decode(value):
    if not isinstance(value,dict) or set(value)!={'result_json'} or not isinstance(value['result_json'],str):
        raise ValueError('invalid_string_envelope')
    def unique(pairs):
        out={}
        for key,val in pairs:
            if key in out:raise ValueError('duplicate_envelope_result_key')
            out[key]=val
        return out
    try:return json.loads(value['result_json'],object_pairs_hook=unique)
    except json.JSONDecodeError as exc:raise ValueError('incomplete_envelope_result') from exc
