"""Local serial studio; render does not start models or grant authorization."""
from pathlib import Path
from datetime import datetime
import subprocess
import sys
from src.content_factory.corpus_screenplay_v1 import read, freeze, digest
from src.content_factory import serial_story_production_v2 as pipeline
from src.content_factory import serial_story_assets_v2 as assets

ROOT = Path(__file__).resolve().parents[2]


def artifact(run, name):
    run=Path(run).resolve(); index=read(run/'ARTIFACT_INDEX.json'); row=index[name]
    path=(run/row['path']).resolve()
    if not path.is_relative_to(run): raise ValueError('artifact_outside_run')
    value=read(path)
    if digest(value)!=row['sha256']: raise ValueError('artifact_changed')
    return value


def launch(run, resume=False):
    run=Path(run).resolve()
    if read(run/'PLAN.json')['version']!=pipeline.VERSION: raise ValueError('unsupported_run_version')
    # Worker repeats authorization and run-lock checks before any model request.
    if not (run/'AUTHORIZATION.json').is_file(): raise ValueError('explicit_authorization_missing')
    args=[sys.executable,str(ROOT/'scripts/run_serial_story.py'),'execute','--run',str(run)]
    if resume: args.append('--resume')
    with (run/'worker.log').open('ab') as log:
        process=subprocess.Popen(args,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return process.pid


def render_page():
    import streamlit as st
    st.header('小说连载剧本')
    st.caption('全章分析 → 连载分集 → 逐场生成 → 审核与返修。文本任务与视频发布分开。')
    manifests=sorted((ROOT/'data/fanqie_account_control/books').glob('*/MANIFEST.json'))
    if manifests:
        with st.form('serial_prepare'):
            manifest=st.selectbox('已获取书籍',manifests,format_func=lambda p:read(p).get('book_name',p.parent.name))
            batch=st.number_input('每批生成集数',1,100,2)
            calls=st.number_input('本任务总文本调用上界（续写共享）',1,2000,400)
            seconds=st.number_input('每个视频片段最大秒数',1,120,15)
            create=st.form_submit_button('建立本地计划')
        if create:
            run=ROOT/'data/serial_story_runs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            pipeline.prepare(manifest,run,user_statement='网页用户建立连载文本计划，尚未授权外发',
                             episode_limit=int(batch),max_calls=int(calls),shot_seconds=int(seconds))
            st.success('本地计划已建立；未调用模型。')
    runs=sorted((ROOT/'data/serial_story_runs').glob('*/PLAN.json'),reverse=True)
    if not runs:
        st.info('建立计划后可查看状态、授权启动和管理参考资产。'); return
    run=st.selectbox('连载任务',[p.parent for p in runs],format_func=lambda p:p.name)
    plan=read(run/'PLAN.json'); state=read(run/'STATE.json'); source=read(run/'SOURCE.json')
    st.write({'状态':state['status'],'调用次数':state['calls_started'],'已完成集数':state.get('completed_episodes',0)})
    if st.button('刷新任务状态'): st.rerun()
    if not (run/'AUTHORIZATION.json').exists():
        st.write(f"授权范围：{source['manifest'].get('book_name','')}，已获取{len(source['chapters'])}章。MiniMax分析/编剧，DeepSeek分集终审；最多{plan['max_calls']}次文本调用，无媒体或发布。")
        agreed=st.checkbox('我允许将上述原文和剧本发送至所列模型服务')
        if st.button('确认授权并开始文本生成',disabled=not agreed):
            pipeline.authorize(run,{'origin':'explicit_user_approval','user_statement':'用户在连载页明确确认展示的书籍、章节、服务及调用范围',
                'plan_sha256':digest(plan),'source_sha256':plan['source_sha256'],'chapter_indices':plan['chapter_indices'],
                'destinations':plan['routes'],'max_calls':plan['max_calls'],'media':False,'publication':False})
            st.success(f'已启动文本任务，进程 {launch(run)}。')
    elif state['status'] in ('prepared','paused','ready_for_next_batch','running') and state['pending'] is None:
        if st.button('继续文本任务 / 下一批'):
            (run/'PAUSE_REQUESTED.json').unlink(missing_ok=True)
            st.success(f'已提交，进程 {launch(run,resume=state["status"]!="prepared")}。')
    if state['status']=='running' and st.button('在当前调用结束后暂停'):
        if not (run/'PAUSE_REQUESTED.json').exists(): freeze(run/'PAUSE_REQUESTED.json',{'user_requested':True})
        st.info('不会中断已经发出的模型请求。')
    if (run/'ARTIFACT_INDEX.json').exists():
        index=read(run/'ARTIFACT_INDEX.json')
        selected=st.selectbox('查看产物',list(index))
        value=artifact(run,selected); st.json(value)
        import json
        st.download_button('下载此产物',json.dumps(value,ensure_ascii=False,indent=2),file_name=selected,mime='application/json')
    library=ROOT/'data/serial_story_assets'
    with st.expander('人物与场景参考资产'):
        with st.form('serial_asset_import'):
            image=st.text_input('本机图片绝对路径')
            entity=st.text_input('剧本中的人物或地点ID')
            kind=st.selectbox('资产类型',['character','place'])
            view=st.text_input('方位或细节名称',value='正面')
            register=st.form_submit_button('保存为新资产版本')
        if register:
            try: st.json(assets.register(library,image,book_id=source['manifest']['book_id'],entity_id=entity,kind=kind,view=view))
            except (ValueError,OSError) as exc: st.error(str(exc))
        if (library/'INDEX.json').exists():
            available=[a for a in read(library/'INDEX.json')['assets'] if a['book_id']==str(source['manifest']['book_id'])]
            st.json(available)
            if (run/'ARTIFACT_INDEX.json').exists():
                choices=[n for n in read(run/'ARTIFACT_INDEX.json') if n.endswith('_ACCEPTED.json')]
                if choices:
                    with st.form('serial_asset_bind'):
                        episode=st.selectbox('绑定到已审核剧集',choices)
                        picks=st.multiselect('选择明确资产版本',range(len(available)),format_func=lambda i:f"{available[i]['entity_id']} / {available[i]['view']} / v{available[i]['version']}")
                        submit=st.form_submit_button('导出含参考资产的镜头计划')
                    if submit:
                        try:
                            bound=artifact(run,episode)['bound']
                            shots=artifact(run,episode.replace('_ACCEPTED.json','_SHOTS.json'))['shots']
                            result=assets.bind(library,source['manifest']['book_id'],bound,shots,[available[i] for i in picks])
                            freeze(run/('ASSET_BINDING_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json'),result)
                            st.success('镜头计划已绑定指定版本；未生成视频。')
                        except (ValueError,KeyError,OSError) as exc: st.error(str(exc))
