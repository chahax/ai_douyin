"""Read-only business sampling; writes only local diagnostic evidence."""
import json,sqlite3,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/novel_feed_activation/timeout_recovery_20261024'
A='account:9158f1d29f70eff9819c46b4'
def rows(name,sql,args=()):
    with sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(x) for x in db.execute(sql,args)]
def main():
    r={'at':time.time()}
    r['control']=rows('account_refresh.db','SELECT state,revision,error_code FROM account_controls WHERE account_uuid=?',(A,))
    r['commands']=rows('account_browser_control.db','SELECT command_id,kind,state,error_code,created_at,updated_at,cursor,result FROM browser_control_commands WHERE account_id=? ORDER BY created_at DESC LIMIT 4',(A,))
    for c in r['commands']:
        cursor=json.loads(c.pop('cursor') or '{}');completed=cursor.get('completed',{})
        c['progress']={k:completed.get(k) for k in ('verified_videos','actual_watch_seconds','error_code')}
        c['next_candidate_index']=cursor.get('next_candidate_index')
        c['verified_video_ids']=[item.get('video_id') for item in completed.get('items',[]) if item.get('playback_verified')]
        result=json.loads(c.pop('result') or '{}');m=result.get('maintenance_result',{})
        c['result']={k:result[k] for k in ('healthy','window_minimized','original_feed_tab_preserved','window_closed','automatic_clear_feed_handback') if k in result}
        if m:c['result']['playback']={k:m.get(k) for k in ('status','playback_verified_videos','actual_watch_seconds','error_code')}
    r['playback']=rows('account_refresh.db','SELECT run_id,status,started_at,finished_at,detail FROM playback_runs WHERE account_uuid=? ORDER BY started_at DESC LIMIT 2',(A,))
    for p in r['playback']:p['detail']=json.loads(p['detail'])
    r['observations']=rows('account_refresh.db',"SELECT stage,observed_at,evidence_json FROM clear_feed_observations WHERE command_id='2e418e64d60b4637b15b08a85b1d5d0f'")
    for o in r['observations']:
        e=json.loads(o.pop('evidence_json'));o['evidence']={k:e.get(k) for k in ('page','active_feed','challenge','navigation')}
    pid=int((ROOT/'data/logs/streamlit_web.pid').read_text());r['pid']=pid
    p=psutil.Process(pid)
    r['browsers']=[{'pid':c.pid,'created_at':c.create_time(),'headless':any('headless' in a for a in c.cmdline()),'muted':'--mute-audio' in c.cmdline()} for c in p.children(recursive=True) if c.name()=='chrome.exe' and not any(a.startswith('--type=') for a in c.cmdline())]
    (OUT/f"SAMPLE_{int(r['at'])}.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:r[k] for k in ('at','pid','control','commands','browsers')},ensure_ascii=False))
if __name__=='__main__':main()
