from pathlib import Path
import json
r=Path('data/creative_workflows/reusable_trial_20260927');s=json.loads((r/'state.json').read_text(encoding='utf-8'))
base=Path('data/production_trials/reusable_20260927')
result={
'schema':'reusable_production_trial_result/v1','decision':'failed_preproduction_acceptance',
'actual_run':str(r.resolve()),'source_brief':str((base/'brief.json').resolve()),
'review_scope':['actual_provider_text_outputs','original_character_images','original_background_image','asset_routes','video_template_executability','revision_cli','stage_receipt_provenance'],
'calls_started':s['calls_started'],'reported_tokens':s.get('reported_tokens'),'revision_rounds':s['revision_rounds'],'contract_repairs_used':s.get('contract_repairs_used'),
'configured_max_calls':s['max_calls'],'configured_max_revisions':s['max_revisions'],
'stop_reason':s.get('assistant_revision_error'),
'actual_new_video_generated':False,'new_image_generation_calls':0,'new_video_generation_calls':0,
'full_workflow_pass':False,'audio_voice_check':None,'lip_sync_check':None,
'checks_fixed_in_code':['case-insensitive production design receipt/artifact collision','original brief and asset library reload in revision CLI'],
'fix_regression_tests':{'passed':29,'failed':0,'report':str((base/'regression.xml').resolve())},
'unresolved':['second revision patch missing required B04 and has extra top-level item, malformed dialogue field; repair repeated invalid output','first revised SH03B offscreen dialogue still marked on-camera','palette support missing after both hands lowered','background geometry contradicts actual asset','required_tags invented rather than using supplied catalog, causing all assets to be regenerated','opening image prompts advance actions beyond start_state','asset-design revision input omits the assistant asset feedback','generic media execution and campaign adapter remain unconnected'],
'first_draft_design_call_receipt':'overwritten on Windows by artifact filename; source record not reconstructed',
'real_media_quality_verified':False,
'notes':'15 calls is usage, not price. Five nominal calls remain, but second revision attempt reached deterministic no-op stop and the configured two editorial rounds are consumed. No budget reset or synthetic approval.'
}
(base/'AUDIT_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report=f'''# 真实试生产审核结果：未通过生成前验收

这次从可替换简报启动了真实编剧/导演模型，实际审阅首稿、第一轮返修，并查看原始人物与场景图片。没有生成新视频，因此没有视频画面、声音或口型通过结论。

## 结果与用量

- 首稿85秒5镜；4镜超出当前4–15秒的生成器范围。
- 第一轮返修77秒9镜，时长拆分修复，但声音归属、道具、布局、资产复用和首帧动作仍有主要问题。
- 第二轮返修模型未按要求返回全部节拍：B04缺失、B05落在顶层item、dialogue为空字符串；结构修复返回同样内容，流程正确停止。无合格第二轮稿。
- 文本调用 {s['calls_started']}/{s['max_calls']} 次，服务回报 token {s.get('reported_tokens')}；技术修复 {s.get('contract_repairs_used')}/8，实质返修2/2。token不是人民币费用，没有编造费用。
- 新图片调用0，新视频调用0，未登记新视频失败预算，也未修改旧稿失败历史。

## 实际暴露的缺口

1. 执行限制反馈太晚：导演写完才发现多数镜头不能提交；需要在分镜阶段明确生成器时长与连续性限制。
2. 自动回核会漏检：画外林屿仍标画内，调色板在双手垂下后去向不明，背景右后窗仍与左上窗原图冲突。模型高分和空问题单不能替代实审。
3. 资产复用未闭环：设计加入大量库里没有的必需标签，三项都走向重新生成；返修资产阶段只接收简报/目录/剧本/分镜，没有接收针对资产的实际反馈，问题会重复。
4. 首帧设计会提前执行动作：人物在静态首图中已经跨门槛或走到凳旁，与start_state矛盾。
5. 通用任务包尚未接通实际生成和campaign回执适配；全部planned_cut镜头不能自动变成符合原始尾帧规则的续段。
6. 修复协议仍不稳定：第二轮漏节拍及额外顶层字段没有被模型修好。没有用手工补故事冒充自动通过。

## 已修复并验证

- 将阶段调用记录改名为director_production_design.json，与PRODUCTION_DESIGN.json分开，避免Windows不区分大小写造成覆盖。初稿已丢失的原调用记录不补造，保留事故事实。
- 正式返修CLI重新载入原创brief与资产库绑定，能够在同任务预算中恢复。
- 定向回归29项通过，并增加原调用记录保留与CLI恢复的检查。

## 审核证据

- FIRST_ACTUAL_REVIEW.md：首稿实际审核。
- REVISION1_ACTUAL_REVIEW.md：第一轮返修实际复审。
- ASSET_VISUAL_OBSERVATIONS.json：三张原始素材的实际看图观察。
- AUDIT_RESULT.json：结构化结果和本次停止原因。
- 原始模型响应与状态保留在data/creative_workflows/reusable_trial_20260927，第二轮无效响应也完整保留。

结论：已经验证前期生成、实际审核和失败停止确实能运行，但目前没有证明“只改简报即可稳定生成优质成片”。应先修复上游约束与资产反馈传递、补齐通用执行适配，再进行下一轮有明确预算的生产验证。
'''
(base/'AUDIT_REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps({k:result[k] for k in ('decision','calls_started','reported_tokens','new_video_generation_calls')},ensure_ascii=False))
