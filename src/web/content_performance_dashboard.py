"""Creator performance collection and account-scoped analysis."""
import pandas as pd
import streamlit as st

# Streamlit can rerun this page while retaining the pre-upgrade service module
# in sys.modules. Refresh that module once when its new API is unavailable.
from src.services import content_performance as _performance
if not all(hasattr(_performance, name) for name in
           ('snapshot_history', 'WATCH_FIELDS', 'review_prompts', '_scope')):
    from importlib import reload
    reload(_performance)

from src.services.content_performance import latest_snapshots, analyze_snapshot, snapshot_history, WATCH_FIELDS


def render_content_performance():
    from src.operations_accounts import AccountProfileRepository, AccountBindingRepository, AccountRuntimeService
    from src.web.components.account_scope import select_account_scope
    from src.web.components.auth import has_permission, get_current_role

    st.subheader('视频内容表现分析')
    repository = AccountProfileRepository()
    profiles = repository.list_active()
    if not profiles:
        st.info('请先在抖音账号中创建并绑定账号。')
        return
    account_uuid = select_account_scope(profiles, key='performance_account_scope', allow_all=False)
    profile = next((p for p in profiles if p.account_uuid == account_uuid), None)
    if profile is None:
        st.info('选择运营账号后查看作品数据。')
        return
    binding = next((b for b in AccountBindingRepository(repository.db_path).list_all()
                    if b.account_key == profile.account_key), None)
    st.link_button('打开抖音内容管理', 'https://creator.douyin.com/creator-micro/content/manage')
    st.caption('自动采集使用该账号专属环境并核验身份；普通网页链接使用当前浏览器登录账号。')
    if st.button('采集视频后台数据', key='collect_creator_metrics',
                 disabled=not has_permission(get_current_role(), 'admin') or not binding or binding.status != 'active'):
        adapter = None
        try:
            from src.platform_adapter.douyin_adapter import DouyinAdapter
            runtime = AccountRuntimeService()
            context = runtime.resolve(profile.account_key)
            with runtime.operation_lease(context, operation='creator_metrics', daily_limit=100,
                                         cooldown_seconds=60, lock_seconds=600):
                try:
                    adapter = DouyinAdapter(session=context.create_browser_session(headless=True), runtime_context=context)
                    with st.spinner('核验账号并采集作品指标…'):
                        result = adapter.sync_videos(page_limit=5)
                    if result.success:
                        st.success(f'已采集 {len(result.videos)} 条作品。最多采集 100 条，不代表完整作品列表。')
                    else:
                        st.error(result.message)
                finally:
                    if adapter:
                        adapter.close()
        except Exception as exc:
            st.error(f'采集未完成：{exc}')
    snapshots = latest_snapshots(account_uuid)
    st.caption('单条作品累计指标，每次同步追加快照。定时账号刷新也会更新此处。未返回的数据保留为空。')
    if not snapshots:
        st.info('暂无后台指标快照。请点击采集，或等待已启用的定时账号刷新。')
        history = snapshot_history(account_uuid)
        if history:
            st.caption('已保存以下单日或区间数据，尚无累计快照；不同区间不合计。')
            st.dataframe(pd.DataFrame(history).drop(columns=['raw_metrics_json','metric_details_json','evidence']),
                         hide_index=True, width='stretch')
            import json
            st.download_button('导出已保存的观看数据',json.dumps(history,ensure_ascii=False,indent=2),
                               file_name='watch_history.json',mime='application/json')
        from src.web.production_learning_dashboard import render_learning
        render_learning(account_uuid, snapshots, has_permission(get_current_role(), 'editor'))
        return
    columns = st.columns(5)
    for col, key, label in zip(columns, ('play_count','like_count','comment_count','share_count','collect_count'),
                               ('后台播放量','后台点赞量','后台评论量','后台转发 / 分享','后台收藏量')):
        known = [r[key] for r in snapshots if r[key] is not None]
        with col:
            st.metric(label, f'{sum(known):,}' if known else '未采集')
            st.caption(f'覆盖 {len(known)}/{len(snapshots)} 条作品')
    st.caption('以上是创作者后台每条作品最新累计计数，不等于已同步的评论明细。覆盖不全时只合计已知值，不把缺失值当作零。')
    from src.web.production_insights import display_time
    st.caption('最近采集（北京时间）：' + display_time(max(r['collected_at'] for r in snapshots)))
    rows = []
    for item in snapshots:
        rates, note = analyze_snapshot(item)
        row = {'作品': item['title'], '作品ID': item['video_id'], '发布时间': item['publish_time'],
               '采集时间（北京时间）': display_time(item['collected_at'])}
        for key, label in [('play_count', '播放'), ('like_count', '点赞'), ('comment_count', '评论'),
                           ('share_count', '分享'), ('collect_count', '收藏')]:
            row[label] = item[key]
            if key in rates:
                row[label + '率(%)'] = rates[key]
        row['分析'] = note
        row['完播率(%)'] = item['completion_rate']
        row['2秒跳出率(%)'] = item['bounce_2s_rate']
        row['吸粉量'] = item['follower_count']
        row['来源'] = item['source']
        for key, label in WATCH_FIELDS.items():
            row[label] = item[key]
        rows.append(row)
    frame = pd.DataFrame(rows)
    st.dataframe(frame, hide_index=True, width='stretch')
    st.download_button('导出当前账号指标 CSV', frame.to_csv(index=False).encode('utf-8-sig'),
                       file_name=f'{profile.account_key}_performance.csv', mime='text/csv')
    st.caption('完播率与2秒跳出率来自成功匹配的作品卡片，未匹配项留空；平均观看时长尚未接入。留存率采用平台显示口径，不按播放量反推人数。')
    with st.expander('查看采集页面证据'):
        for item in snapshots:
            if item.get('evidence'):
                st.text(item['evidence'])
    with st.expander('观看数据复盘提示'):
        from src.services.content_performance import review_prompts
        st.caption('以下是依据当前指标提出的核查方向，不代表已经证明内容问题或改动有效。')
        for item in snapshots:
            st.text(item['title'])
            for prompt in review_prompts(item):
                st.write(prompt)
    with st.expander('历史观看数据与趋势'):
        by_id = {r['video_id']:r for r in snapshots}
        video_id = st.selectbox('查看作品历史', list(by_id), format_func=lambda v: by_id[v]['title'])
        history = snapshot_history(account_uuid,video_id)
        periods = sorted({(r['period'],r['period_start'],r['period_end']) for r in history})
        period = st.selectbox('历史统计口径', periods, format_func=lambda p: ' / '.join(p))
        selected = [r for r in history if (r['period'],r['period_start'],r['period_end']) == period]
        df = pd.DataFrame(selected)
        st.line_chart(df.set_index('collected_at')[['play_count','like_count','comment_count','share_count','collect_count']])
        st.line_chart(df.set_index('collected_at')[['completion_rate','bounce_2s_rate','watch_5s_rate']])
        st.caption('横轴为采集时间；累计计数和百分比单独绘制。不同统计区间分开查看，指标下降可能是平台修正。')
        st.dataframe(df.drop(columns=['raw_metrics_json','metric_details_json','evidence']), hide_index=True, width='stretch')
        import json
        st.download_button('导出该作品全部历史及原始指标', json.dumps(history,ensure_ascii=False,indent=2),
                           file_name=f'{video_id}_metric_history.json', mime='application/json')
        observation = st.selectbox('查看原始观看数据', selected, format_func=lambda r: f"#{r['id']} · {r['collected_at']}")
        st.json({'扩展指标':json.loads(observation['metric_details_json']),
                 '接口原始统计':json.loads(observation['raw_metrics_json'])})
    from src.web.production_learning_dashboard import render_learning
    render_learning(account_uuid, snapshots, has_permission(get_current_role(), 'editor'))
