"""Settle only the native closed tab bound to its original manual command."""


def settle_closed_manual_tabs(actor, resource, status):
    tabs={r['tab_id']:r for r in status.get('tabs',[]) if isinstance(r,dict) and r.get('tab_id')}
    closed=[]
    for task_id,tab_id in list(resource.manual_tasks.items()):
        tab=tabs.get(tab_id)
        if not tab or tab.get('closed') is not True or tab.get('role')!='manual':
            continue
        command=actor.store.get(task_id)
        if (not command or command['kind']!='manual' or command['state']!='waiting_human'
                or command['owner_id']!=actor.owner_id or command['generation']!=actor.generation
                or (command.get('result')or{}).get('tab_id')!=tab_id):
            continue
        if status.get('context_closed') is not True:
            resource.session.save_storage_state()
        actor.store.complete_waiting(task_id,actor.owner_id,actor.generation,
            result={'window_closed':True,'identity_verified':False,'closed_tab_id':tab_id,
                    'account_pause_changed':False,'other_tabs_preserved':True})
        resource.manual_tasks.pop(task_id)
        closed.append(task_id)
    if closed and not resource.manual_tasks and not getattr(resource,'console_tasks',{}):
        remaining=[r for r in tabs.values()if r.get('closed') is not True]
        # Only the controller's blank default page can be retired here. An
        # unclaimed/user tab or another human page always keeps its environment.
        if all(r.get('role')=='default' and r.get('url')=='about:blank' for r in remaining):
            resource.shutdown()
            resource.headless=True
            return True
    return False
