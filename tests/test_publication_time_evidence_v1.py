import json
import sqlite3
import pytest
from src.services.publication_time_evidence_v1 import read_publication_time,verify_publication_time


def make_db(tmp_path, *, wrong=None):
    p=tmp_path/'browser.db'
    original={'status':'published','success':True,'post_id':'123456789012345',
        'publish_url':'https://www.douyin.com/video/123456789012345','publish_evidence':{'post_verified':True}}
    video={'video_id':'123456789012345','account_uuid':'a','account_key':'novel','publish_time':'2026年11月16日 14:30'}
    if wrong=='post':video['video_id']='888888888888888'
    if wrong=='account':video['account_uuid']='other'
    if wrong=='date':video['publish_time']='昨天'
    with sqlite3.connect(p) as d:
        d.execute('CREATE TABLE browser_control_commands(command_id TEXT,account_id TEXT,binding_version TEXT,state TEXT,kind TEXT,payload TEXT,result TEXT)')
        d.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?,?)',('pub','a','v','succeeded','publish',json.dumps({'account_key':'novel'}),json.dumps(original)))
        d.execute('INSERT INTO browser_control_commands VALUES(?,?,?,?,?,?,?)',('sync','a','v','succeeded','read',json.dumps({'method':'sync_videos'}),json.dumps({'read_result':{'success':True,'videos':[video]}})))
    return p


def test_real_publish_without_date_uses_verified_sync_date(tmp_path):
    p=make_db(tmp_path)
    e=read_publication_time(p,'pub','a','v',metadata_command_id='sync')
    assert e['published_at']=='2026-11-16T14:30:00+08:00' and e['source']=='verified_sync_videos'
    assert verify_publication_time(p,e)==e
    with sqlite3.connect(p) as d:d.execute("UPDATE browser_control_commands SET result='{}' WHERE command_id='sync'")
    with pytest.raises(ValueError):verify_publication_time(p,e)


@pytest.mark.parametrize('wrong',['post','account','date'])
def test_wrong_sync_evidence_not_used(tmp_path,wrong):
    with pytest.raises(ValueError):read_publication_time(make_db(tmp_path,wrong=wrong),'pub','a','v',metadata_command_id='sync')


def test_no_date_no_current_time_fallback(tmp_path):
    with pytest.raises(ValueError,match='metadata_required'):read_publication_time(make_db(tmp_path),'pub','a','v')
