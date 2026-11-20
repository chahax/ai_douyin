"""Adopt known native receipts without changing them; remove arbitrary fact-count cap."""
from framework_bench_20261027 import *
class ReadingUnbounded(Strict):facts:list[Fact]=Field(min_length=1)
def main(framework):
    parent=BASE/framework;run=BASE/(framework+'_continued')
    if run.exists():raise ValueError('existing_run_no_replay')
    state=read(parent/'STATE.json');prior=read(parent/'RESULT.json')
    if state['pending'] is not None or not prior['error'] or 'at most 30 items' not in prior['error']:raise ValueError('not_known_count_failure')
    receipt=read(parent/'RESPONSE_1.json');native=receipt['native'];calls=native['choices'][0]['message']['tool_calls']
    if native['model']!=MODEL or len(calls)!=1 or calls[0]['function']['name']!='submit_result':raise ValueError('native_mismatch')
    reading=ReadingUnbounded.model_validate_json(calls[0]['function']['arguments']).model_dump()
    catalog=read(BASE/'SOURCE.json');known={p['id'] for p in catalog}
    if any(i not in known for f in reading['facts'] for i in f['source_ids']):raise ValueError('source_ref_unknown')
    run.mkdir();dump(run/'ADOPTION.json',{'parent':str(parent),'native_response_sha256':sha(receipt),'reading_sha256':sha(reading),'schema':ReadingUnbounded.model_json_schema(),'change':'删除无内容依据的30条材料上限，其余字段及来源校验保持','authorization':'用户授权五框架比较，已知原生回执复用，不重跑旧任务','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()});dump(run/'READING.json',reading)
    gw=Gateway(run);gw.save();error=None
    try:
        verdicts=invoke(framework,gw,CHECK_PROMPT,{'complete_chapters':catalog,'blind_reading':reading,'fixed_claims':read(BASE/'CLAIMS.json')},Verdicts)
        dump(run/'VERDICTS.json',verdicts)
        ids=[f['id'] for f in verdicts['findings']]
        if sorted(ids)!=sorted(c['id'] for c in read(BASE/'CLAIMS.json')) or any(i not in known for f in verdicts['findings'] for i in f['source_ids']):raise ValueError('verdict_bindings')
        expected={e['id']:e['supported'] for e in read(BASE/'EXPECTED_NOT_SENT.json')}
        dump(run/'SCORE.json',[{'id':f['id'],'matches':expected[f['id']]==f['supported']} for f in verdicts['findings']])
    except Exception as exc:error=type(exc).__name__+':'+str(exc)[:300]
    gw.save();dump(run/'RESULT.json',{'framework':framework,'calls':gw.calls,'reported_tokens':gw.tokens,'elapsed_seconds':gw.elapsed,'pending':gw.pending,'error':error,'acceptance':'pending_primary_review','adopted_original_reading':True});print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main(sys.argv[1])
