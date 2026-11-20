"""Three durable daily opportunities; no offline backlog or interaction policy."""
import datetime
import hashlib
import json
import secrets

TABLE='playback_random_policies'
WINDOWS=((540,720),(840,1020),(1140,1320))
ZONE=datetime.timezone(datetime.timedelta(hours=8))


def read(db,account_uuid):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():return None
    row=db.execute(f'SELECT config FROM {TABLE} WHERE account_uuid=?AND enabled=1',(account_uuid,)).fetchone()
    return json.loads(row[0])if row else None


def normalize(value,old=None):
    if value is None:return None
    if value!={'mode':'random_daily_three'}:raise ValueError('随机播放仅支持每日三个固定范围内的随机时段')
    return old or {'mode':'random_daily_three','timezone':'Asia/Shanghai','windows':[list(x)for x in WINDOWS],
        'daily_limit':3,'seed':secrets.token_hex(16)}


def save(db,account_uuid,account_key,config):
    if config is None:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone():
            db.execute(f'UPDATE {TABLE} SET enabled=0 WHERE account_uuid=?',(account_uuid,))
        return
    db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(account_uuid TEXT PRIMARY KEY,account_key TEXT NOT NULL,
        enabled INTEGER NOT NULL,config TEXT NOT NULL)''')
    old=db.execute(f'SELECT account_key FROM {TABLE} WHERE account_uuid=?',(account_uuid,)).fetchone()
    if old and old[0]!=account_key:raise ValueError('随机计划账号绑定不一致')
    db.execute(f'''INSERT INTO {TABLE} VALUES(?,?,1,?) ON CONFLICT(account_uuid)DO UPDATE SET
        enabled=1,config=excluded.config''',(account_uuid,account_key,json.dumps(config,sort_keys=True)))


def next_due(db,account_uuid,config,now):
    """Count every original opportunity, including failures; never create a retry."""
    day=datetime.datetime.fromtimestamp(now,ZONE).date()
    for offset in range(3):
        date=day+datetime.timedelta(days=offset)
        start=datetime.datetime.combine(date,datetime.time(),ZONE).timestamp()
        rows=db.execute('SELECT started_at FROM playback_runs WHERE account_uuid=?AND started_at>=?AND started_at<?',
            (account_uuid,start,start+86400)).fetchall()
        if len(rows)>=3:continue
        used=set()
        for row in rows:
            minute=(row[0]-start)/60
            for i,(low,high)in enumerate(WINDOWS):
                if low<=minute<high:used.add(i)
        for i,(low,high)in enumerate(WINDOWS):
            if i in used or start+high*60<=now:continue
            token=f"{config['seed']}:{account_uuid}:{date.isoformat()}:{i}"
            seconds=int(hashlib.sha256(token.encode()).hexdigest(),16)%((high-low)*60)
            due=start+low*60+seconds
            return due
    raise ValueError('随机计划无法找到下一个有效时段')
