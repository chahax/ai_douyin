# 五视图室内与压缩稿首段实测

用户移除CORRIDOR_SIDE、认可室内后要求“用这个生成”。本轮使用该五视图环境板、两张原人物三视图/面部细节板准备一张完整开场图片，再用现有本地H3 FL2VA首帧模式生成压缩稿《这份申请，我没提》的S01一次，约15秒。仅S01，不续段、不重试、不发布；同故事已知3/10保留。

独立执行目录为 `data/video_generation/h3_dense_office_trial_20261018`。`AUTHORIZATION.json`绑定原60秒稿、新室内适配稿、正向视频提示词、原环境选择与素材恢复证据。旧稿、旧视频和失败不修改。主助手亲自完成适配，未调用外部文本模型。

开场图 `opening_frame.png` 由内置imagegen一次生成，三项参考实际顺序为环境/C01/C02；原生图1672×941，同字节复制到D盘。图中桂芳在左桌核库存，经理在右后方敞门内已可见，桌椅、纸笔、申请和文件夹初始均存在。静帧的便笺实际为小便笺本，主助手在新适配稿中同步整本移动、上层页写字及整本交回，保留对齐前草案；对白、时长和因果不改。`OPENING_IMAGE_REQUEST.json`、`OPENING_IMAGE_RECEIPT.json`及`PRIMARY_OPENING_IMAGE_REVIEW.json`记录实际输入、来源和结构准备，不伪写用户视频批准或精确三维几何复原。

新独立runner `src/content_factory/h3_dense_office_trial_v1.py` 和CLI `scripts/run_h3_dense_office_trial_20261018.py`编译20节点原生图：`MiniMaxH3ImageToVideo.first_frame`连接完整开场图，FL2VA已安装量化权重；旧REF2VA三图输入移除，维持768×416、12步、res_multistep/simple、24fps、362帧及原生音频，不用Turbo，不新装依赖或模型。视频提示词只有实际场景、动作神情、机位与准确四句普通话，不混入图板标题、审查、预算或制作控制语。

四项有意义的离线验证覆盖源字节不变/单图原生编译、未知不重派与原ID恢复、唯一claim/受理ID持久保存/二次提交拒绝、原ID查询/服务失败停止。实际原生校验valid=true、node_errors={}、未执行节点；图SHA为 `319b9db368e0874699c0fab729848e52b60d7c2029bbcb246b6777950fc21550`。CPU只读校验中的可选nodes_replacements初始化警告保留，实际所需节点校验成功，未按日志建议擅自安装环境。

主助手实际阅读runner、共用HTTP/保存/锁/图身份助手、四项测试及实际图/提示词/素材绑定，`PRIMARY_TRIAL_REVIEW.json`仅放行当前一次提交。全局和本地永久claim先保存再POST；遇未知保留证据，只可查原ID，禁止重派。实际运行状态以`SUBMISSION_RESPONSE.json`、`receipt.json`和`HISTORY.json`为准，本文件不把准备或接口校验当成视频完成。

本轮场景板和完整开场图已按独立版本加入自有资产库；37项verify=ok、0 issues。稳定ID分别为 `imagegen.scene.office_five_views.20261018.v2` 和 `imagegen.composition.office_guifang_matao_s01.20261018.v1`，保留用户媒体批准null。

视频只做接口、原图身份、容器包/帧数/分辨率/音轨/时长、原PNG编码CRC及文件SHA检查。助手不抽帧、听看、ASR或替用户进行内容验收。技术保存后仍为awaiting_human_review，需交付实际MP4和完整D盘路径。

## 实际完成

唯一原ID `9045f35d-ce0a-4487-b5e3-a85a988ba964` 已成功，17:51:11受理，18:09:21完成收集。HISTORY记录服务执行1065.087秒（17分45.087秒），提交至文件保存1089.705秒（18分9.705秒）；采样部分12步13分27秒。旧低清试片服务执行2447.901秒仅作单次历史对照，本轮约减少56.5%；输入模式/参考条件也改变，不能归因于单独一个速度参数或保证后续同速。

交付MP4为H.264、768×416、24fps、362帧、15.083333秒，AAC 32kHz双声道，1963547字节；原生FLAC与原始首尾PNG一并保存。主助手独立核实际request等于冻结图、原ID历史图仅有既有fps/denoise数值类型转换、所有原始服务文件与本地副本/交付SHA一致，视频362个包、音轨473个包，来源未变。结果见`PRIMARY_DELIVERY_VERIFICATION.json`。未听看、抽帧或ASR；内容仍awaiting_human_review，同故事失败仍3/10，未提交S02。

实际交付：`D:\IT\ai_douyin\data\video_generation\h3_dense_office_trial_20261018\deliverables\S01_office_768x416_12step_with_audio.mp4`，SHA256 `235ad4549f24e3e033bf5c37b95982031480f993abc92657b36e6685c1f864d4`。
