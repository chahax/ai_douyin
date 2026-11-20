import json
import pytest
from src.platform_adapter.fanqie_book_corpus import collect_corpus, CATALOG, READER
from src.platform_adapter.fanqie_book_inspect import BookInspectionStopped
from test_fanqie_account_control import accounts, login, Session

BOOK='7302660145530539062'
class Page:
    def __init__(self,locked=False,stale=False):self.index=0;self.clicks=[];self.locked=locked;self.stale=stale
    def evaluate(self,js):
        if js==CATALOG:return [{'title':f'第{i}章','locked':self.locked and i==4} for i in range(1,7)]
        if js==READER:
            i=1 if self.stale else self.index
            return {'book_id':BOOK,'item_id':str(7302660145530539000+i),'text':f'第{i}章正文'*50,'url':'https://kol.fanqieopen.com/'}
        if 'const matches=' in js:
            self.index=next(i for i in range(1,7) if f'"第{i}章"' in js);self.clicks.append(self.index);return True
    def wait_for_timeout(self,n):pass

def run(page,root,guard=lambda:None):
    return collect_corpus(page,{'book_id':BOOK,'book_name':'书'},guard,lambda v:None,root,resource_id='r',command_id='c')

def test_all_accessible_and_resume(tmp_path):
    p=Page(locked=True);v=run(p,tmp_path)
    assert v['corpus']['status']=='accessible_catalogue_complete'
    assert len(v['corpus']['chapters'])==5 and p.clicks==[1,2,3,5,6]
    assert v['corpus']['full_book_confirmed'] is False
    p=Page(locked=True);run(p,tmp_path);assert p.clicks==[]

def test_stale_reader_stops_with_checkpoint(tmp_path):
    with pytest.raises(BookInspectionStopped,match='stale'):run(Page(stale=True),tmp_path)
    state=json.loads((tmp_path/'MANIFEST.json').read_text(encoding='utf-8'))
    assert state['status']=='stopped' and len(state['chapters'])==1

def test_cached_corruption_stops(tmp_path):
    run(Page(),tmp_path)
    path=tmp_path/'chapters/00002.json';v=json.loads(path.read_text(encoding='utf-8'));v['text']+='篡改';path.write_text(json.dumps(v),encoding='utf-8')
    with pytest.raises(BookInspectionStopped,match='cached_source'):run(Page(),tmp_path)

def test_other_identity_cannot_reuse_corpus(tmp_path):
    run(Page(),tmp_path);before=(tmp_path/'MANIFEST.json').read_bytes()
    with pytest.raises(BookInspectionStopped,match='identity_changed'):
        collect_corpus(Page(),{'book_id':BOOK,'book_name':'书'},lambda:None,lambda v:None,tmp_path,resource_id='other',command_id='d')
    assert (tmp_path/'MANIFEST.json').read_bytes()==before

def test_lost_guard_never_clicks(tmp_path):
    p=Page()
    def guard():raise BookInspectionStopped('owner_lost')
    with pytest.raises(BookInspectionStopped,match='owner_lost'):run(p,tmp_path,guard)
    assert p.clicks==[]

@pytest.mark.parametrize('changed',[False,True])
def test_long_read_refreshes_same_identity_or_stops(accounts,monkeypatch,changed):
    import time
    from src.operations_accounts.fanqie_account_control import run_owner
    import src.platform_adapter.fanqie_book_inspect as module
    env,cmd,_,_=login(accounts);accounts.confirm(cmd['command_id'],'uid:12345','fixture')
    accounts.queue(env['resource_id'],'fanqie_book_inspect',book_name='书',chapters=1)
    class Fresh:
        def _cmd(self,*a,**k):return {'evidence':{'verified':True,'challenge':False,'observed_at':time.time(),'platform_identity_key':'uid:99999' if changed else 'uid:12345'}}
        def goto(self,*a,**k):pass
        def wait_for_timeout(self,n):pass
    class Long(Session):
        def _cmd(self,*a,**k):
            v=super()._cmd(*a,**k);v['evidence'].update(observed_at=time.time()-31,page_location={'origin':'https://kol.fanqieopen.com'});return v
        def new_tab(self,role):assert role=='book-identity-refresh';return Fresh()
    def inspect(page,title,guard,checkpoint,**kwargs):guard();return {'book_name':title,'status':'inspected'}
    monkeypatch.setattr(module,'inspect_book',inspect)
    result=run_owner(env['resource_id'],accounts,session_factory=Long)
    assert result['state']==('failed' if changed else 'succeeded')
    if changed:assert result['result']['reason']=='identity_refresh_failed'

def test_prehandler_contention_keeps_original_id(accounts,monkeypatch):
    import src.operations_accounts.fanqie_account_control as module
    base=module.BrowserControlActor
    class Actor(base):
        attempts=0
        def run_next(self):
            self.attempts+=1
            if self.attempts==1:return None
            return super().run_next()
    monkeypatch.setattr(module,'BrowserControlActor',Actor)
    env=accounts.create('小说','novel');cmd=accounts.queue(env['resource_id'])
    result=module.run_owner(env['resource_id'],accounts,session_factory=Session,max_login_seconds=2)
    assert result['state']=='succeeded' and result['command_id']==cmd['command_id']
    assert (accounts.folder(cmd['command_id'])/'ADMISSION_WAIT_1.json').exists()
