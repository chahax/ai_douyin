# H3 空间与尾帧承接实验执行器 v24

本模块是独立的诊断生产路线，不修改旧 v20/v21/v23 PLAN、资产资格、原 H3 暂停或账号后台。使用原本地8190服务和既有 Ref2VA 权重，无新增自定义节点。实际 GPU 提交由主代理统筹。

## 实验输入与边界

`src/content_factory/visual_spatial_delivery_v24.py`、`scripts/run_spatial_delivery_v24.py`。
新根 `data/video_generation/spatial_minute_experiments_20261107_v1/variants/{A,B,canary_A,canary_B}`。

- A/B正式档各4×362帧，736×1312、24fps、12步，原生声音，合计1448帧、60⅓秒。
- canary只有S01、124帧，288×512或384×672，约5.167秒；正文只保留原S01第一句，不把整段对白挤进5秒。
- 每镜5个独立参考槽：苏墨、叶南、叶西决与同一房间两视角。角色即使像素相同也不合并槽位。
- 新资产必须具名、绑定来源文件SHA与主代理实际参考审核；不把新空间图伪造为旧generation_refs/v6合格产物。
- 原4段来源与对白逐句核对：minute保留本段全部原句，probe只含第一句。主代理审核完整spec，变更需新命名空间。
- 语义问题记录在独立审核文件，保留原片并继续诊断成片，不把技术成功当内容批准。结果始终 `production_approved=false/publication=false`。

## 实际图接线

`ReferenceToVideo.conditioning` → `AddGuide.positive`，原视频latent → `AddGuide.latent`，实际图像及原VAE接入；frame_idx=0；AddGuide输出接BasicGuider。

首段使用明确审核过的initial_guide。后段必用**当前variant前一段已保存的原生last**，绑定前段RESULT、原ID及SHA，而非旧片尾帧或计划图。尺寸由本机AddGuide原生center-resize映射到输出画幅，原输入图不被覆写。

若某镜另有已审核end_guide，第二个AddGuide接在start之后，frame_idx=frames−1；不悄悄覆盖前段tail。当前不声称单帧锚定能完整传递运动速度或解决全部串人。

## Spec 与审核

`CANARY_A_SPEC_TEMPLATE.json`只为起草模板，有缺失SHA时不能提交。root写的正式spec包括：

- schema `spatial_h3_spec/v24`，variant/profile/width/height/frames/seed；
- authorization、parent_runner_plan文件绑定；
- references每项含reference_id、kind、entity_id、view、description、image(path/SHA)、provenance(path/SHA)、root_review(path/SHA)；
- initial_guide含image、root_review及原生native_result/role，或generated producer_receipt；
- segments含id、original_prompt、prompt，可有end_guide；
- config使用既有input/output/GPU锁路径与8190 URL，base_workflow必须文件绑定。

reference review为 `reviewed_by=root_agent,accepted_for_reference=true,image,entity_id,provenance`。guide review为 `reviewed_by=root_agent,accepted_for_guide=true,image`；新生成图还绑定producer_receipt。root spec approval为 `reviewed_by=root_agent,approved_for_generation=true,diagnostic_only=true,spec(path/SHA)`。

授权来自本轮完整用户请求；8个正式视频、2个小样是工程范围，不冒称用户给出的精确数字。所有同授权variant的CLAIM统一计数，unknown也占次，不以更换目录逃避。不给新调用伪造新批准。

## 运行与恢复

```powershell
.venv/Scripts/python.exe -B scripts/run_spatial_delivery_v24.py prepare --run data/video_generation/spatial_minute_experiments_20261107_v1/variants/canary_A --spec data/video_generation/spatial_minute_experiments_20261107_v1/CANARY_A_SPEC.json --approval data/video_generation/spatial_minute_experiments_20261107_v1/CANARY_A_ROOT_APPROVAL.json
.venv/Scripts/python.exe -B scripts/run_spatial_delivery_v24.py execute --run data/video_generation/spatial_minute_experiments_20261107_v1/variants/canary_A --poll-seconds 30 --max-seconds 21600
```

其他命令status、submit、poll、assemble、pause、resume。prepare/status不提交；execute独占RUNNER.lock，提交时使用既有GPU锁、服务路径检查、空队列检查与共享预算锁。CLAIM之前冻结实际graph/REQUEST；已知原ID仅收存；CLAIM有而response缺失就是unknown，绝不自动重发。仅CLAIM前的本地中断可复用已冻结REQUEST继续。

暂停和输入变化阻止新提交，已知在途原ID仍继续收存四原件与原history。原生失败/中断/unknown都停止，不当内容失败盲重试。`LOG.md/job_ids.txt`在提交时追加；RESULT保存来源SHA、实际首尾图、音视频元数据。不得同时启动两个execute。

正式四段齐后自动纯CPU合成 `DIAGNOSTIC_MINUTE_736x1312.mp4`。每段实际解码、源SHA和时钟检查；音频48k统一到每段724000个有效采样，最终2896000采样、AV起点0。合成前后核对原RESULT，已有无回执输出保留而不覆盖。

## CPU验证与真实验证区分

测试 `tests/test_visual_spatial_delivery_v24.py` 包括：明确profile/原对白、参考槽/角色/审核、真实AddGuide接线与首尾链、原ID恢复/未知不重派、共享预算、锁、暂停/输入变化继续收存、篡改拒绝，以及真实CPU ffmpeg/ffprobe四颜色夹具全链1448帧合成与重复execute无第五次模拟POST。

颜色夹具全在QA临时目录，不是模型生成、更不作为一分钟交付。真实模型状态只能看新variant原生ID及原产物，不能由CPU测试推断语义或画质通过。实际审核、采样和ASR由主代理独立执行。

## 本地 staging 配置边界补修

首次真实canary在POST前触发 `Config.__init__ unexpected gpu_lock_root`，当时没有CLAIM、REQUEST或原生ID，旧prepared计划和graph原样保留。初版33项把stage_input替换为记录器，漏测了真实Config接缝；该版源码/测试/XML/验收已逐字归档 `data/qa/spatial_v24/pre_stage_cfg_fix`，不能把初版33项当作真实节点成功。

现仅将视频执行配置投影到图像staging实际支持的service_url/input_root/output_root/timeout四字段；没有关闭Config规范化或SHA检查，也未改既有PLAN/spec/生成graph。新增3项真实本地stage_input边界测试，使用实际PNG、实际目标复制及SHA校验，覆盖5refs+start/end共7个目标、错误来源SHA、已存在目标冲突保留、错误发生在CLAIM/REQUEST/POST之前。最终同一文件36项回归以 `delivery_stage_cfg_release.xml` 为准，不把针对3项和旧33相加。此次是已知未提交计划的本地修复，不是重发未知模型请求。
