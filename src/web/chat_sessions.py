"""User-scoped chat UI actions and durable, exact-plan confirmation receipts."""
from contextlib import contextmanager
import hashlib
import json
import threading
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base
from src.memory.models import ConversationSession, ConversationMessage

_locks = {}
_guard = threading.Lock()
ReceiptBase = declarative_base()


class ChatActionReceipt(ReceiptBase):
    __tablename__ = 'chat_ui_action_receipts'
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False)
    session_id = Column(Integer, nullable=False)
    plan_sha = Column(String(64), nullable=False)
    action = Column(String(16), nullable=False)
    status = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'session_id', 'plan_sha'),)


def digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def session_token(row):
    return digest([row.id,row.user_id,row.title,
        row.created_at.isoformat() if row.created_at else None,
        row.updated_at.isoformat() if row.updated_at else None])


@contextmanager
def user_lock(user):
    if not isinstance(user, str) or not user.strip():
        raise ValueError('Authenticated user required')
    with _guard:
        lock = _locks.setdefault(user, threading.RLock())
    with lock:
        yield


def factory():
    from src.shared.database import SessionLocal
    return SessionLocal()


def view(user):
    if not isinstance(user,str) or not user.strip():
        raise ValueError('Authenticated user required')
    with factory() as db:
        active_rows = db.query(ConversationSession).filter_by(user_id=user,status='active').limit(2).all()
        if len(active_rows)>1:
            raise ValueError('Multiple active sessions require reconciliation')
        active = active_rows[0] if active_rows else None
        rows = db.query(ConversationSession).filter_by(user_id=user,status='archived').order_by(ConversationSession.updated_at.desc()).limit(20).all()
        messages = []
        if active:
            recent = db.query(ConversationMessage).filter_by(session_id=active.id).order_by(ConversationMessage.id.desc()).limit(200).all()
            messages = [{'role': r.role, 'content': r.content} for r in reversed(recent) if r.role in ('user','assistant')]
        receipt = None
        has_receipts=inspect(db.get_bind()).has_table(ChatActionReceipt.__tablename__)
        unsettled=set()
        unresolved=[]
        if has_receipts:
            unsettled={r[0] for r in db.query(ChatActionReceipt.session_id).filter(
                ChatActionReceipt.user_id==user,ChatActionReceipt.status.in_(('executing','outcome_unknown')))}
            unresolved=[{'session_id':r.session_id,'plan_sha':r.plan_sha,'status':r.status}
                for r in db.query(ChatActionReceipt).filter(ChatActionReceipt.user_id==user,
                    ChatActionReceipt.status.in_(('executing','outcome_unknown'))).order_by(ChatActionReceipt.id.desc()).limit(20)]
        if active and active.pending_plan and has_receipts:
            claimed = db.query(ChatActionReceipt).filter_by(user_id=user,session_id=active.id,plan_sha=digest(active.pending_plan)).first()
            receipt = claimed.status if claimed else None
        return {'active': {'id': active.id, 'title': active.title, 'pending': active.pending_plan, 'receipt':receipt,'token':session_token(active)} if active else None,
                'archived': [{'id': r.id, 'title': r.title,'token':session_token(r),
                              'delete_blocked':bool(r.pending_plan) or r.id in unsettled} for r in rows],
                'messages': messages,'unresolved':unresolved}


def new(user, *, expected_active=None):
    with user_lock(user), factory() as db:
        if expected_active is not None and not db.query(ConversationSession).filter_by(id=expected_active,user_id=user,status='active').first():
            return False
        db.query(ConversationSession).filter_by(user_id=user,status='active').update({'status':'archived','archived_at':datetime.utcnow()})
        db.add(ConversationSession(user_id=user,title='新会话',status='active'))
        db.commit()
        return True


def rename(user, session_id, title):
    if not isinstance(title,str) or not title.strip() or len(title.strip()) > 255:
        return False
    with user_lock(user), factory() as db:
        changed = db.query(ConversationSession).filter_by(id=session_id,user_id=user).update({'title':title.strip(),'updated_at':datetime.utcnow()})
        db.commit()
        return bool(changed)


def activate(user, session_id):
    with user_lock(user), factory() as db:
        row = db.query(ConversationSession).filter_by(id=session_id,user_id=user,status='archived').first()
        if not row:
            return False
        db.query(ConversationSession).filter_by(user_id=user,status='active').update({'status':'archived','archived_at':datetime.utcnow()})
        row.status, row.archived_at = 'active', None
        db.commit()
        return True


def delete(user, session_id, *, confirmed=False, expected_token=None):
    if confirmed is not True:
        return False
    with user_lock(user), factory() as db:
        row = db.query(ConversationSession).filter_by(id=session_id,user_id=user,status='archived').first()
        if not row or row.pending_plan or not expected_token or expected_token!=session_token(row):
            return False
        if inspect(db.get_bind()).has_table(ChatActionReceipt.__tablename__) and db.query(ChatActionReceipt).filter(
            ChatActionReceipt.user_id==user,ChatActionReceipt.session_id==session_id,
            ChatActionReceipt.status.in_(('executing','outcome_unknown'))).first():
            return False
        db.delete(row)
        db.commit()
        return True


def resolve(user, session_id, plan_sha, action, execute=None):
    """Unknown execution receipts are retained and never automatically retried."""
    if action not in ('confirm','cancel'):
        raise ValueError('Invalid action')
    with user_lock(user):
        with factory() as db:
            row = db.query(ConversationSession).filter_by(id=session_id,user_id=user,status='active').first()
            if not row or not row.pending_plan or digest(row.pending_plan) != plan_sha:
                raise ValueError('Original plan changed')
            # Schema is created only on this explicit action, never a page read.
            ChatActionReceipt.__table__.create(db.get_bind(),checkfirst=True)
            claim = ChatActionReceipt(user_id=user,session_id=session_id,plan_sha=plan_sha,action=action,status='executing')
            db.add(claim)
            if action == 'cancel':
                row.pending_plan = None
                claim.status = 'cancelled'
                db.add(ConversationMessage(session_id=session_id,role='assistant',content='已取消，未执行计划。'))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise ValueError('Original plan already claimed') from exc
        if action == 'cancel':
            return None
        try:
            response = execute(session_id)
            if response is None:
                raise RuntimeError('No confirmed agent response')
        except BaseException:
            with factory() as db:
                db.query(ChatActionReceipt).filter_by(user_id=user,session_id=session_id,plan_sha=plan_sha).update({'status':'outcome_unknown'})
                db.commit()
            raise
        with factory() as db:
            db.query(ChatActionReceipt).filter_by(user_id=user,session_id=session_id,plan_sha=plan_sha).update({'status':'returned'})
            db.commit()
        return response
