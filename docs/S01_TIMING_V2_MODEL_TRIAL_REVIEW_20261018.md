# 新估时规范的首段真实模型测试与主审

用户要求“可以尝试把这个设置给模型重新输出第一段”。按[本次计划](S01_TIMING_V2_MODEL_TRIAL_PLAN_20261018.md)实际完成一次MiniMax首段、一次DeepSeek忠实整理/九维审核及一次实际SDK全文审核。当前结果为**7秒模型候选，原生final为revise，未生成视频**。

运行根为`data/narrative_pacing_production/20261018_timing_v2_S01`。[MiniMax原生首段](../data/narrative_pacing_production/20261018_timing_v2_S01/S01_NATURAL_DIRECTOR.md)不可变保存，以下为概述，不是助手修正后的新稿：

| 内部估时 | 对白 | 并行内容 |
|---|---|---|
| 0—3.9秒 | 周禾：“房间找好了。头三个月紧点，也能过。” | 女儿直接看父亲开口，父亲听着取票。 |
| 3.9—5.3秒 | 周明：“我没问这个。” | 看女儿，落票桌面，手不离票；女儿听。 |
| 5.3—7秒 | 周明：“票买好了。” | 推票松手与女儿随票意外、回看并行，完成即收。 |

模型估三句声音约3.8、1.1、0.9秒，最后声音约6.2秒结束。数字接近输入编辑候选，不证明已录音试读或实际视频自然度。完整v2profile与SHA确实进入全部三次真实请求，同一brief、单段前缀和消息参数可以从冻结材料重建；49秒v4仍明确标助手编辑候选，旧已通过完整稿只作背景。新范围仅S01，未改旧整片105—135秒硬范围或十轮停点。

DeepSeek第一审原生pass、issues=[]，忠实整理得到一份7秒SDK预览。最终审核原生revise，唯一minor为prompt混入“父亲0.1秒后接话”等内部硬时点。主审与独立子agent还发现：

1. MiniMax世界说明票已取出攥在手中，段首又在内袋握票，第一组再伸手取票；实际prompt仍有“手已在袋内→右手伸入”的歧义，须统一初态以免重复动作。
2. 第三组说末句结束同时完成推票松手，拍法说明又把同一动作放在声音后0.8秒完成。回看可以继续，但推票松手要有唯一完成点，不能重复占时；目前既不能证明全部尾窗必要，也不能断言7秒必然过长。

两处属director表述问题，extract与final均漏检。不能仅删0.1秒便标文本通过。原final把硬时点归compiler，主审纠正为extractor：SDK文本与原整理prompt逐字一致，编译没有新增文字。“到7秒”只是整段终点，本身不是小数硬时点；原判词不追改，另存[主审V2及独立结论](../data/narrative_pacing_production/20261018_timing_v2_S01/PRIMARY_REVIEW_V2.json)。初版主审误将原生minor标major，V2明确纠正并绑定初版；所有模型回执保持。

| 实际调用 | reported tokens |
|---|---:|
| MiniMax-M3自然稿 | 18549 |
| deepseek-flash整理/九维 | 21558 |
| deepseek-flash实际请求全文审查 | 37994 |
| 本轮3次 | 78101 |
| 继承后同源20次 | 383259 |

模型/端点与原冻结配置一致：MiniMax-M3位于`https://api.minimaxi.com/v1`，deepseek-flash位于`https://api.deepseek.com/v1`；SDK重试0，超时600秒。原20次/500000保持，调用剩余0，剩余116741 tokens不授权额外调用。本次无返修、运输重试或媒体；`STOP.json`保存停点。

所有REQUEST、CLAIM、RESPONSE和CALL_LEDGER不可变保存。每阶段重新核原生stop/content、唯一choice、无工具、同稿正文、请求身份和已知用量；三次全部已知。SDK预览重建与原整理相同，原生extract/final可从原请求复算。16个本次输入/代码冻结、37个前轮产物及旧历史文件核对不变。

五项离线安全检查通过：已知原生读取、重复阶段拒派、原回执篡改拒绝、未知用量保存停止、未知前序阻下游，见`data/qa/s01_timing_model_trial_v1/OFFLINE_CHECKS.json`。独立只读审查核实真实输入、冻结绑定与上述内容问题。当前仅交用户阅读比较的待修候选，没有视频质量批准或可续用尾帧。
