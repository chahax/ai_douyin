"""New real-text v6 runs, five efforts. No old run is replayed."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import serial_story_production_v6 as p
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/corpus_production_trials/20261028_v6_five_efforts'
EFFORTS=('low','medium','high','xhigh','max')


def prepare():
    BASE.mkdir(exist_ok=False)
    freeze(BASE/'EXPERIMENT.json',{'user':'拿小说测试minimax不同程度的版本都可以试下',
        'source':'你敢惹我？我有六个反派儿子，第1—3章完整正文',
        'efforts':EFFORTS,'read_calls_expected':5,'read_checkpoint':True,
        'total_engineering_call_bound':200,'max_calls_per_run':40,'continuation':'由主助手独立核对后选取有改善的档位继续首集；不重置各run预算',
        'media':False,'publication':False,'book_prior_calls_started':150,'historical_unknowns':2})
    for effort in EFFORTS:
        run=BASE/effort
        plan=p.prepare(ROOT/'data/fanqie_account_control/books/7302660145530539062/MANIFEST.json',run,
            user_statement='用户要求真实小说测试MiniMax各思考档；先比较前三章理解，再继续合适档位的v6首集，沿原授权DeepSeek只做终审。',
            max_calls=40,episode_limit=1,writer_effort=effort,writer_max_tokens=65536,reading_checkpoint=True,chapter_indices=[1,2,3])
        p.authorize(run,{'origin':'explicit_user_approval','user_statement':plan['user_statement'],
            'plan_sha256':digest(plan),'source_sha256':plan['source_sha256'],'chapter_indices':plan['chapter_indices'],
            'destinations':plan['routes'],'max_calls':plan['max_calls'],'media':False,'publication':False})


def execute(effort,resume=False):
    result=p.execute(BASE/effort,resume=resume)
    print(effort+': '+result['state']['status']+'; calls='+str(result['state']['calls_started'])+'; '+str(result['error']),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','read','resume']);ap.add_argument('--effort',choices=EFFORTS)
    args=ap.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='read':
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(execute,EFFORTS))
    else:
        if not args.effort:ap.error('resume requires --effort')
        execute(args.effort,True)
