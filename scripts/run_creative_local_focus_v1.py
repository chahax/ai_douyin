"""Explicit operator entry: repeat exact current source/state at the request end."""
import sys,json
from scripts import run_creative_resume_v8 as runner


def run(drevision,index,revision,feedback=None):
    ctx,d=runner.direction_source(drevision)
    prior=runner.local_sources(drevision,index-1)
    inp=runner.physical.build_local_input(ctx,d,prior)
    shot=runner.physical._shots(d)[index-1]
    source=runner.physical._raw_sources(ctx)
    focus={'current_shot_only':shot,
      'ordered_complete_current_steps':[{"source_step_ref":ref,**source[ref]} for ref in shot['source_step_refs']],
      'actual_start_state':inp['start_state'],
      'allowed_satisfies_ids':[q['id'] for q in shot['performance_requirements'] if q['relation']!='during'],
      'output_contract':runner.local_contract.VERSION,
      'verified_faults_or_source_preflight':feedback or {},
      'complete_submission':'只生成上述当前镜的全部原action及对白表演，不处理未来镜。operation恰四键对象或null；每group的satisfies仅可使用allowed_satisfies_ids；空列表意味着每group都写[]。全文原稿/R01在前面的实际请求中保持，当前步骤以此原文为准，不拼接旧输出。'}
    runner.control.write(runner.ROOT/f'FOCUSED_INPUT_p{index:03}_r{revision}.json',focus,True)
    value=runner.local(drevision,index,revision,focus)
    return {k:value.get(k) for k in ('ordinal','status','validation_error','document_output','response_metadata')}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    fb=runner.control.read(sys.argv[4]) if len(sys.argv)>4 else None
    print(json.dumps(run(*map(int,sys.argv[1:4]),fb),ensure_ascii=False,indent=2))
