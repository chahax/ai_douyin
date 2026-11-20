"""Check declared speech timing. Does not prove generated audio speed or sync."""
import re

LINE=re.compile(r'^\s*-\s*(?P<speaker>[^【\n]+)【(?P<start>\d+(?:\.\d+)?)\s*[-—–]\s*(?P<end>\d+(?:\.\d+)?)秒】[：:]\s*(?P<text>.+)$',re.M)

def audit(body,kind):
    duration=45 if kind=='short' else 180
    rows=[];errors=[]
    for m in LINE.finditer(body):
        start,end=float(m['start']),float(m['end']);speech=m['text'].strip()
        count=len(re.sub(r'\s+','',speech));seconds=end-start
        rate=count/seconds if seconds>0 else None
        row={'speaker':m['speaker'].strip(),'start':start,'end':end,'text':speech,'characters_including_punctuation':count,'declared_characters_per_second':rate}
        rows.append(row)
        if start<0 or end>duration or seconds<=0:errors.append(f'Invalid speech range: {start}-{end}')
        if rate is not None and rate>6.00001:errors.append(f'Speech too dense: {start}-{end}, {rate:.2f} chars/s')
        if count>=8 and rate is not None and rate<3.5:errors.append(f'Speech too stretched: {start}-{end}, {rate:.2f} chars/s')
        if re.search(r'\d',speech):errors.append(f'Use spoken Chinese numbers at {start}')
    for prior,current in zip(rows,rows[1:]):
        if current['start']<prior['end']:errors.append(f'Unspecified overlapping speech at {current["start"]}')
    total=sum(r['characters_including_punctuation'] for r in rows)
    minimum=150 if kind=='short' else 620
    if total<minimum:errors.append(f'Insufficient spoken material for requested active pacing: {total} < {minimum}')
    if not rows:errors.append('Missing machine-readable speech timings')
    return {'schema':'cohort_declared_pacing/v1','kind':kind,'duration_seconds':duration,
        'declared_dialogue_characters':total,'declared_speech_seconds':sum(r['end']-r['start'] for r in rows),
        'rows':rows,'errors':errors,'passed':not errors,
        'scope':'Only declared text timing. Not actual audio articulation, speaker voice, mouth sync or performance approval.'}
