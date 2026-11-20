# v32：任务模式与提示要求绑定的FL2VA调用配方验证

本轮针对实际调用差异和精确对白区间观察修流程。root查看五路对齐证据后确认：旧Seedance/raw H3的第二句给哥哥，spatial A和C都给弟弟近景；不能把它定为C新回归。工程方向由root依据证据选择，不伪造用户选定baseline。

v32恢复曾实际完整运行的FL2VA/I2V single-first调用配方，让首图同时进入Qwen视觉和视频VAE；停止视频端混用五独立参考槽、AddGuide与B英文重写。**这不是已证明Guide导致错误，也不是承诺已修好口型。** S01仍采用A已审canonical首图，非旧Seedance JPEG，因此不是完全复现旧视频。

独立root：`data/video_generation/h3_legacy_call_restore_20261108_v1`。旧raw、Ref2VA、A/B/C的PLAN、授权、消耗、未知记录及原视频全部保留。新的4正式视频/0probe是工程边界，非用户逐字数额。

## 输入与确定性文字适配

`USER_AUTHORIZATION.json`使用 `h3_legacy_call_restore_authorization/v32`，绑定原A_SPEC、旧raw PLAN和冻结调用差异审计；记录用户原话、root工程选择和精确对齐证据。prepare只读这些来源，不请求模型或服务。

四段从A的源稿进入编译器，只允许六类明确文字替换：具名参考图改为首图承接、映射标题改为首图人物/服装说明、三个Picture人物前缀改成首图中的人物，S01起点的参考措辞也改成首图。角色、衣服、动作全文、神情、时间窗、10句原对白/心声和“纯剧情影像、通过表演和声音传达”条款保留。

没有用模型再编写，没有加统一固定机位，也没有在本版本加逐句主体近景说明。每次编辑保存原文/新文、原始字符和UTF-8位置、编译后位置及源/结果SHA；逆向重放必须逐字节恢复原A稿。未识别的Picture/参考措辞会拒绝，不默默删除。

`PROMPTS_READING.md`为root审阅四稿；`prompts/Sxx.audit.json`为可逆审计。此前上游五张人物/房间资产仍记在PLAN的 `upstream_asset_references` 以供追溯，**不是视频请求的输入槽**。

## 实际调用图合同

每段模板取旧raw该段真实 `REQUEST.json`、`workflow_api.json` 与成功 `HISTORY.json`，要求请求图/历史等价、原生ID对应。保留每段实际的FL2VA权重、Qwen encoder、视频/音频VAE、sampler、scheduler、12steps、24fps、362帧、736×1312和seed2026110700—03。

构图仅改变正文、`ref_scene`首图文件路径及四个输出scope。条件节点始终为 `MiniMaxH3ImageToVideo`，first_frame接 `ref_scene`；没有last_frame、Ref2VA、AddGuide或独立五图槽。S01复制原A canonical首图的原PNG字节；S02—04只复制本次上一段实际成功原生last，不能用旧段尾帧或计划末图替换。

## 文件合同

|文件|关键字段|
|---|---|
|PLAN|schema `h3_legacy_call_restore/v32`；authorization/三来源binding、原本地config/protected_pause；settings含width/height/frames/fps/initial_guide和四segments；segment含original_prompt、prompt、adaptation_audit、template、legacy_actual_call|
|STATE|id/status/prompt_id/plan_sha256；实际提交后graph_sha256；保存后result_sha256。plan_sha256是内容fingerprint，不冒称PLAN文件SHA|
|GRAPH_BINDING|id/scope/graph_sha256；guide原件来源；first_frame为新root内复制输入binding；input_name；source_prompt为实际编译正文；original_prompt为A源；task_mode及direct_reference_slots=0|
|CLAIM/REQUEST/RESPONSE|CLAIM在POST前冻结并绑定REQUEST SHA与graph SHA；REQUEST保留实际图及client_id；RESPONSE保留原生原ID，不替换|
|HISTORY|按原ID保存原生prompt/status/outputs；只允许已验证的denoise 1→1.0、fps 24→24.0等价解释，原图和原历史均保留|
|RESULT|schema v32、shot_id/prompt_id/graph_sha256、files四原件各path/sha256/source_path、native_metadata、guide/first_frame/source_prompt/original_prompt；technical_saved与内容批准分开|
|FINAL_RESULT|file binding、四native_ids、clock、assembly_inputs_sha256、task_mode、direct_reference_slots=0、diagnostic_preview=true、production_approved=false|

## 准入、收存与合成

prepare固定新root和新授权，不执行HTTP。真实提交另需 `LAUNCH_APPROVAL.json`：schema `h3_legacy_call_restore_launch_approval/v32`、reviewed_by=root_agent、approved_for_generation=true、diagnostic_only=true、plan和authorization两binding、baseline_selection_by=root_agent；selection_basis是绑定列表，至少包含授权中的call_difference_audit和selection_evidence。没有 `user_baseline_confirmed` 要求或假记录。

审批还必须有 `execution_sources={executor:binding(本模块),cli:binding(新CLI)}` 和 `cpu_acceptance:binding(data/qa/h3_legacy_call_restore_v32_20261108/ACCEPTANCE.json)`。每次新dispatch读取当前源码与验收SHA，路径必须精确匹配，拒绝文件变化；该门只在新提交前检查，不能阻止已知原ID收存。root在代码和CPU验收稳定后填写，程序不会自造通过审批。

CLI：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/run_h3_legacy_call_restore_v32.py prepare
.venv/Scripts/python.exe -X utf8 scripts/run_h3_legacy_call_restore_v32.py status
```

execute只在root完成四稿、代码与真实上游收存审核后唯一启动；须等C/S02原89517528收存及旧worker退出，当前本文不发起执行。

单runner锁、每步运行锁、原有两层GPU租约及队列/本地服务路径核对仍在。CLAIM无原生ID为unknown，不能盲重派；已有原ID继续跟踪。暂停只阻止新POST，源稿/授权变化不阻止原ID收存。四原件从原生输出严格验路径、SHA、几何和声音，技术失败与语义缺陷均保留，不自动语义重拍。

四段成功保存后自动CPU合成。复用v30的实际输入时钟核查及原AV拼接纯函数，输出1448帧、60.333333秒、48kHz/2,896,000样本，音视频起点0。CPU合成与程序测试不能当作演员、声纹、口型或完整剧情验收，后续由独立CPU QA和root实际看图/对齐审核。
