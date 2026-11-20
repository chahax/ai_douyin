# S7 五张独立参考与首段执行记录

用户明确要求结束合成首帧，准备五图并直接生成首段，视频人工审核和原尾帧续段保留。完整原话、采用范围和旧规范的取代关系保存于[流程覆盖记录](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/WORKFLOW_OVERRIDE_v2.json)。

## 本次实际完成

两人各新增一张独立正面面部图、一张独立全身服装图，均为1024×1536原始PNG；复用已确认办公室图，共5张。四次内置imagegen请求均引用各自已确认的人设档案，未生成合成首帧或走廊新图。原生工具返回的模型与reported用量未知，不能计作零费用。所有原图、实际提示词、输入SHA、派发意图和生成回执已保存。新图的人工内容状态仍为待审，不写成独立图片通过。

[五图可视审阅](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/REVIEW.md) · [实际五图绑定](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/FIVE_REFERENCE_MANIFEST.json) · [完整提示词](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/SH01_DIRECT_REFERENCE_PROMPT.txt)

首段仅采用4秒制作时长以满足当前接口下限，沿原SH01两段表演等比例展开，表演全文、操作顺序、起止态和无对白约束保留。原62.26秒冻结交接不改，整片68秒时间候选未采用。参考图确定身份、妆造、环境，视频模型组织构图，起态和推纸动作来自原表演合同。

## 实际接口结果与阻塞

官方SDK的ListAssetGroups只读请求成功；CreateAssetGroup仅请求1次，返回HTTP403、SubscriptionRequired。没有素材组ID，属于明确接口拒绝，不是“服务端结果未知”。真实回执见[素材接入阻塞](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/SUBMISSION_BLOCKED.json)。本次未购买或升级套餐。

依据[官方权益说明](https://docs.volcengine.com/docs/ark/seedance-2-0-purchase-guide?lang=zh)，有免费的高级创作权益（Entry）可支持虚拟素材API；当前账户尚需完成对应开通。已向用户说明并请求回复开通状态。鉴权配置存在、只读成功与上传权益属于不同条件，不能混写为全部可调用。

独立参考的角色图片来自内置图片工具，需按[官方私域虚拟人像库](https://docs.volcengine.com/docs/ark/private-virtual-avatar-library-guide-preview?lang=zh)入库Active后使用Asset ID，不冒充同账号Seedream文生图原始产物。该调用属于服务自身素材入库处理；未调用额外助手音画或图片审核模型。

## 验证边界与后续

五个本地图像的文件头、尺寸、SHA与原始字节核对完成。现有底层请求构造器接受五图reference_image形状，离线预览禁止网络。当前[请求预览](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/REQUEST_PREVIEW_NOT_SUBMIT_READY.json)仍含占位素材地址，明确不可提交；素材库上传、Active绑定和显式参考模式生产入口尚未完成。离线形状通过不等于服务接受或内容质量通过。

当前实际新视频调用0、文本调用0、远程素材上传0；新增内置图片4次。原生图片累计10次，原Seedream9次及115200已知reported图片tokens、旧林屿未知请求完整保留；原文本265次、4559929已知reported tokens与70/160未知用量及93117预留不改。不同类别不能相加伪报统一用量。

[恢复步骤](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/RESUME_CHECKLIST.md)已明确：开通后继续现有五图和授权，完成素材接入与来源绑定，再提交本轮唯一首段。后续首段视频保存状态为awaiting_human_review；用户通过后才用服务原始尾帧续段。保持当前Seedance 2.0 Mini，不主动抽帧、听看、ASR、音画审核、自动重试或发布。合成首帧历史及拒绝回执保留，工作路线已结束，不再把其批准作为首段参考模式的前置条件。


## 五图直接参数实测与前置判断纠正

用户指出可直接传参后，使用既有一次首段授权直接传入五张原图Base64。素材库并非统一必经步骤；实际一次请求到达图片审核，HTTP400 PrivacyInformation拦截三张角色图，未返回任务ID。没有视频产物、自动重试或内容通过；费用未知。本次一次授权已用1/1，同稿失败计数1/10，旧账本不重置。旧403及manifest保留作为历史证据。

实际参数、错误、来源绑定与下一候选路线见[完整实测报告](../data/video_generation/this_time_i_leave_s7_direct_reference_first_segment_20261006/round_01/direct_parameter_SH01/REPORT.md)。
