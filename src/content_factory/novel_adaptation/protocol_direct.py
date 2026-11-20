"""Opt-in native tool arguments, without JSON encoded inside a JSON string."""
import json
from src.content_factory.serial_story_transport_v6 import Ledger, NativeClient
from src.content_factory.corpus_screenplay_v1 import read, freeze
from . import contracts as c


class DirectLedger(Ledger):
    def request_size(self,messages,schema):
        return sum(len(m['content'].encode('utf-8'))+len(m['role'].encode('utf-8')) for m in messages)+len(json.dumps(schema,ensure_ascii=False).encode('utf-8'))

    def call(self,name,role,prompt,payload,schema):
        if role!='writer':raise ValueError('direct_writer_only')
        report=None
        before_call=self.state['calls_started']
        try:
            super().call(name,role,prompt+' 工具参数直接使用output_schema的字段，不要嵌套result_json字符串。',payload,schema)
        finally:
            folder=self.run/f"native_{self.state['calls_started']:03}"
            if self.state['calls_started']>before_call and (folder/'CHUNKS.jsonl').exists() and (folder/'RESPONSE.json').exists():
                from .stream_evidence import audit_folder
                try:report=audit_folder(folder)
                except (ValueError,OSError) as exc:
                    report={'completion_evidence':'unknown','audit_error':type(exc).__name__,'may_retry':False}
                freeze(self.run/f"STREAM_EVIDENCE_{self.state['calls_started']:03}.json",report)
        if report is not None and report['completion_evidence']!='known':
            self.state.update(status='outcome_unknown',pending=self.state['calls_started']);self.save()
            raise RuntimeError('native_stream_receipt_inconsistent_no_replay')
        # Reparse the original tool arguments strictly; the shared ledger keeps
        # the original receipt and cumulative accounting, even for invalid JSON.
        receipt=read(self.run/f"RESPONSE_{self.state['calls_started']:03}.json")
        raw=receipt['native']['choices'][0]['message']['tool_calls'][0]['function']['arguments']
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate_direct_key')
                result[key]=value
            return result
        value=json.loads(raw,object_pairs_hook=unique)
        errors=c.schema_issues(value,schema,'direct_tool_result')
        if errors:raise c.ContractError(errors)
        freeze(self.run/(name+'_DIRECT_DECODED.json'),value)
        return value
