"""Reference library, detailed metric entry, and production experiment UI."""
import json
import streamlit as st

from src.services.content_performance import WATCH_FIELDS, METRICS, RETENTION, record_snapshot, snapshot_history
from src.services.production_learning import (list_references, save_reference, list_experiments,
    save_experiment, record_outcome, experiment_packet)


def render_learning(account_uuid, snapshots, can_edit):
    with st.expander('推荐学习视频与笔记', expanded=not snapshots):
        references = list_references(account_uuid)
        options = {0: '新增参考视频', **{r['id']: r['title'] for r in references}}
        chosen = st.selectbox('选择参考视频', list(options), format_func=options.get, key='learning_ref_choice')
        existing = next((r for r in references if r['id'] == chosen), {})
        with st.form(f'learning_ref_{account_uuid}_{chosen}'):
            url = st.text_input('视频链接', value=existing.get('url', ''))
            title = st.text_input('参考视频标题', value=existing.get('title', ''))
            reason = st.text_area('推荐理由 / 值得学习的地方', value=existing.get('reason', ''))
            notes = st.text_area('观看笔记（可记录时间点、开头、节奏、镜头、对白）', value=existing.get('notes', ''))
            tags = st.text_input('学习标签', value=existing.get('tags', ''))
            statuses = ['待学习', '已学习', '暂不采用']
            status = st.selectbox('学习状态', statuses, index=statuses.index(existing.get('status', '待学习')))
            if st.form_submit_button('保存参考视频', disabled=not can_edit):
                try:
                    save_reference(account_uuid,url,title,reason,notes,tags,status)
                    st.success('参考视频和笔记已保存。')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        for ref in references:
            st.link_button(ref['title'], ref['url'])
            st.caption(f"{ref['status']} · {ref['tags']}")
            st.text(ref['reason'])
            if ref['notes']:
                st.text(ref['notes'])
        if references:
            st.download_button('导出学习资料 JSON', json.dumps(references,ensure_ascii=False,indent=2),
                               file_name='learning_references.json', mime='application/json')

    with st.expander('保存更多后台观看数据'):
        st.caption('用于尚未自动采集的详情指标。时长以秒、比例以百分数填写；未获取字段使用 null。扩展数据可保存流量来源、受众分布、逐秒留存等原始结构和单位。')
        from src.services.video_service import get_videos
        works = {r['video_id']: r for r in get_videos(account_uuid=account_uuid,limit=10000) if r.get('video_id')}
        for row in snapshots:
            works.setdefault(row['video_id'],row)
        if works:
            with st.form(f'watch_details_{account_uuid}'):
                video_id = st.selectbox('关联已发布作品', list(works), format_func=lambda v: works[v]['title'])
                period = st.selectbox('统计口径', ['lifetime', 'daily', 'range'],
                                      format_func=lambda v: {'lifetime':'累计','daily':'单日','range':'指定区间'}[v])
                start = st.text_input('统计开始日期（累计留空，其他填 YYYY-MM-DD）')
                end = st.text_input('统计结束日期（单日与开始日期相同）')
                source = st.text_input('后台页面链接', value='https://creator.douyin.com/creator-micro/content/manage')
                values = st.text_area('指标 JSON', value=json.dumps(dict.fromkeys((*METRICS,*RETENTION,*WATCH_FIELDS)), ensure_ascii=False, indent=2),height=240)
                details = st.text_area('扩展观看数据 JSON', value='{}')
                evidence = st.text_area('原始页面数据 / 备注')
                if st.form_submit_button('追加观看数据快照', disabled=not can_edit):
                    try:
                        from src.platform_adapter.models import VideoItem
                        payload = json.loads(values)
                        extended = json.loads(details)
                        if not isinstance(payload,dict) or not isinstance(extended,dict):
                            raise ValueError('请填写 JSON 对象')
                        allowed = set((*METRICS,*RETENTION,*WATCH_FIELDS))
                        if set(payload) - allowed:
                            raise ValueError('未定义字段请放入扩展观看数据，避免误认指标单位')
                        for key, value in payload.items():
                            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or value < 0):
                                raise ValueError(f'{key} 必须为非负数或 null')
                            if value is not None and (key in ('completion_rate','bounce_2s_rate','watch_5s_rate','avg_watch_percent')) and value > 100:
                                raise ValueError(f'{key} 应为 0—100 的百分数')
                            if value is not None and key in (*METRICS,'follower_count','unique_viewers','impression_count','profile_visit_count') and not float(value).is_integer():
                                raise ValueError(f'{key} 是计数，必须填写整数')
                        payload.update(_details=extended,_raw_metrics=json.loads(values),_evidence=evidence,
                                       _source='creator_manual_entry',_period=period,_period_start=start,
                                       _period_end=end,_source_url=source)
                        work = works[video_id]
                        record_snapshot(VideoItem(account_uuid=account_uuid,video_id=video_id,title=work['title'],
                            publish_time=work.get('publish_time'),creator_metrics=payload))
                        st.success('新快照已保存，旧数据保留。')
                        st.rerun()
                    except (ValueError,TypeError) as exc:
                        st.error(str(exc))
        else:
            st.info('先同步作品，随后可按作品保存后台观看数据。')

    with st.expander('生产流程改进实验'):
        st.caption('把数据观察转化为可验证的生产改动，例如调整前2秒信息、冲突出现时间或镜头节奏。记录基线和候选版本，后续回填结果。')
        evidence_rows = snapshot_history(account_uuid)
        evidence_labels = {r['id']: f"#{r['id']} · {r['title'][:30]} · {r['collected_at']} · {r['period']}" for r in evidence_rows}
        refs = {r['id']:r['title'] for r in references}
        with st.form(f'production_experiment_{account_uuid}'):
            title = st.text_input('实验名称')
            selected = st.multiselect('观看数据证据', list(evidence_labels), format_func=evidence_labels.get)
            selected_refs = st.multiselect('学习参考视频', list(refs), format_func=refs.get)
            hypothesis = st.text_area('数据观察与待验证假设')
            change = st.text_area('下一版生产流程具体改动')
            evaluation = st.text_area('对比方法与目标指标（注意样本量、发布时长和统计口径）')
            baseline = st.text_input('基线作品 / 剧本 / 流程版本')
            candidate = st.text_input('候选作品 / 剧本 / 流程版本')
            if st.form_submit_button('保存改进实验', disabled=not can_edit):
                try:
                    save_experiment(account_uuid,title=title,hypothesis=hypothesis,proposed_change=change,
                        evaluation=evaluation,snapshot_ids=selected,reference_ids=selected_refs,
                        baseline_version=baseline,candidate_version=candidate)
                    st.success('已保存，视频制作页可查看和导出。')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        render_experiments(account_uuid, can_edit)


def render_experiments(account_uuid, can_edit=False):
    for plan in list_experiments(account_uuid):
        st.markdown(f"**实验 #{plan['id']} · {plan['title']} · {plan['status']}**")
        st.text(plan['hypothesis'])
        st.text('生产改动：' + plan['proposed_change'])
        st.text('评价方法：' + plan['evaluation'])
        st.caption(f"基线：{plan['baseline_version']} · 候选：{plan['candidate_version']}")
        packet = experiment_packet(account_uuid,plan['id'])
        st.download_button('导出生产改进依据',json.dumps(packet,ensure_ascii=False,indent=2),
            file_name=f"production_experiment_{plan['id']}.json",mime='application/json',key=f"experiment_export_{plan['id']}")
        if can_edit:
            with st.form(f"experiment_outcome_{plan['id']}"):
                statuses = ['待验证','试验中','保留改动','不采用']
                status = st.selectbox('实验进度',statuses,index=statuses.index(plan['status']))
                result = st.text_area('对比结果及生产决策',value=plan['outcome'])
                if st.form_submit_button('保存实验结果'):
                    try:
                        record_outcome(account_uuid,plan['id'],status,result)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        elif plan['outcome']:
            st.text(plan['outcome'])
