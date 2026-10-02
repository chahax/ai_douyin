"""Render recorded cohort evidence; never promotes model observations to facts."""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_cohort_expression_trial import prepare

def bjt(value):
    if not value:return '未知（来源未提供）'
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None:return f'{value}（原记录无时区，未推断）'
    return stamp.astimezone(ZoneInfo('Asia/Shanghai')).isoformat()

def main():
    trial=Path(sys.argv[1]).resolve()
    cards,_,gate=prepare(trial)
    run=json.loads((trial/'run.json').read_text(encoding='utf-8'))
    modes={'conflict_drama':'人物冲突','direct_explanation':'直接讲解','prop_demonstration':'实物演示','question_answer':'知识问答','text_cards':'文字卡片'}
    lines=['# 本批20条视频：来源与表达证据', '',
        '本报告使用此前采集的原片，不代表今天新采集的热度。点赞共 **1,397,314**，不是播放量；20条来自同一采集批次，覆盖合同纠纷、劳动争议、婚姻家事。', '',
        f"- 本次分析启动（北京时间）：{run['started_at_bjt']}",
        f"- 本地音画工件处理结束后的登记时间（北京时间）：{run['observations_completed_at_bjt']}",
        '- 发布时间、采集时间、分析时间分别记录，未使用文件修改时间推断完成。',
        '- 原有逐条图像/转写分析保留；本次新增129个连续音画窗口（最长30秒、图像约1帧/秒）及20条本地声音分析。原音频覆盖不代表逐帧人工听看。',
        '- Omni观察与emotion2vec分类是辅助证据。复述问题/截断/重复结果不作为有效观察；互相矛盾的情绪判断保留未知。未上传原片音轨到外部接口。', '',
        '## 类型比较', '',
        '高点赞组统一为≥122,000的5条，类型标签可重叠。每个原视频只算一条，不按窗口数或时长加权。', '',
        '|类型|条数|点赞中位数|高点赞组中出现|','|---|---:|---:|---:|']
    for row in cards['type_comparison']['types']:
        lines.append(f"|{modes[row['mode']]}|{row['n']}|{row['median_likes']:,}|{len(row['high_ids'])}/5|")
    lines+=['', '实物演示3条是相近的按印/空白/跨页标记模板；这不能证明是同一作者或系列，也不能视为三个独立的效果实验。点赞相关性不等于表达形式导致高点赞。', '',
        '## 每条来源、时间及声音观察范围', '',
        '|来源ID|点赞|时长秒|主要标签|发布时间（北京时间）|采集时间（北京时间）|AV窗口/不可用窗口|',
        '|---|---:|---:|---|---|---|---|']
    for s in cards['sources']:
        windows=s['audio_visual_observations']
        lines.append(f"|{s['source_id']}|{s['metric_value']:,}|{s['original_duration_seconds']:.2f}|{s['primary_tag']}|{bjt(s['published_at'])}|{bjt(s['collected_at'])}|{len(windows)}/{sum(bool(w['quality_warnings']) for w in windows)}|")
    lines+=['', '## 逐条核心、画面和语言结构', '',
        '以下沿用绑定原片、抽帧、转写与原审核的表达分析。每个法律结论仅代表素材主张，不能直接用于新剧本的普遍法律示范。']
    old=(trial/'cohort_report.pending.md').read_text(encoding='utf-8')
    body=old.split('## 逐条已有核心与表达证据',1)[1]
    body=body.replace('说明：以上为已有逐条表达分析；新全片音画窗口结果尚未汇总，不能把转写语言结构当成已听到的声线或语气。',
        '说明：这里的语言结构来自转写，不等于人工确认的声线、语速或声画同步。新增音画工件见下方索引。')
    lines.append(body)
    lines+=['', '## 新增本地音画分析索引', '',
        '分类器窗口可跨越不同说话人及背景音乐，不用于计算人物情绪占比。各条完整AV原始输出与原片秒数见 full_av_v2/manifest_concise.json；每条声学窗口见 acoustics/<来源ID数字>.json。', '',
        '|来源ID|8秒声音窗口最高分类标签计数（仅模型假设）|', '|---|---|']
    for s in cards['sources']:
        counts=s['acoustic_hypotheses']['window_label_counts']
        lines.append(f"|{s['source_id']}|"+'；'.join(f'{k}: {v}' for k,v in counts.items())+'|')
    lines+=['', '尤其注意：15秒催付冲突片的语气快慢，Omni与分类器/既有观察存在矛盾，不能当成已验证的语速曲线。低点赞问答片也被分类为生气，不能据此推论只要更愤怒就会更好。', '',
        '## 生成与审核记录', '',
        '研究总结由项目模型读取全部20条表达分析及其引用证据生成，实际审核后才进入剧本阶段。第一版因退回知识讲解、CTA结尾及统计归纳错误被拒绝；原件与具体原因保留在 summary_v1。最终选用总结、剧本与审核见本轮交付说明。本报告本身不表示剧本或视频通过。']
    (trial/'analysis_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__':main()
