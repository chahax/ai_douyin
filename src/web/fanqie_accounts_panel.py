"""Authenticated UI for persistent Fanqie environments and explicit identity binding."""
import json
import sqlite3
from contextlib import closing
import streamlit as st
from src.operations_accounts.fanqie_account_control import FanqieAccounts, launch_worker
from src.web.components.auth import get_current_user, get_current_role, has_permission


def require_admin():
    user = get_current_user()
    if not user or not has_permission(get_current_role(), "admin"):
        raise PermissionError("仅登录的管理员可操作番茄账号环境")
    return user


def mutate(accounts, action, **values):
    user = require_admin()
    if action.startswith('workspace_'):
        from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace
        workspace=PromotionWorkspace(accounts=accounts)
        methods={'workspace_sync':'sync','workspace_apply':'apply','workspace_migrate':'migrate',
            'workspace_register':'register_candidate','workspace_bind':'bind_candidate','workspace_review':'record_review',
            'workspace_prepare_publish':'prepare_publish','workspace_dispatch_publish':'dispatch_publish',
            'workspace_attach':'attach_publication','workspace_recover':'recover_publish_receipt',
            'workspace_metadata':'request_publication_metadata',
            'workspace_prepare_backfill':'prepare_backfill','workspace_authorize_backfill':'authorize_backfill',
            'workspace_dispatch_backfill':'dispatch_backfill','workspace_reconcile':'reconcile_backfill'}
        if action not in methods:raise ValueError('不支持的工作台操作')
        return getattr(workspace,methods[action])(**values)
    if action == "create":
        return accounts.create(values["label"], values["douyin_account"])
    if action == "open":
        return launch_worker(accounts.queue(values["resource"]), accounts)
    if action == "close":
        return accounts.request_close(values["command"])
    if action == "confirm":
        return accounts.confirm(values["command"], values["identity"], user)
    if action == "catalog":
        return launch_worker(accounts.queue(values["resource"], "fanqie_catalog"), accounts)
    if action == "book":
        return launch_worker(accounts.queue(values['resource'], 'fanqie_book_inspect',
            book_name=values['book_name'], chapters=0), accounts)
    raise ValueError("不支持的账号操作")


def render_page():
    if not get_current_user():
        st.info("请先登录系统。")
        return
    st.title("番茄账号")
    st.caption("番茄与抖音分别登录、分别确认身份。专属目录保存登录会话；不会读取或保存账号密码。")
    accounts = FanqieAccounts()
    if not accounts.installed():
        st.warning("番茄账号管控尚未部署，请先完成数据库迁移。")
        return
    admin = has_permission(get_current_role(), "admin")
    try:
        if admin:
            with closing(sqlite3.connect(accounts.douyin_db.as_uri() + "?mode=ro", uri=True)) as db:
                keys = [r[0] for r in db.execute("SELECT account_key FROM account_runtime_bindings WHERE platform='douyin' AND status='active'")]
            with st.expander("登记专属环境"):
                target = st.selectbox("关联抖音运营账号", keys, index=None)
                label = st.text_input("环境名称", "番茄小说专属环境")
                if st.button("登记环境", disabled=not target):
                    mutate(accounts, "create", label=label, douyin_account=target)
                    st.rerun()
        envs = accounts.list()
        if not envs:
            st.info("尚未登记番茄环境。")
            return
        selected = st.selectbox("专属环境", [e["resource_id"] for e in envs], format_func=lambda key: next(e["label"] for e in envs if e["resource_id"] == key))
        env = accounts.get(selected)
        target = accounts.check_association(env)
        st.caption("关联抖音运营账号：" + target["account_key"] + " · " + target["platform_identity_key"])
        st.caption("固定浏览器目录：" + env["profile_dir"])
        binding = accounts.bindings().get(selected)
        st.write("已绑定身份：" + binding["platform_identity_key"] if binding else "尚未确认番茄真实身份；业务读取与回填不会执行。")
        command = accounts.latest_command(selected)
        if command:
            st.write(f"原任务：{command['command_id']} · {command['state']}")
            if command.get("error_code"):
                st.warning(command["error_code"])
            if (command.get("result") or {}).get("reason"):
                st.warning(command["result"]["reason"])
            probe = accounts.folder(command["command_id"]) / "LATEST_PROBE.json"
            if probe.is_file():
                value = json.loads(probe.read_text(encoding="utf-8"))
                if value.get("verified"):
                    st.info("窗口识别到身份：" + value["platform_identity_key"] + "。请核对后保存关闭，再确认绑定。")
                elif value.get("challenge"):
                    st.warning("平台要求验证，请在这个专属窗口手动完成。")
        if st.button("刷新状态"):
            st.rerun()
        if admin:
            if st.button("打开／复用专属登录窗口"):
                mutate(accounts, "open", resource=selected)
                st.rerun()
            if command and command["kind"] == "fanqie_login" and command["state"] == "running":
                if st.button("保存会话并关闭原窗口"):
                    mutate(accounts, "close", command=command["command_id"])
                    st.rerun()
            if not binding and command and command["kind"] == "fanqie_login" and command["state"] == "succeeded":
                identity = command["result"]["identity"]
                confirmed = st.checkbox(f"我确认 {identity} 是要关联此抖音运营账号的番茄账号")
                if st.button("确认绑定", disabled=not confirmed):
                    mutate(accounts, "confirm", command=command["command_id"], identity=identity)
                    st.rerun()
            if binding and st.button("核验身份并读取书籍目录"):
                mutate(accounts, "catalog", resource=selected)
                st.rerun()
            if binding:
                book_name = st.text_input('要分析的准确书名', key='fanqie_full_book_name')
                st.caption('获取该书全部可读章节，逐章保存进度；付费、权限和验证码不会绕过。采集完成后再分批分析选段。')
                if st.button('获取全部可读章节', disabled=not book_name.strip()):
                    mutate(accounts, 'book', resource=selected, book_name=book_name.strip())
                    st.rerun()
        render_workspace(accounts,selected,admin=admin)
        st.caption("登录身份核验有效期5分钟。过期需在原环境重新核验；未知任务保留原ID，不能反复开窗。")
    except Exception as exc:
        st.error(str(exc))


def _workspace_result(value):
    if isinstance(value,dict) and value.get('status')=='blocked_existing_command':
        st.warning('原任务仍未结束，未新增或派发本次请求。请先完成或核对原窗口任务：'+value['command_id'])
    elif isinstance(value,dict) and (value.get('application_status')=='outcome_unknown'
            or value.get('backfill_status')=='outcome_unknown' or value.get('requires_read_only_sync')):
        st.warning('平台结果仍待核对，请同步或只读核验原记录，未自动重新提交。')
    elif isinstance(value,dict) and value.get('confirmed') is True:
        st.success('平台结果已核对完成。')
    else:st.info('操作记录已保存。请刷新查看原任务及业务结果；登记或排队不表示平台已完成。')


def _workspace_action(accounts,action,**kwargs):
    try:
        value=mutate(accounts,action,**kwargs)
        if action=='workspace_attach' and isinstance(value,dict) and 'path' in value:
            st.session_state['fanqie_workspace_publication_handoff']=value['path']
        if action=='workspace_metadata' and isinstance(value,dict) and value.get('command_id'):
            st.session_state['fanqie_workspace_metadata_'+kwargs['candidate_id']]=value['command_id']
        if action=='workspace_prepare_backfill' and isinstance(value,dict) and value.get('binding_uuid'):
            st.session_state['fanqie_workspace_backfill_id']=value['binding_uuid']
            st.session_state['fanqie_workspace_manifest_sha']=value['manifest']['sha256']
        _workspace_result(value)
        return value
    except Exception:
        st.warning('当前条件尚不齐全，操作未完成。请检查推广任务、对应素材与原发布凭据，原记录已保留。')


def prepared_metadata_matches(candidate,metadata,task):
    prepared=candidate.get('prepared_publication') or {}
    request=prepared.get('request') or {}
    selection=prepared.get('promotion',{}).get('selection_key',prepared.get('promotion',{}).get('row',{}).get('platform_task_id'))
    return (bool(prepared) and selection==task
        and all(request.get(k)==v for k,v in metadata.items()))


def render_workspace(accounts,resource,*,admin):
    from pathlib import Path
    from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace,ref
    workspace=PromotionWorkspace(accounts=accounts)
    state=workspace.status(resource)
    st.subheader('小说推广工作台')
    st.caption('同步推广任务、关联本地素材、确认发布资料，再使用原发布凭据准备回填。各步骤独立确认，不自动重传。')
    douyin=state.get('douyin_status') or {}
    if not douyin.get('available'):
        st.warning('关联抖音账号状态暂无法核对，不能据番茄登录状态认为可以发布。')
    elif douyin.get('waiting_original_manual_window'):
        st.warning('请先完成并关闭原抖音处理窗口，再按账号管理原流程完成身份核验；本工作台不会自动解除暂停。')
    elif douyin.get('waiting_original_identity_check'):
        st.warning('关联抖音账号仍暂停或待核验。请先在原账号管理流程处理，本工作台不会自动恢复。')
    else:st.caption('关联抖音控制状态已读取，实际发布仍须通过原账号管控与身份核验。')
    if douyin.get('active_commands'):
        st.dataframe([{'原抖音任务ID':c['command_id'],'类型':c['kind'],'状态':c['state'],'异常':c.get('error_code')}
                      for c in douyin['active_commands']],hide_index=True)
    st.markdown('[前往抖音账号管理](/douyin-accounts)')
    command=state.get('original_command') or {}
    if command.get('state') in {'queued','running','paused','waiting_human','outcome_unknown'}:
        st.warning('原账号任务尚未结束：'+command['command_id']+'。新业务操作可能被保留等待，不会重复打开窗口。')
    business=command.get('result') or {}
    if business.get('requires_read_only_sync') or business.get('requires_read_only_reconciliation'):
        st.warning('原提交结果仍待核对。任务处理已结束不等于业务成功，请同步或只读核验。')
    rows=state.get('promotion_rows',[])
    if rows:
        names=dict(book_name='书名',book_id='书籍ID',alias='推广词',publish_type='发文类型',promotion_path='推广路径',
            alias_status='推广词状态',book_status='书籍状态',platform_task_id='平台任务ID',alias_id='推广词ID',
            valid_until='有效截止',status='资料状态',pending_fields='待补资料')
        if state.get('snapshot_schema')=='fanqie_promotion_snapshot/v2':
            names={k:val for k,val in names.items() if k not in ('platform_task_id','alias_id','promotion_path')}
            names.update(native_kind='原生记录类型',native_record_id='平台推广记录ID',workflow_label='推广方式')
        st.dataframe([{label:r.get(k) for k,label in names.items()} for r in rows],hide_index=True)
    else:st.info('尚无已核对的推广任务快照。先同步；字段缺失的任务会显示待补齐。')
    if state.get('ledger_unavailable'):
        st.warning('业务台账当前无法读取，暂不执行写入或迁移。请等待占用解除或核对服务状态后刷新，原记录已保留。')
        return
    if admin and st.button('同步推广任务',key='fanqie_workspace_sync'):
        _workspace_action(accounts,'workspace_sync',resource=resource)
    if admin and st.button('同步原生别名推广身份',key='fanqie_workspace_sync_native'):
        _workspace_action(accounts,'workspace_sync',resource=resource,snapshot_version='v2')
    if not admin:return
    with st.expander('申请准确书籍的AIGC推广词'):
        with st.form('fanqie_workspace_apply'):
            book_id=st.text_input('平台书籍ID');name=st.text_input('准确书名')
            alias=st.text_input('本次推广词');path=st.text_input('平台实际提供的推广路径')
            st.caption('发文类型固定为AIGC。系统会先核对已有任务，不自动改书、改词或换路径。')
            statement=st.text_input('本次申请确认说明')
            agree=st.checkbox('确认上述书籍、推广词和路径，允许提交这一次申请')
            if st.form_submit_button('确认并登记申请',disabled=not agree):
                _workspace_action(accounts,'workspace_apply',resource=resource,book_id=book_id,book_name=name,
                                  alias=alias,promotion_path=path,user_statement=statement)
    if state.get('migration_required'):
        st.info('素材与回填台账尚未部署或尚未通过结构检查。部署会先保存一致性备份。')
        with st.expander('部署台账扩展'):
            backup=st.text_input('新的项目data备份目录',key='fanqie_workspace_backup')
            if st.button('备份后部署台账扩展',disabled=not backup):
                _workspace_action(accounts,'workspace_migrate',backup_directory=backup)
        return
    with st.expander('登记已有本地视频候选'):
        with st.form('fanqie_workspace_register'):
            handoff=st.text_input('候选交接工件路径');provenance=st.text_input('小说来源证据路径')
            technical=st.text_input('同一视频技术审核路径')
            account=accounts.check_association(accounts.get(resource))['account_key']
            st.caption('关联抖音运营账号：'+account+'。登记不会自动通过内容审核或发布。')
            if st.form_submit_button('登记待审核素材'):
                try:_workspace_action(accounts,'workspace_register',handoff=ref(handoff),provenance=ref(provenance),
                    technical_review=ref(technical),account_key=account)
                except (OSError,ValueError):st.warning('请提供项目中存在且对应同一视频的工件。')
    candidates=state.get('candidates',[])
    if not candidates:st.info('尚无本地候选素材，先登记已有视频。');return
    st.dataframe([{k:c.get(k) for k in ('candidate_id','book_name','task_id','video_job_id','user_review_recorded',
                                      'publication_prepared','dispatch_state','publication_command_state','publication_command_error','command_id','publish_id')} for c in candidates],hide_index=True)
    cid=st.selectbox('候选素材',[c['candidate_id'] for c in candidates],
        format_func=lambda value:next(c['book_name']+' · '+value[:8] for c in candidates if c['candidate_id']==value),key='fanqie_workspace_candidate')
    if st.session_state.get('fanqie_workspace_active_candidate')!=cid:
        for name in ('fanqie_workspace_publication_handoff','fanqie_workspace_backfill_id','fanqie_workspace_manifest_sha'):
            st.session_state.pop(name,None)
        st.session_state['fanqie_workspace_active_candidate']=cid
    candidate=next(c for c in candidates if c['candidate_id']==cid)
    if Path(candidate['media']['path']).is_file():st.video(candidate['media']['path'])
    options=state.get('promotion_options') or []
    task_ids=[option['key'] for option in options]
    task=st.selectbox('已完整同步的平台推广任务',task_ids,index=None,
        format_func=lambda value:next(option['label'] for option in options if option['key']==value),key='fanqie_workspace_task')
    selected={'promotion_key':task} if state.get('snapshot_schema')=='fanqie_promotion_snapshot/v2' else {'platform_task_id':task}
    if st.button('绑定准确推广任务',disabled=not task):
        _workspace_action(accounts,'workspace_bind',candidate_id=cid,resource=resource,**selected)
    with st.expander('确认素材和发布资料'):
        review=st.text_input('观看该视频后的确认说明',key='fanqie_workspace_review')
        accepted=st.checkbox('我已观看并接受本视频作为发布素材，保留已知问题记录',key='fanqie_workspace_accepted')
        if st.button('记录本人素材确认',disabled=not accepted):
            _workspace_action(accounts,'workspace_review',candidate_id=cid,user_statement=review)
        title=st.text_input('发布标题',key='fanqie_workspace_title')
        description=st.text_area('发布说明',key='fanqie_workspace_description')
        tags=st.text_input('对应标签（逗号分隔）',key='fanqie_workspace_tags')
        metadata=dict(title=title,description=description,hashtags=[x.strip().lstrip('#') for x in tags.replace('，',',').split(',') if x.strip()],ai_generated=True,fictional_story=True)
        st.write('标题：'+title);st.write('说明：'+description);st.write('标签：'+'、'.join(metadata['hashtags']))
        st.write('声明：AI生成；虚构剧情。')
        st.caption('将声明AI生成与虚构剧情；发布仍使用原账号管控流程。')
        publish_statement=st.text_input('对上述资料及选中推广任务的发布授权说明',key='fanqie_workspace_pub_statement')
        authorized=st.checkbox('授权按所示资料准备并随后派发本次发布',key='fanqie_workspace_pub_authorized')
        if st.button('固定本次发布资料',disabled=not (authorized and task)):
            _workspace_action(accounts,'workspace_prepare_publish',candidate_id=cid,resource=resource,
                              **selected,metadata=metadata,user_statement=publish_statement)
        if candidate['publication_prepared']:
            st.caption('已固定、实际将派发的发布资料：')
            fixed=candidate['prepared_publication']['request']
            st.write('标题：'+fixed['title']);st.write('说明：'+fixed['description'])
            st.write('标签：'+'、'.join(fixed['hashtags'])+'；AI生成；虚构剧情。')
            if not prepared_metadata_matches(candidate,metadata,task):
                st.info('当前输入或任务与已固定资料不一致，暂不派发。请核对上方实际发布资料。')
        if st.button('派发已授权发布',disabled=not (authorized and task and prepared_metadata_matches(candidate,metadata,task)
                and douyin.get('publication_ready') and candidate.get('publication_command_state')!='unavailable')):
            _workspace_action(accounts,'workspace_dispatch_publish',candidate_id=cid,resource=resource,**selected)
    with st.expander('原发布凭据与回填'):
        original=candidate.get('command_id')
        metadata_command=st.session_state.get('fanqie_workspace_metadata_'+cid)
        st.caption('使用当前素材已登记的原发布任务，自动读取链接与平台发布时间。')
        if st.button('同步该作品的真实发布时间',disabled=not original):
            _workspace_action(accounts,'workspace_metadata',candidate_id=cid)
            metadata_command=st.session_state.get('fanqie_workspace_metadata_'+cid)
        with st.expander('历史记录高级核对'):
            if st.checkbox('使用手工指定的历史发布记录',key='fanqie_workspace_history_override_'+cid):
                original=st.text_input('仅历史核对时指定原发布任务ID',original or '',key='fanqie_workspace_original_publish_'+cid)
                metadata_command=st.text_input('仅历史核对时指定原作品信息任务ID',metadata_command or '',key='fanqie_workspace_metadata_command_'+cid) or None
        if st.button('只读恢复原派发回执'):_workspace_action(accounts,'workspace_recover',candidate_id=cid)
        if st.button('核验并写回原发布凭据',disabled=not original):
            _workspace_action(accounts,'workspace_attach',candidate_id=cid,command_id=original,metadata_command_id=metadata_command or None)
        handoff_path=st.text_input('已核验发布交接工件路径',key='fanqie_workspace_publication_handoff')
        template=st.text_input('官方回填模板本地路径',key='fanqie_workspace_template')
        output=st.text_input('新的项目data回填准备目录',key='fanqie_workspace_output')
        if st.button('生成对应视频回填资料',disabled=not(handoff_path and template and output)):
            try:_workspace_action(accounts,'workspace_prepare_backfill',publication_handoff=ref(handoff_path),resource=resource,
                                  official_template=template,output_directory=output)
            except (OSError,ValueError):st.warning('请使用已核验的原发布交接工件与官方模板。')
        bid=st.session_state.get('fanqie_workspace_backfill_id','')
        sha=st.session_state.get('fanqie_workspace_manifest_sha','')
        with st.expander('历史回填高级核对'):
            bid=st.text_input('仅历史核对时指定回填记录ID',value=bid,key='fanqie_workspace_backfill_id')
            sha=st.text_input('仅历史核对时指定回填资料校验值',value=sha,key='fanqie_workspace_manifest_sha')
        statement=st.text_input('对该视频回填资料的授权说明',key='fanqie_workspace_backfill_statement')
        if st.button('授权上述回填资料',disabled=not(bid and sha and statement)):
            _workspace_action(accounts,'workspace_authorize_backfill',binding_uuid=bid,manifest_sha256=sha,user_statement=statement)
        if st.button('派发已授权回填',disabled=not bid):_workspace_action(accounts,'workspace_dispatch_backfill',binding_uuid=bid)
        if st.button('只读核对原回填结果',disabled=not(bid and sha)):
            _workspace_action(accounts,'workspace_reconcile',resource=resource,binding_uuid=bid,manifest_sha256=sha)
        if bid:
            try:
                current=workspace.backfill_status(bid)
                if current['confirmed']:st.success('平台回填已核对完成。')
                else:st.info('回填状态：'+current['business_status']+'。尚不能视为平台已完成。')
            except Exception:st.info('尚无可核对的该条回填记录，请检查ID。')
