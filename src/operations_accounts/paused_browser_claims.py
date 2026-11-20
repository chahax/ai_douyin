"""Do not transiently claim background maintenance while recovery is paused."""
from pathlib import Path
import sqlite3


REPAIR_KINDS = ('manual','recovery','read','publication_verify',
                'publication_reconcile','publication_comment_settlement')


def install(actor, resource, *, path=None):
    """Install on this live actor's own Store, leaving all original queue rows intact."""
    previous = actor.store.claim_next
    if getattr(previous, '_paused_browser_claim_guard', False):
        return
    if path is None:
        from src.scheduler.account_refresh import DB
        path = DB
    path = Path(path).resolve()

    def claim(account_id, binding_version, owner_id, generation, *, above_priority=None,
              kinds=None, parent_command_id=None):
        # This RO check happens before acquiring the browser writer reservation.
        # Unknown control state keeps ordinary maintenance queued as well.
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro',uri=True,timeout=1) as db:
                control = db.execute('SELECT state FROM account_controls WHERE account_uuid=?',
                                     (account_id,)).fetchone()
            active = bool(control and control[0] == 'active')
        except sqlite3.Error:
            active = False
        if (account_id == actor.account_id and (not active or resource.manual_tasks
                or getattr(resource,'console_tasks',{}))):
            kinds = tuple(k for k in (REPAIR_KINDS if kinds is None else kinds) if k in REPAIR_KINDS)
        return previous(account_id,binding_version,owner_id,generation,
            above_priority=above_priority,kinds=kinds,parent_command_id=parent_command_id)

    claim._paused_browser_claim_guard = True
    actor.store.claim_next = claim
