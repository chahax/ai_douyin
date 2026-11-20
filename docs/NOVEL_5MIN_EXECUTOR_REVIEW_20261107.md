# 五分钟单任务执行器审查

仅修改 `data/video_generation/novel_5min_20261106_v1/run_production.py` 及新增 `tests/test_novel_5min_production_runner.py`。未修改冻结管线库、父packet、F0001 PLAN、旧H3、账号或发布业务。

11项CPU测试通过；实际只读status命令成功。测试覆盖顺序派发、原ID恢复、未知终态停止、首段音画证据门、现有首图返修状态兼容、27个独立回执/输出、四类源文件与成功history、7292帧拼接，以及编码完成后rename与最终receipt之间的崩溃恢复。独立子进程确认WORKER锁互斥并正常释放。

`all` 顺序为每镜首图→本镜H3；首段音频、画面、原文对白未经绑定证据核对，禁止进入第二镜。`FIRST_SAMPLE_REVIEW.json` 必须包含首段原prompt_id、video_sha256、PRODUCTION_PLAN.source、checks={audio:true,visual:true,source_dialogue:true}、reviewed_by，以及evidence列表(path/sha256)。这不是自动合格标记；应由实际音画与对白检查后登记，证据发生变化会停止。

命令：

```powershell
.venv/Scripts/python.exe data/video_generation/novel_5min_20261106_v1/run_production.py videos --only F0001
.venv/Scripts/python.exe data/video_generation/novel_5min_20261106_v1/run_production.py all
.venv/Scripts/python.exe data/video_generation/novel_5min_20261106_v1/run_production.py assemble
```

当前root因真实首图人数/肢体异常暂停新F0001，尚未启动H3。不得执行上述生产命令来绕过暂停；修复首图生成边界并建立合法新PLAN后再继续。执行器CPU验收不代表该首图、视频或整片通过。

冻结清单与XML SHA见 `data/qa/NOVEL_5MIN_EXECUTOR_ACCEPTANCE_20261107.json`。
