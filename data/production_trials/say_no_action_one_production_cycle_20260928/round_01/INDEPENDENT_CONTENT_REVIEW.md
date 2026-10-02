# 动作计划单轮生产独立审核

完整审阅锁定剧本、静态清单、动作计划原响应、派生时间轴和排时报告、DeepSeek原审及补证24项理由、终态。没有写人工通过，没有修改原模型计划，没有发起额外付费。

结果：4次真实文本调用、101,586 tokens，终态production_exception。计划结构首次通过；审核返回issues=[]，但覆盖证据不足，补证后仍未解决，未到人工gate。没有合格handoff。

## 已实际改善

- 初态正确：陈禾站立，文件夹桌面holder=none，拿取前提成立；B3放回清空holder，不再把owner当holder。无需针对这部分返工。
- 程序排时实际完成：B1动作5秒、对白5–9.014；B2动作2.5秒、对白2.5–5.086、保持4秒；B3抬眼0–1.5、保持1.5–3.5、软化放夹3.5–6.5、接受6.5–9.371；B4松肩0–2、道别2–4.3、走路4.3–7.3、坐下7.3–9.3。各拍有尾部余量，动作和hold未被压缩。
- 按程序计时单位四句为13/8/9/7，实际对白时长4.014/2.586/2.871/2.3秒，均在5单位/秒上限内。不能再按主观偏快要求返工，也不能据此宣称实际声音自然。
- B3两秒保持从抬眼完成后开始，之前漏掉的稳定对视已在实际计划中修复。

## 三个内容major，DeepSeek均漏报

**SH02/SH03视线重复。** B2 dialogue_performance写“her gaze lifts from the folder back up toward Chen He as she finishes”，typed末态却仍看文件夹。B3再操作从文件夹抬眼。审核continuity只采信typed末态，没检查对白表演自由文，因而错误给pass。需让B2保持看夹，唯一上抬留B3。

**SH03切点矛盾。** camera要求“cut on the moment the folder touches the desk surface”，此时接受对白尚未说，程序安排其在落夹后的6.5–9.371秒；cut_reason却要求接受说完才结束。如果遵循camera会截掉本镜关键接受。应保留整段到接受结束，不是增加硬切或改剧情。

**SH04空间动作不成立。** performance写“steps behind her chair, and sits down”，却只给gaze/affect/sit操作，没有合法座面前侧位置，可能穿椅背。必须明确到可坐侧再坐或直接从原椅前站位落座，不能靠程序posture=standing检查充当空间审查。

具体源路径及仅本地修订目标保存在LOCAL_REVISION_TARGETS.json。这是人工问题清单，不是伪造模型新稿，未应用到原计划。

## 审核接口与内容须分开

本轮DeepSeek原审和补证都给story_preserved=true、issues=[]。运行实际停止原因是v6对照证据缺少本镜正文/visible_performance/state_plan等必要覆盖，而非成功审批。引用ID有效性的最终核查由负责接口的agent完成；不能把有效ID自动等同充分覆盖或正确语义。

主agent以json.loads比较确认原review与补证对象完全相同，24项check无差异；先前关于reason改写的观察已撤回，不能用token差异推断语义改变。最终停止记录明确是覆盖不足。即使程序之后修好覆盖，以上三个内容问题仍应阻断。离线展开审核见INDEPENDENT_EXPANDED_REVIEW.json，其not_an_approval标记不能当通过。

## 未触发及未验证

局部planpatch没有在这轮实际付费链路触发：计划结构一次通过，内容审核尚未进人工gate就停下。其原稿hash、合并、缓存恢复仅离线测试通过，不能说已经靠真实生产补丁修好上述问题。

资产设计、首帧方案、联合审核、完整handoff均未到达；没有实际图片或视频声音/口型/表演审核。没有下一轮调用。
