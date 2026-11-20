# 显示原窗口与关窗竞态修复（2026-11-03）

用户反馈再次点击无反应，要求黑盒测试。本次查明线上新增停点：原显示请求 `b3bfb40b7c974e7cb27110466673d280` 在原 Chrome 关闭期间收到 RuntimeError，通用 actor 将其标为 outcome_unknown，导致用户随后登记的原人工开窗 `a247d742496f4186837af0ebd72760cf` 一直 queued。原人工 `2fb93a16408346329d31a48ecc05c3ad` 已由原 owner/gen21 原生关窗回执结清，closed_tab_id 与该显示请求完全一致。没有新的处理完成请求，不能说身份核验或养号已恢复。

## 行为修复

`reveal_manual_window` 的固定 RPC 只改变原窗口的位置/显示状态；RPC 异常现在返回已知的 `manual_display_unconfirmed` 失败，含义是未确认显示，不推断没有发生显示效果，也不调用新浏览器或恢复账号。原人工任务仍由独立关窗/身份门保护。原账号绑定、owner、代次、tab 检查保持。

历史未知显示请求仅在原 native close 证据可严格匹配时结清：read kind、固定 method/operation_profile/完整参数键集合、请求 SHA 重新计算相符、无游标；同账号/绑定/owner/代次的原 manual 已 succeeded，window_closed=true、identity_verified=false 且 closed_tab_id 相同。旧请求和原关窗回执完整写入独立 SQLite 审计表，再将显示请求记为 failed/manual_window_closed。发布、身份核验、其他 read、缺失关窗证据、改动请求、其他标签页均不适用，不清锁、不关闭异常、不放宽未知发布保护。

## 验证范围

- 本地专项验证显示 RPC 返回异常/超时/未确认时不会产生未知业务围栏；原 manual 保持；不泄露原异常内容。
- 正反用例验证上述历史证据门、审计与幂等；原发布或其他 read 不适用。
- 从线上仅读取本次 display/manual/queued 三条相关记录，在隔离 SQLite 中复现原队列受阻，再通过既有 owner 的队列 API 核验相同原开窗 ID 被 claim。没有真实浏览器/身份/播放操作，不把该回放称为线上整条养号测试。
- 首次测试 fixture 错误地对已存在 owner 再 acquire，被真实所有权门拒绝；原失败留存。改为代表原 live owner 的既有队列 API，生产所有权门不变。最终相关套件71项通过；上一轮86项通过/1个fixture失败的历史报告保留，套件有交集，不相加。

## 部署边界

检查点 `data/development_checkpoints/manual_display_close_race_20261103/`。原后台34744及wrapper31964均按 PID/create-time/命令绑定，确认无浏览器子进程及在途业务后，在 SQLite writer reservations 中审计结清唯一上述 display，再停止空闲旧服务、提交显示元数据、审计退出原 owner。账号暂停、原请求/维护任务、其他未知记录、发布锁均保持。通过既有交互式 Windows 任务 AI_Douyin_Streamlit 启动新后台29168，原人工请求 a247…60cf 在 gen22 开始执行。没有从隔离桌面启动 headed 后台。

线上实际验收应以检查点后续 LIVE_ACCEPTANCE.json 的窗口清单、原请求终态和 UI 可用状态为准；仅 running 不能作为开窗或养号成功。助手不代点处理完成；用户确认处理后，由原后台按登记请求核验，再看真实 playback 的播放条数/观看秒数。H3/8190、其他账号和已取消的 Codex 定时监控不变。

## 线上继续验收发现的两段接续问题

正常桌面已观察到原用户人工请求 a247…60cf 成功开窗（Chrome窗口30412166）；原显示未知已按原native关闭证据结清，旧快照留审计。新业务未据此放行。

暂停账号的原 maintenance 请求仍会被短暂 claim，再被 admission 退回；3.2秒80次只读样本中捕获4次 running，导致前端“继续”入口偶尔错误判 busy。新增 `paused_browser_claims`，在 browser writer reservation 之前仅读取账号控制状态；暂停、核验中或人工占用时，只让原人工/恢复/指定修复种类进入既有 admission，普通维护原ID保持 queued/handler_entered=0。原owner上在线安装元数据门后，80次样本全部 queued，updated_at 保持不变。18项队列/原ID回归及2项部署边界通过；后续完善对未来owner的覆盖，12项通过。此门不关闭浏览器、不恢复账号、不改锁/游标。

用户第一次实际点击完成，产生 `3000dfc187254ada839b92aa217ed611`，原身份核验通过，recovery b1f…6e3e succeeded。其后旧 refresh e6d…03a3 对应的原命令 bc9…e880 真正进入 handler，但 `_gate` 用历史队列的过期 lease 生成异常48/outcome_unknown，随后 dispatch 被内部暂停门以 BrowserControlDeferred 拒绝。原维护 maintenance:203936909e95475cbe5a2c931a8a87b6 在 published_data_sync 失败，0同步；challenge/navigation/feed证据为空，不能把这一 human_required 当平台验证码事实。原refresh已由自身reconcile按真实失败回执结清，link settled，旧失败未覆盖。

新增 `tracked_refresh_gate`：挂接原browser请求时，用冻结请求SHA、原命令状态、匹配的owner/代次/绑定、90秒心跳及从实际执行日志开始计的有界3600秒时间判断，不用历史排队lease否定新执行。排队、已暂停或终态待回填均只等待原请求；原请求未知、来源改变、owner失效等仍暂停并保留，不重派。14项真实临时SQLite回归通过，涵盖过期历史lease+原生新执行、原owner过期、原请求改变、真实未知与终态待回填。第一次测试因隔离module的相对import及未指定测试实例失败，已改绝对import与明确参数，原失败报告保留。

两个元数据门已在线装入 PID29168/gen22，保留当前原manual 720d2ef27af94db58ffeb03816573342 及Chrome，不重启后台。未来owner也应用暂停claim门；下次正常启动由永久源代码加载相同规则。TRACKED_GATE_INSTALLED/CLAIM_GUARD_INSTALLED记录实际加载。app.py和scheduler/ui.py的临时入口均撤去，ARM归档METADATA_GATE_APPLIED_V2，勿重跑部署脚本或旧原命令。

用户再次本人点击继续，新完成请求 `5a57aa007f474501b5c119554b323d01` 已登记；后续以 LATEST_PROGRESS.json / LIVE_ACCEPTANCE.json 的新鲜真实回执为准。旧播放901c…f21c中3条/213.78秒是历史失败轮的观看结果，不计成本次新一轮。

## 本次线上黑盒结果

`5a57…3d01` 已完成原身份核验，账号 active/revision37。新 refresh `973a1a3a3ce549b99212846f166feaea` / 原生维护 `maintenance:1459bf6e5b5c4f3287d122db06598ce4` 成功完成，同步1作品/1评论。新 playback `bb424fb6dcde4b99869185f1099b751d` / 管控 `3d443bc22fc141008d21a90abde21d48` 正在运行；最新完成卡片游标回执已确认本轮1条、实际12.35秒，尚非整轮终态。此为用户本人点击后的线上结果，不是模拟测试或历史播放数。

原研究 smart `9da69f1f155e4366a3346ed6c8dba12b` 另因 research_keywords_missing 受阻，异常50仍open，未擅自填写关键词或修改策略。账号01仍有旧异常35待处理，未恢复该账号。修复入口、临时ARM全部移除/归档；源码长期保留显示已知失败、原native关闭证据结算、暂停领取前门、挂接原执行寿命门。最终 LIVE_ACCEPTANCE.json 保存真实阶段与来源SHA，未创建新Codex定时监控。

收尾复核：同一新播放原命令仍running，无终态错误，完成卡片游标最新已确认2条/102.76秒；整轮尚未结束。
