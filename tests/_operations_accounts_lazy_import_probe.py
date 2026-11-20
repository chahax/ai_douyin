"""Fresh-process import-only probe. Never construct services or call business APIs."""
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Windows platform discovery is not what is under test. Avoid its optional WMI/
# cmd probes while preserving real project dependency imports below.
platform._uname_cache=platform.uname_result(system='Windows',node='isolated-import-test',
    release='10',version='test',machine=os.environ.get('PROCESSOR_ARCHITECTURE','AMD64'))
platform._uname_cache.__dict__['processor']=''
counts={'external_process':0,'database_connect':0,'network_connect':0}
def blocked(kind):
    counts[kind]+=1
    raise AssertionError('Import attempted '+kind)
class NoPopen(subprocess.Popen):
    def __init__(self,*a,**kw):blocked('external_process')
subprocess.Popen=NoPopen
sqlite3.connect=lambda *a,**kw:blocked('database_connect')
sqlite3.dbapi2.connect=sqlite3.connect
socket.create_connection=lambda *a,**kw:blocked('network_connect')
class NoConnectSocket(socket.socket):
    def connect(self,*a,**kw):blocked('network_connect')
    def connect_ex(self,*a,**kw):blocked('network_connect')
socket.socket=NoConnectSocket

RUNTIME=('AccountRuntimeContext','AccountRuntimeError','AccountRuntimeService',
         'PreparedBrowserEnvironment','RuntimeIdentityCheck')
MODEL=('AccountBinding','AccountProfile','AccountRuntimeState','DouyinIdentity','stable_account_uuid')
REPOSITORY=('AccountBindingConflict','AccountBindingNotFound','AccountBindingRepository',
    'AccountOAuthStateError','AccountProfileConflict','AccountProfileNotFound','AccountProfileRepository',
    'AccountRuntimeUnavailable')
PLATFORM_MODELS=('BrowserSessionConfig','CommentQuery','CommentRecord','CommentSyncResult',
                 'PublishRequest','PublishResult','SessionState')
PLATFORM_LAZY={'BrowserSession':'browser_session','build_default_browser_session_config':'browser_session',
    'CommentWorkflow':'comment_workflow','DouyinAdapter':'douyin_adapter','PublishWorkflow':'publish_workflow'}
result={'mode':sys.argv[1],'guard_counts':counts,'business_functions_called':0}

if result['mode']=='light':
    p=importlib.import_module('src.operations_accounts')
    assert not any(n in p.__dict__ for n in RUNTIME)
    assert 'src.operations_accounts.runtime' not in sys.modules
    assert 'src.platform_adapter.browser_session' not in sys.modules
    assert set(p.__all__)==set(RUNTIME+MODEL+REPOSITORY)
    assert all(n in dir(p) for n in p.__all__)
    adapter=importlib.import_module('src.platform_adapter')
    assert not any(n in adapter.__dict__ for n in PLATFORM_LAZY)
    assert 'src.platform_adapter.browser_session' not in sys.modules
    assert set(adapter.__all__)==set(PLATFORM_MODELS)|set(PLATFORM_LAZY)
    assert all(n in dir(adapter) for n in adapter.__all__)
    result['runtime_and_browser_not_loaded']=True
elif result['mode']=='api':
    p=importlib.import_module('src.operations_accounts')
    for module,names in (('models',MODEL),('repository',REPOSITORY),('runtime',RUNTIME)):
        for n in names:
            value=getattr(p,n)
            assert value is getattr(importlib.import_module('src.operations_accounts.'+module),n)
            assert p.__dict__[n] is value
    names={};exec('from src.operations_accounts import *',names)
    assert all(names[n] is getattr(p,n) for n in p.__all__)
    try:getattr(p,'unknown_export')
    except AttributeError:pass
    else:raise AssertionError('Unknown export accepted')
    original=p.AccountRuntimeService
    runtime=importlib.import_module('src.operations_accounts.runtime')
    runtime.AccountRuntimeService=object()
    assert p.AccountRuntimeService is original
    result['public_api_identity_count']=len(p.__all__)
    adapter=importlib.import_module('src.platform_adapter')
    for n in adapter.__all__:
        module=PLATFORM_LAZY.get(n,'models')
        assert getattr(adapter,n) is getattr(importlib.import_module('src.platform_adapter.'+module),n)
        assert adapter.__dict__[n] is getattr(adapter,n)
    names={};exec('from src.platform_adapter import *',names)
    assert all(names[n] is getattr(adapter,n) for n in adapter.__all__)
    original=adapter.BrowserSession
    importlib.import_module('src.platform_adapter.browser_session').BrowserSession=object()
    assert adapter.BrowserSession is original
    result['platform_api_identity_count']=len(adapter.__all__)
elif result['mode']=='platform_failure_new':
    class FailedBrowser(importlib.abc.Loader):
        def create_module(self,spec):return None
        def exec_module(self,module):raise RuntimeError('controlled browser import failure')
    class BrowserFinder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname=='src.platform_adapter.browser_session':return importlib.util.spec_from_loader(fullname,FailedBrowser())
    finder=BrowserFinder();sys.meta_path.insert(0,finder)
    p=importlib.import_module('src.platform_adapter')
    try:p.BrowserSession
    except RuntimeError:pass
    else:raise AssertionError('Browser import failure was swallowed')
    assert sys.modules['src.platform_adapter'] is p and 'BrowserSession' not in p.__dict__
    sys.meta_path.remove(finder)
    assert p.BrowserSession is importlib.import_module('src.platform_adapter.browser_session').BrowserSession
    result['failed_child_preserves_platform_package']=True
elif result['mode'] in ('failure_new','failure_old'):
    class FailedRuntime(importlib.abc.Loader):
        def create_module(self,spec):return None
        def exec_module(self,module):raise RuntimeError('controlled runtime import failure')
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname=='src.operations_accounts.runtime':
                return importlib.util.spec_from_loader(fullname,FailedRuntime())
            if fullname=='src.operations_accounts' and result['mode']=='failure_old':
                return importlib.util.spec_from_file_location(fullname,
                    ROOT/'data/flow_development/operations_accounts_lazy_exports_20261116/BEFORE___init__.py',
                    submodule_search_locations=[str(ROOT/'src/operations_accounts')])
    finder=Finder();sys.meta_path.insert(0,finder)
    if result['mode']=='failure_old':
        try:importlib.import_module('src.operations_accounts')
        except RuntimeError:pass
        else:raise AssertionError('Old eager package unexpectedly imported')
        assert 'src.operations_accounts' not in sys.modules
        result['controlled_failure_removes_old_package']=True
    else:
        p=importlib.import_module('src.operations_accounts')
        try:p.AccountRuntimeService
        except RuntimeError:pass
        else:raise AssertionError('Runtime failure was swallowed')
        assert sys.modules['src.operations_accounts'] is p
        assert 'AccountRuntimeService' not in p.__dict__
        sys.meta_path.remove(finder)
        value=p.AccountRuntimeService
        assert value is importlib.import_module('src.operations_accounts.runtime').AccountRuntimeService
        result['failed_child_preserves_package_and_retry']=True
elif result['mode']=='concurrent':
    targets=['src.scheduler.deployment_maintenance','src.operations_accounts.browser_control',
        'src.operations_accounts.runtime','src.platform_adapter.browser_session',
        'src.platform_adapter.douyin_identity','src.operations_accounts',
        'export:AccountRuntimeService','platform_export:DouyinAdapter']
    gate=threading.Barrier(len(targets))
    def load(name):
        gate.wait(timeout=15)
        if name.startswith('export:'):
            p=importlib.import_module('src.operations_accounts');return getattr(p,name.split(':')[1])
        if name.startswith('platform_export:'):
            p=importlib.import_module('src.platform_adapter');return getattr(p,name.split(':')[1])
        return importlib.import_module(name)
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures=[pool.submit(load,n) for n in targets]
        values=[f.result(timeout=45) for f in futures]
    p=importlib.import_module('src.operations_accounts')
    assert values[6] is p.AccountRuntimeService
    assert values[7] is importlib.import_module('src.platform_adapter').DouyinAdapter
    assert all(getattr(p,n) is getattr(importlib.import_module('src.operations_accounts.runtime'),n) for n in RUNTIME)
    result['actual_cold_paths']=targets;result['threads']=len(targets)
else:raise AssertionError('Unknown probe mode')
assert all(v==0 for v in counts.values()),counts
print(json.dumps(result,sort_keys=True))
