"""Render a completed serial trial with source chapter ranges; never edit model prose."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest

def export(run):
    result=read(run/'RESULT.json');state=read(run/'STATE.json');episodes=read(run/'EPISODE_PLAN.json')
    if state['pending'] is not None or result['chapters']!=69 or result['episodes']!=len(episodes):
        raise ValueError('series_not_complete')
    blocks=[];rows=[]
    for i,ep in enumerate(episodes,1):
        path=run/f'EPISODE_{i:02}.json'
        if not path.exists():path=run/f'ADOPTED_EPISODE_{i:02}.json'
        draft=read(path)
        heading=f"第{i:02}集 {ep['title']}｜原文第{ep['start']}—{ep['end']}章"
        blocks.append('## '+heading+'\n\n'+draft['screenplay'])
        rows.append({'episode':i,'source_chapters':list(range(ep['start'],ep['end']+1)),
                     'candidate_path':str(path.resolve()),'candidate_sha256':digest(draft),
                     'screenplay_characters':len(draft['screenplay'])})
    text='# 《你敢惹我？我有六个反派儿子》69章连载剧本生产候选\n\n'
    text+='> 共46集，全文已生成，但内容尚未验收；部分对白归属、人物年龄和承接存在待修问题。正文原样保留；如原生内文集号与目录不一致，以外层46集目录为准。\n\n'
    text+='\n\n---\n\n'.join(blocks)
    output=run/'全69章_46集剧本阅读版_待修订.md'
    with output.open('x',encoding='utf-8') as f:f.write(text)
    freeze(run/'READING_EXPORT.json',{'path':str(output.resolve()),'rows':rows,
        'screenplay_characters':sum(x['screenplay_characters'] for x in rows),'all_prose_preserved':True,
        'source_chapter_coverage':[n for x in rows for n in x['source_chapters']],
        'semantic_acceptance':False})
    print(str(output.resolve()))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();export(a.run)
