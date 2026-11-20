# v39：单独 S02 提示词对照

固定新根 `data/video_generation/h3_s02_prompt_probe_20261110_v1`。仅生成一个约15秒的原生 S02，不是第三个整分钟；不调用图片模型、云媒体，不新建 observer，不重启或配置服务，不改已冻结 v38。

源固定为 v38 `R2/shots/S02` 的实际 REQUEST、成功原 ID 与已保存四件。seed 固定 `45905597282583733`，首图 SHA 固定 `d44f2e648f91e6546e8b6da857c812b47d31a48ec3fcd1be272da2dc11558917`。736×1312、362帧、24fps、12步和原模型/编码器/VAE/采样图全部保留。

只替换 Root 已写的 `PROMPT.txt` 原始 UTF-8 文本，以及新 staging/output namespace。两句原中文必须依序逐字保留，首图是原始 PNG 字节，使用新的 client_id/native ID。实际行为不依赖内容通过判断，也不因心声口型小问题重拍。

`PLAN.json` 使用单一 `shot`，不是四段列表。`shots/S02` 保存 workflow、GRAPH_BINDING、first_input、REQUEST、CLAIM、RESPONSE、STATE、HISTORY 和标准 native RESULT。四件技术保存后，单 `FINAL_RESULT.json` 直接指向原 native MP4，`postprocessing=[]`；不重编码、不后期去字、不伪造内容通过。

```text
python scripts/run_h3_s02_prompt_probe_v39.py prepare
python scripts/run_h3_s02_prompt_probe_v39.py execute
python scripts/run_h3_s02_prompt_probe_v39.py collect
```

Root 技术 `LAUNCH_APPROVAL.json` schema 为 `h3_s02_probe_technical_launch/v39`，绑定 PLAN、授权、`_sources()`、CPU验收，并填写 `approved_for_technical_execution=true`。工程上限一个视频，不伪称用户逐字给过次数。

POST 前冻结 CLAIM，结果不确定保留原记录并停止，不换路径重发。共享 GPU/input锁、队列门、单 runner 锁保持。已知 ID 在当前提示词/授权变更或暂停后仍按原请求收存；新派发继续严格校验。CPU 测试只连接独立本地 HTTP fixture、使用真实原件格式文件和短 CPU 音视频，不调用生产模型。
