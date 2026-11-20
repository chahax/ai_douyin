"""Adopt exactly one known DSPy JSON-wrapper receipt; do not regenerate it."""
from novel_multiround_20261027 import *
def parse_native_wrapper(native,source):
    if native.get('model')!=MODEL or len(native.get('choices',[]))!=1:raise ValueError('native_identity')
    choice=native['choices'][0];message=choice['message']
    if choice['finish_reason']!='stop' or message.get('tool_calls'):raise ValueError('not_known_text_terminal')
    parsed=json.loads(message['content'])
    if set(parsed)!={'result'}:raise ValueError('exact_dspy_wrapper_required')
    return validate_material(parsed['result'],source)
def main():
    parent=BASE/'fewshot';run=BASE/'fewshot_continued';source=read(BASE/'SOURCE.json')
    if run.exists():raise ValueError('no_replay')
    prior=read(parent/'RESULT.json')
    if prior['pending'] is not None or prior['calls']!=1 or prior['error']!='RuntimeError:native_contract_failed':raise ValueError('wrong_prior')
    receipt=read(parent/'ANALYZE/RESPONSE_1.json');initial=parse_native_wrapper(receipt['native'],source)
    run.mkdir();dump(run/'ADOPTION.json',{'parent':str(parent),'native_sha256':sha(receipt),'material_sha256':sha(initial),'protocol':'仅接收已知stop、无tool_calls、JSON恰有result键、result符合Material及原段引用；原文和结果不改','remaining_max_native_calls':7,'source_sha256':sha(source),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    session=Session(run);session.save();failure=None;outcome=None
    try:
        outcome=drive(source,session.call,lambda n,v:dump(run/(n+'.json'),v),initial)
        dump(run/'FINAL_MATERIAL.json',outcome['material'])
    except Exception as exc:failure=type(exc).__name__+':'+str(exc)[:600]
    session.save();dump(run/'RESULT.json',{'status':outcome['status'] if outcome else 'needs_attention','rounds':outcome['rounds'] if outcome else None,'calls':session.count,'tokens':session.tokens,'pending':session.pending,'error':failure,'acceptance':'pending_primary_review','original_generation_reused':True})
    print(json.dumps(read(run/'RESULT.json')),flush=True)
if __name__=='__main__':main()
