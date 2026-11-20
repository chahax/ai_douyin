"""Explicitly opted-in, minimized handoff of the original loaded feed tab."""
import sqlite3
from pathlib import Path


def enabled(account, path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='retained_feed_preferences'").fetchone():
            return False
        row=db.execute('SELECT enabled FROM retained_feed_preferences WHERE account_uuid=?',(account,)).fetchone()
        return bool(row and row[0]==1)


def minimize(page):
    """Native browser window state only; never changes challenge or page state."""
    cdp=page.context.new_cdp_session(page)
    try:
        target=cdp.send('Browser.getWindowForTarget')
        cdp.send('Browser.setWindowBounds',{'windowId':target['windowId'],
                                         'bounds':{'windowState':'minimized'}})
        bounds=cdp.send('Browser.getWindowBounds',{'windowId':target['windowId']})
        if bounds.get('bounds',{}).get('windowState')!='minimized':
            raise RuntimeError('Browser minimization not confirmed')
        return {'minimized':True}
    finally:
        cdp.detach()


def retain(resource, page, tab_id):
    result=page._cmd('minimize_window')
    if result.get('minimized') is not True:
        raise RuntimeError('Original window minimization not confirmed')
    resource.retained_feed_tab=tab_id
    resource.headless=False


def take_tab(resource, context):
    command=getattr(context,'command',{})
    tab=getattr(resource,'retained_feed_tab',None)
    if tab and command.get('kind')=='maintenance' and command.get('payload',{}).get('mode')=='playback':
        resource.retained_feed_tab=None
        return tab
    return None
