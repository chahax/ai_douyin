# 快速上传检查转移：实施与主审

## 实际停点

本轮唯一发布6730f85e9f9b45bc9c0520f2e23c5cd3已知failed/upload_failed，post_id/URL为空、无新提交锁、未AI声明/发布/评论。日计数26已用，原控制active42/failures1、runtime lease为空。原日志与两分钟诊断保留，不将其回写为上传或发布成功。用户批准本次只追加一次发布，当前未新增额度或重传。

诊断文字先“检测中5%”，后“作品未见异常”，旧门漏过上传字节＋取消控件瞬态便永远不能形成完成证明。已增加独立的本次选文件后检测状态转移证明，保留旧传输证明分支。

## 实现和限制

新`src/shared/upload_check_transition.py`仅读渲染UI，worker私有WeakKeyDictionary保存原Page、document、URL/主frame导航代次、独立“快速检测”容器和原状态叶节点、原可操作“重新上传”控件。成功set_input_files后绑定唯一nonce，检查中变为clean后再连续读两次稳定完成；同时旧probe仍须无传输、检测、失败或截断。正文/编辑框/footer/预览、旧稳定稿、节点替换、导航或未知观察不能形成证明。状态不写window/DOM，不读取媒体、文件内容、网络或账号存储。

worker只新增专用begin/observe RPC，workflow仅`__init__`、`_upload_video_file`、`_wait_for_upload_complete`变化。主审AST与逐字核对确认原AI声明helper99c663和`_require_ai_declaration`保持，单次`_click_publish`保持。

首版把helper放platform_adapter，真实worker首次调用触发该包导入过慢；子agent联测发生20秒transport超时，主审首测则因约4.5秒导入漏掉fixture的1秒检测状态。两份11过1失败证据均保留。实际修复是迁至轻量shared namespace，避免首次RPC导入平台包；fixture完成begin后才安排检测完成，分开验证转移逻辑与模块加载耗时。没有改transport超时、配额、生产服务或重传。

实际平台HTML/原节点身份与选文件后的URL保持尚未通过新门验收。真实React若替换状态叶节点、平台导航或缺独立容器，本实现仍拒绝；历史诊断只证明文字顺序，不证明本门原生资格。不得把本地DOM通过描述成平台上传或主动AI声明已完成。

## 最终验证和冻结

相关旧上传完成/诊断/单次点击52项通过；最终主助手独立12项真实本地Chrome全部通过，107.72秒，含worker RPC+workflow串行状态转移和其他Page不可复用nonce。子agent修正后单项RPC独立通过45.80秒。测试范围有重叠，不将子agent单项重复累计。

证据目录：`data/development_checkpoints/upload_fast_check_transition_20261019`。`PRIMARY.xml`保留首次失败，`PRIMARY_FINAL.xml`为最终12项通过，另有old_tests.xml、rpc_retry_test.xml、SOURCE_SHA.json、PRIMARY_SOURCE_REVIEW.json、CHANGE.patch及历史诊断SHA回放。

最终SHA：shared helper3940c49a49f5aba1125f57c6eab1787aeec2ff78392603d785fe8edc2f064a05；worker7387f04d919f3e7d183597de0b53f6d214ac692bdef784a57b26ea138a699590；workflow9039a1a31e864be6cfbffef9a8a6eaad3d24a9e8bd81d475b4bb9f515a391951。原worker42a14副本保留，实际服务22452尚未部署本次上传识别修复。旧AI及单次点击修复已在本次13:17部署，两个阶段不得混同。

后续须有新增有效运行授权后，精确核对当前26计数/原控制/无租约或未知业务，受控交还原owner、部署冻结源码，再仅派授权范围内同一视频发布。当前不登记新grant、不排新任务、不自动重传。
