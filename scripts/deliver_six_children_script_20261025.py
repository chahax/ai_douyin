"""Export an explicitly editorial draft; preserve machine verdicts and place hold."""
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import natural_director_pipeline_v10 as pipe

root=Path(__file__).resolve().parents[1]/'data/novel_platform_trials/20261025_six_children'
run=root/'writer';out=root/'deliverables';core=pipe.core


def main():
    if out.exists():raise RuntimeError('交付记录已存在，不覆盖')
    with core._lock(run/'.execution.lock'):
        b,s=pipe.parent._verify(run)
        assert s['calls_started']==6 and s['pending_call'] is None and s['stage']=='director_full'
        assert pipe.parent._value(s,'gate')['gate']['decision']=='pass'
        native=run/'DRAFT_005.md';original=native.read_text(encoding='utf-8');draft=original
        changes=[
          ('我穿成了他们将来要报复的继父……这肉，是不能再让他们偷了。',
           '我穿成了他们最恨的继父。刚把肉分出去，竟像给孩子吃送别饭。'),
          ('大家放学后一起去找他。','大家下课时去找他，放学后一起回家。'),
          ('双胞胎不增加台词，以同桌、起身、跟随和围拢动作表现他们是共同体。',
           '双胞胎以同桌、起身、跟随和围拢动作表现他们是共同体，保留叶寻的一句短回应。'),
          ('约 **13个发言轮次**','**18个发言轮次**'),
          ('对白本身约需48—55秒；其余时间由分肉、停顿反应、起身离桌、围拢定策等与对白并行或承接的信息动作构成，不以静候凑时长。',
           '对白本身约需55—65秒；起身离桌、转场和必要反应与对白并行或自然承接。表演时多人反应同刻发生，不逐个排队展示。90秒为剪辑前估算，实际时长须在分镜和演出后复核。'),
        ]
        for before,after in changes:
            assert draft.count(before)==1,before
            draft=draft.replace(before,after)
        spoken=re.findall(r'^\*\*(?:苏墨|叶东|叶南|叶北|叶寻|叶嫣儿|叶西决)[^\n]*?：\*\*\s*(.+)$',draft.split('# 五、完整可拍剧本')[-1],re.M)
        count=len(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',''.join(spoken)))
        assert len(spoken)==18 and 200<=count<=260
        out.mkdir()
        file=out/'一顿好饭_剧本校订版.md'
        header='# 《一顿好饭》｜剧本校订版\n\n来源：苏捷捷《你敢惹我？我有六个反派儿子》第1—3章。目标约90秒，竖屏剧情短片。\n\n本版供审稿，已核对书籍与章节来源，尚未生成视频。人物表情、动作与对白按同一时间并行演出。空间、灯光及家具属于依据贫困城中村生活条件作的视觉补足；原文已知事实见背景部分。\n\n---\n\n'
        file.write_text(header+draft,encoding='utf-8')
        audit={'status':'editorial_draft_ready_for_user_review','source_chapters':3,
          'native_draft':core._binding(native),'native_review':s['active']['gate'],
          'native_machine_verdict':'pass','native_machine_verdict_preserved':True,
          'editorial_version':core._binding(file),'changes':[{'before':a,'after':z} for a,z in changes],
          'edited_version_machine_reviewed':False,'reviewer':'assistant_editorial_review',
          'spoken_character_estimate':count,'spoken_turns':len(spoken),'target_seconds':90,
          'duration_is_measured':False,'calls_started':6,'reported_tokens':s['known_reported_tokens'],
          'promotion_task_active':False,'media_calls':0,'platform_submission':False,
          'before_checkpoint':core._binding(sorted(run.glob('STATE_*.json'))[-1])}
        core._write(out/'DELIVERY_AUDIT.json',audit)
        # The native pass stays intact. It must not dispatch its known defective
        # sentence or silently treat this edited copy as the machine-reviewed text.
        s.update(status='needs_attention',halt_reason='原生审核漏判肉来源语义及排时统计；单独人工校订稿已交付待用户审阅，原稿保持且不得自动派发。6次文本调用已用完。')
        pipe.parent._save_state(run,s);pipe.parent._verify(run)
        core._write(root/'FINAL_STATUS.json',{**audit,'automatic_dispatch_blocked':True,
          'native_checkpoint':core._binding(sorted(run.glob('STATE_*.json'))[-1])})
        print(file)
        print('spoken_chars',count,'turns',len(spoken),'calls',s['calls_started'],'tokens',s['known_reported_tokens'])


if __name__=='__main__':main()
