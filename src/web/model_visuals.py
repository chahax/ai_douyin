"""Model relationship views sourced from runtime configuration or logged requests."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import streamlit as st

from src.web.components.flow_graph import flow_graph
from src.web.components.ui import page_header

CALLER_LABELS = {'agent_chat': '助手对话', 'scene_plan': '场景规划', 'script_gen': '脚本生成',
                 'tag': '内容标注', 'error_reviewer': '错误诊断', 'error_review': '错误诊断',
                 'humane_recorder': '记忆整理', 'investigate_problems': '问题调查',
                 'unknown': '未标注来源', '': '未标注来源'}


def safe_endpoint(value):
    """Do not display credentials, query parameters, or fragments in endpoint URLs."""
    try:
        url = urlsplit(value)
        if url.scheme not in {'http', 'https'} or not url.hostname:
            return '未配置有效地址'
        host = url.hostname
        if ':' in host:
            host = '[' + host + ']'
        if url.port:
            host += ':' + str(url.port)
        return urlunsplit((url.scheme, host, url.path, '', ''))
    except ValueError:
        return '未配置有效地址'


def configured_graph(settings, client):
    provider = {'ollama': '本地模型服务', 'openai_compatible': '兼容接口服务', 'mock': '模拟服务'}.get(client.provider_name, client.provider_name)
    model = '模拟响应' if client.provider_name == 'mock' else client.model_name
    channel = '即梦网页套餐' if settings.SEEDANCE_PROVIDER == 'dreamina_cli' else 'BytePlus 接口'
    video_model = settings.DREAMINA_MODEL_VERSION if settings.SEEDANCE_PROVIDER == 'dreamina_cli' else settings.SEEDANCE_MODEL
    rows = [
        [('文本需求','脚本、对话与分析请求'), (provider, '当前文本模型服务来源'),
         (model or '未配置模型', '运行时解析后的文本模型'), ('文本与工具建议','返回回答或工具调用建议')],
        [('配音文本','已确认的旁白或对白'), (settings.TTS_PROVIDER, '当前配置的配音服务'),
         ('音频素材','产出的语音供制作环节使用')],
        [('分镜与提示词','已确认的画面描述和参考素材'), (channel,'当前视频生成渠道'),
         (video_model,'该渠道配置的视频生成模型'), ('视频片段','生成结果仍需下载、检查与审核')],
    ]
    nodes, edges = [], []
    for row, items in enumerate(rows):
        for column, (label, intro) in enumerate(items):
            node_id = f'{row}-{column}'
            facts = [['用途', intro], ['配置范围', ['文本模型', '配音服务', '视频生成'][row]],
                     ['状态含义', '只读配置快照；未发起连接检测或模型调用。']]
            if row == 0 and column == 2:
                facts += [['超时上限', f'{settings.LLM_TIMEOUT_SECONDS} 秒']]
            nodes.append(dict(id=node_id, label=label, subtitle=['文本智能','声音制作','视觉生成'][row],
                              column=column, row=row, description=intro + '。点击只展示说明，不会发起生成。',
                              status='配置示意', facts=facts))
            if column:
                edges.append(dict(id=f'{row}-{column-1}:{node_id}', source=f'{row}-{column-1}', target=node_id,
                                  label=items[column-1][0] + ' → ' + label, status='配置关系', short_label='请求 / 结果',
                                  description=f'{items[column-1][1]}，衔接到{intro}。此线表示配置关系，不表示已验证连通。',
                                  facts=[['使用条件', '实际调用受账号、服务依赖、额度与审核要求约束。']]))
    return nodes, edges


def render_system_settings():
    from src.shared.config import settings
    from src.shared.llm_client import llm_client
    page_header('模型与系统设置', '了解文本、声音与视频模型分别负责什么，再查看当前配置。', icon='⌘', eyebrow='MODEL CONSTELLATION')
    nodes, edges = configured_graph(settings, llm_client)
    flow_graph(nodes, edges, key='system_model_graph', title='AI 能力连接图',
               description='三条独立能力路径：文本理解、声音制作、视觉生成。点击模型或连线展开介绍；当前展示配置，不代表在线或可用。')
    text_tab, voice_tab, video_tab = st.tabs(['文本模型设置', '配音设置', '视频模型设置'])
    with text_tab:
        provider = llm_client.provider_name
        a, b = st.columns(2)
        a.text_input('当前服务类型', value={'ollama':'本地 Ollama','openai_compatible':'兼容接口','mock':'模拟服务'}.get(provider,provider), disabled=True)
        b.text_input('当前文本模型', value='模拟响应' if provider == 'mock' else llm_client.model_name, disabled=True)
        endpoint = (llm_client._resolve_ollama_base_url() if provider == 'ollama' else settings.LLM_BASE_URL) if provider != 'mock' else ''
        st.text_input('服务地址', value=safe_endpoint(endpoint), disabled=True)
        st.caption(f'调用超时：{settings.LLM_TIMEOUT_SECONDS} 秒。这里展示实际文本服务使用的模型。')
    with voice_tab:
        st.text_input('配音服务', value=settings.TTS_PROVIDER, disabled=True)
        with st.expander('本地语音依赖'):
            st.text_input('语音工具目录', value=settings.GPT_SOVITS_SDK_ROOT or '未配置', disabled=True)
    with video_tab:
        a,b = st.columns(2)
        a.text_input('生成渠道', value='即梦网页套餐' if settings.SEEDANCE_PROVIDER == 'dreamina_cli' else 'BytePlus 接口', disabled=True)
        b.text_input('生成模型', value=settings.DREAMINA_MODEL_VERSION if settings.SEEDANCE_PROVIDER == 'dreamina_cli' else settings.SEEDANCE_MODEL, disabled=True)
        st.caption('生成后仍需检查一致性与审核结果，不能直接据此判断作品可发布。')
    st.info('这些设置由本地环境配置管理。修改后重启相关服务生效；本页仅查看，不提交生成任务。')


def usage_graph(rows):
    """rows are aggregate request records, including cache hits and rate limits."""
    nodes, edges, callers, models = [], [], {}, {}
    for row in rows:
        caller, model = row.caller or 'unknown', row.model or '未记录模型'
        if caller not in callers:
            callers[caller] = f'caller-{len(callers)}'
        if model not in models:
            models[model] = f'model-{len(models)}'
    for values, column in ((callers,0),(models,1)):
        for index,(name,node_id) in enumerate(values.items()):
            matching = [r for r in rows if (r.caller or 'unknown') == name] if column == 0 else [r for r in rows if (r.model or '未记录模型') == name]
            label = CALLER_LABELS.get(name, '扩展调用来源') if column == 0 else name
            count = sum(r.calls for r in matching)
            nodes.append(dict(id=node_id, label=label, subtitle=f'{count} 条请求记录', column=column,row=index,
                              description='业务来源与模型之间的请求记录关系。缓存命中与被限流的请求也可能在其中。',status='已记录',
                              facts=[['来源标识' if column==0 else '模型名称',name],['图中请求记录',str(count)],
                                     ['账面成本',f'${sum(float(r.cost) for r in matching):.4f}']]))
    for i,row in enumerate(rows):
        caller,model=row.caller or 'unknown',row.model or '未记录模型'
        edges.append(dict(id=f'usage-{i}',source=callers[caller],target=models[model],label=f'{CALLER_LABELS.get(caller,caller)} → {model}',
                          short_label=f'{row.calls} 条',description='该业务来源与模型的聚合请求记录，不表示每条请求都访问了外部模型。', status='历史请求',
                          facts=[['请求数',str(row.calls)],['缓存命中',str(row.hits)],['被限流',str(row.limited)],
                                 ['输入 / 输出词元',f'{row.in_tok} / {row.out_tok}'],['账面成本',f'${float(row.cost):.4f}']]))
    return nodes,edges
