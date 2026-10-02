本次采用 script delta_v1 传输格式，下述结构替代上文stage=script的完整状态结构，其他剧情与时长规则完全保留。
只输出 requested_kind 对应顶层，结构如下：
{"short或long":{"scenes":[{"id":"L1","location":"实际地点","time_context":"时间关系"}],"props":[{"id":"P1","name":"道具唯一实体名"}],"initial_state":{"characters":{"每个人物ID":"开场位置、手持物、视线"},"props":{"每个道具ID":"开场位置及状态"}},"shots":[{"shot_id":"S01","event_id":"E01","scene_id":"L1","duration_seconds":5,"participants":["C1","C2"],"action":"具体动作","result":"实际结果","dialogue":[{"speaker":"C1","text":"实际说的话","start":0.1,"end":2.5,"delivery":"触发/语气语速/本句实际重音"}],"changes":{"characters":{"C1":"本镜完成后的新状态"},"props":{"P1":"本镜完成后的新状态"}}}]}}
不要输出event_spine/state_before/state_after；程序原样复制批准的events，逐镜继承完整状态，再应用你写的changes。只写实际发生变化的ID，不变则{}，不能删除ID。initial_state列齐所有实体。任何位置/拿放/安装变化必须在action中有对应动作；scene切换也不会自动改变状态。包袋与袋内新屏必须分开ID，屏装进手机后其ID仍表示屏，不变成包装。无需列不影响剧情的装修/工具为道具，但任何持物要明确。
每事件下镜头时长之和精确等于提纲事件。台词字符数含标点不超过(结束-开始)*6，短版建议4.5~5.5字/秒；不可把吸气停顿/省略号作为台词。先分配可说完的台词，不靠越过镜尾。无台词=[]。
不要照搬被拒稿错误：不能说同一场无时间跳跃却6秒完成拆机；拆机/装机使用明确省略时间的新scene和完成动作连接，避免拍细小内部排线技术步骤。只有拍出实际完成才能在result声明完成。情绪要由具体话语和动作推进。
