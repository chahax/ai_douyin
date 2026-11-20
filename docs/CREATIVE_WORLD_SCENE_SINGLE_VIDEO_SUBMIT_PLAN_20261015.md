# 世界场次流程：一次视频提交与原任务保存

本模块承接用户2026-10-15的明确授权：真实文本与制作审查达标后，直接生成一次测试视频。文本协调器已冻结并由主线程执行；本子任务只新增独立提交器、离线测试及本文档，不修改已冻结文本/制作模块、另一会话媒体、旧回执或账本，不实际调用服务。

## 准入与唯一提交

固定消费项目的文本 `verify_text_handoff`、首段制作 `verify_first_segment_handoff`，以及媒体准备v2的原文件、原图顺序和显式编码余量。准备文件中的成功标志不能替代这两个原始验证器。新提交器通过媒体v2 `verify_prepared`重验这些证据，再核本地图合同校验报告、同故事失败账本、服务目录与空队列、当前修复轮，以及原始prompt/graph/reference/encoding身份。

`preview`与授权模板只读；`submit`在claim前核一次，在共享媒体锁内再次核验。唯一授权claim和原制作交接claim均原子创建，绑定固定本轮一次视频范围、准备根与原文件SHA；部分claim或POST未知均保存停点，不能删claim、换目录或换grant重派。提交前写原始请求并持久化“开始发送”证据，然后最多执行一次 `POST http://127.0.0.1:8190/prompt`。SDK与HTTP自动重试均为0，不降分辨率、不续段、不发布。

## 原任务查询与保存

`poll`只接受本次原始回执中的prompt_id，执行原ID的GET；没有原ID时明确结果未知，不能重POST。历史必须回读同一client_id、prompt_id及逐值一致的原graph。服务明确失败保存原始history，不触发重生成。查询可重复，不能改变一次生成额度。

原任务成功后，`finalize`只解析既定save_video/save_audio/save_first/save_last槽，输出路径必须位于本次唯一prefix。检查文件非空、SHA与复制一致性；ffprobe仅读取容器/流元数据，不解码画面、听音、抽帧、ASR或调用审核模型。原服务同次首尾PNG及独立音轨完整保存，但不打开。交付视频状态始终为`awaiting_human_review`，人工/审美/内容通过保持false/null。

## 实现边界

新增`scripts/creative_world_scene_video_submit_v1.py`及窄测试。CLI提供preview、authorization-template、native-validate、submit、poll、finalize。`native-validate`仅GET现有服务的`object_info`，在本地核对必需槽、枚举/模型名、链接输出类型、V3动态参考槽及无环；不导入Comfy运行时，不新起实例，不发送所谓validate-only的POST。报告明确`server_native_validation_performed=false`、未运行自定义节点校验；不能把必要合同检查当成服务端原生校验、1280×704实际生成或视频内容通过。

视频唯一授权标识固定为`world_scene_live_20261015_one_video_user_authorization_v1`，不随文本修复轮或v1/v2文本根改变。当前计轮和准备根参数化；旧媒体账本只读，新增本次媒体消费ledger完整继承其快照，不回写另一会话的原账本。已提交的原ID查询不需要新计轮/鲜度授权，后续来源漂移如实附记，不能影响原任务证据保存或变成重新提交权限。

离线验证使用临时项目、假的证书验证器及HTTP transport；默认live路径只使用固定项目验证器。重点覆盖已知成功唯一POST、timeout未知禁止重派、claim后计轮/准备文件变更拒绝、同授权/同制作交接换目录拒绝、原history/输出路径身份和纯元数据保存。主线程审核最终SHA与离线证据后，亲自决定实际准备、GPU占用和提交。本模块不主动申请新的授权或使用旧拒绝尾帧。
