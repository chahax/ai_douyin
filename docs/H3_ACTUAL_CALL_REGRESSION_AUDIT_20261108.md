# 实际调用差异审计：增人和结尾装饰

本轮只读核对18个真实REQUEST/workflow：旧raw首图路线4段、旧纯Ref2VA五参考路线4段、当前spatial A/B各4段、C已提交的S01/S02。17份已保存HISTORY与冻结请求图等价；C/S02仍在途，未把缺HISTORY视为通过。0模型/HTTP/GPU/POST，未改任何运行源码或PLAN。

逐字段JSON：`data/qa/h3_actual_call_comparison_20261108/ACTUAL_CALL_DIFF.json`，SHA `6fc0fb771476cc90a7eeeddd917387865bfb07bb27d24aa01d0ebd45eb244f70`。每项含实际文件SHA、原生ID、完整已提交正文、槽内实际staged图片SHA/尺寸及两两图差分。只归一化输出文件scope和LoadImage节点名称，保留实际图片内容SHA、prompt、seed及其他参数。

“上次A/B”标签尚不能自动绑定到某个旧目录：历史里有Seedance/H3左右对照，也有稍后的纯Ref2VA分钟；最近明确命名A/B的是spatial实验。下面按真实线路列出，不能把旧候选都认作用户指定版本。

## 确定的参数变化

|实际线路|视频模型/条件节点|人物与房间图片/首尾接法|seed|S03、S04实际正文字符/纯文本token|
|---|---|---|---|---|
|旧raw：`h3_seedance_prompt_parity_60s_20261107_v1`|FL2VA INT8 / `MiniMaxH3ImageToVideo`|没有五个参考槽；S01原Seedance JPEG首图，之后本轮前段原生尾图，全部first-only；没有AddGuide|2026110700—2026110703|679/530；660/506|
|旧纯参考：`h3_reference_full_minute_20261107_v1`及各v20 delivery|Ref2VA INT8 / `MiniMaxH3ReferenceToVideo`|每段同3人物+2房间参考；没有首图/尾图/AddGuide；各段独立生成|S01 35082988865554014；S02 65828460078193209；S03 37757047853303467；S04 13220207175429509|726/519；701/488|
|当前spatial A|同Ref2VA INT8|同旧纯参考五张图片、同次序；**新加frame-zero AddGuide**，S01为旧纯参考S01原生首图，之后为本轮前段原生尾图|12345—12348|908/652；868/608|
|当前spatial B|同Ref2VA INT8|三人物相同，两房间换新图；新组合首图，之后本轮原生尾图；**S03另有frame361末锚**|同A|3713/872；3650/876|
|当前C room-only|同Ref2VA INT8|A的文字、人物、首图和策略不变，仅两房间换B图片；S02自然改用C自身S01原生尾图|同A|未提交S03/S04；S01/S02正文与A逐字相同|

18图中没有发现漏掉latent、音轨，或多挂ControlNet等新模型节点。以下字段全部相同：Qwen3-VL-32B NVFP4 encoder、视频VAE INT8 ConvRot、音频VAE FP32、res_multistep、simple、12steps、denoise=1、BasicGuider、736×1312/362帧/24fps、VAEDecodeTiled参数、原生音频解码与CreateVideo音轨连接。BasicGuider没有显式CFG值或negative分支，不能把没有cfg字段误说为本轮丢失。

同一模型文件名/编码器配置是确定事实；单凭REQUEST不能证明跨日期所有模型文件字节或Comfy实现都未变化，未补写不存在的运行时tensor/模型全量SHA回执。按本机节点公式推导的共同AV latent为video `[1,24,107,82,46]`、audio `[1,32,2,603]`，这是代码推导而非运行时tensor dump。

## 首图通道并不等价

本机 `comfy_extras/nodes_minimax_h3.py` 显示：I2V的first_frame既进入Qwen视觉token，又经VAE编码加入keyframe；AddGuide只向已有positive追加VAE keyframe，没有重新让Qwen看该组合首图。当前Ref2VA的Qwen看到五张独立参考，随后另加latent首图。这是明确的调用结构差别，不能把两种情况都简称“给了首图”而视为相同。

当前图的接线本身未发现漏接：AddGuide positive接Ref2VA输出0、latent接输出1，BasicGuider接最后的guide，Sampler latent仍接输出1；B/S03的末锚接在首锚之后。raw的first_frame入口也确实存在。没有统一固定机位/控制视频节点偷偷加入。

旧纯参考与A的五个实际staged图片SHA和次序均相同，`ref_image_size=match`也未改。旧五图都是768×1024，match实际不缩小；B/C两房间图为736×1312，也不缩小，因此换图同时改变了参考图面积/纵横比。按32px合并网格估计，五图视觉patch总量由3840增至4190；这是由尺寸推导，未冒充实测视觉token。

归一化后的实际图比较：A→C/S01只有两张room图片SHA不同；A→C/S02额外变化是C自身上一段尾图SHA。没有发现其他暗改采样参数。但这个实验只比较具体两张房间图替换，不能称为只隔离“空间算法”的因果实验。

## 文本丢失和多角色表达

旧纯参考→A实际新增一段具名Picture/衣服/高矮映射；旧footer的“同一人物外观与服装”“Picture4/5是同一场景环境”改成了短名称列表。S03另外将“男童心声”具名为叶西决。原10句引号内容没有改变。

B又整体改为英文六节、Subject身份号、每段局部声音号、逐句d标签。它没有要求增加孩子，Subject4定义的是房间；但这些标签和重复人物描述是否造成模型将参考/已存在人物当成多个实例，目前没有受控证据，不能先断言。

**确定丢失：** raw、旧纯参考、A、C实际正文都有“画面以纯剧情影像呈现，叙事信息通过表演和声音传达。”B的实际英文正文没有保留这条制作意图，也没有等义的明确正文边界。B不是只换语言而完整保留所有提示约束。恢复该意图是可落实的文本合同修正；它是否足以消除金字/星点，需要新实片验证，不能把相关性当因果。

纯文本token按同一本地Qwen2Tokenizer和MiniMax7个special token重算，所有实际prompt不足1000文本token；统计不含视觉块。本机tokenization路径未发现512/1024的短截断，因此目前没有证据指向“B过长被截掉后半段”。此前 `B_TOKENIZER_LOCAL_PREFLIGHT.json` 是旧插入稿，不应用其数字冒充实际native英文POST；本审计按实际REQUEST重新计数。

## 增人、结尾金边：实际证据和未证明的机制

root已看7、40、50、59.5秒四路实帧，证据为 `data/qa/h3_call_regression_audit_20261108/ACTUAL_PATH_COMPARISON.json`：旧raw50秒样本为成人+2孩、59.5秒无金边；当前A50秒有额外孩子，B7秒已有两对兄弟，B59.5秒有金边。旧raw40秒也有普通烧入台词，不能称旧版本从无文字或完全无缺陷。以上是具体时间点观察，不是逐帧人数认证。

旧纯参考的 `ROOT_MOVIE_REVIEW.md` 也记录S02/S03额外儿童、两床和串衣，因此它是一个真实调用baseline，而不是已通过的“无增人”质量基线。到底对应用户所说的旧A/B，由root继续结合历史定位，不用目录名替用户决定。

本审计实际查看了B/S04原生last、其实际frame-zero guide、两张实际room参考。guide中是3人持一个袋子，没有金边；两张room参考也没有金字星点。原生last已有大量金色伪字/星点边框。last的取值路径是VAE解码→ImageFromBatch→SaveImage，未经过完整片合成。

18个实际图都没有文字/水印/overlay/composite渲染节点；四份完整片assembly filter也没有drawtext、overlay、subtitles、ass等过滤器。QA CONTACT虽有标题标注，但其像素并未被这些实际参考/guide路径作为输入。故现有证据指向**模型原生输出像素中的装饰**，不是管理页面debug层或CPU合成额外加水印。B/S04 `ROOT_S04_REVIEW.json`有同一发现。

首尾承接也存在已观察的放大路径：A/S03尾图多出孩子，A/S04继承后人数扩大；但B/S01首段中途已经出现重复兄弟，所以“尾帧传播”只能解释后段放大，不能独自解释首段复制。混合五参考+组合首图、参考共指弱化、随机seed变化、英文制作意图丢失都是待分离的候选机制，不能全部归因模型，也不能只靠换两张room图覆盖。

## 可落实的恢复验证

优先恢复已有完整真实回执的旧raw **FL2VA/I2V first-only调用配方**：以其四份实际REQUEST/workflow/HISTORY为模板，保留各段模型/encoder/VAE/采样/fps及2026110700—03 seed，停止混入五参考+AddGuide和B英文重写。上游人物/房间资产仍可用于首图准备，不等于视频端继续有五参考槽。

本轮root拟采用A同一已审canonical首图，后段用新一轮实际尾图；A中文源仅确定性移除没有实际输入的Picture/具名参考措辞，换为首图人物服装说明，保留原10句、动作、时序与纯剧情影像条款。**这将恢复已实测的调用配方，但首图/适配文字仍与旧raw不同，不可冒称完全同输入复刻，也不等于已经证明根因。** 应另建新root/授权/ID，保留所有旧记录，不重放旧调用。

若最终确认用户指定的是旧纯Ref2VA版本，则可明确复用其原五图次序、实际prompt及各段seed，且不加任何guide，另做受控恢复；但旧片已知增人记录不能抹掉。当前C已暂停新POST，S02只按原ID收存，审计本身没有发起任何恢复生成。
