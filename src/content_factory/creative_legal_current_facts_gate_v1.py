"""Scoped current resignation-scene fact checks; no prose rewriting/quality claim."""
import re

def check_current_scene_facts(script):
    findings=[]
    rules=[('UNAPPROVED_WORKING_DATE',r'周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今天.{0,12}(?:交接|交上|收上|返工|不交)'),('UNAPPROVED_SYSTEM_CAUSE',r'系统'),('UNAPPROVED_PERSONAL_HISTORY',r'带我|带过我|家里|家人'),('UNAPPROVED_PENALTY',r'挨训|扣.{0,8}(?:活|工资|钱)|处罚|返工'),('UNAPPROVED_FOLLOWUP_PROMISE',r'后面的事.{0,12}(?:我|姐).{0,8}跟|我回去再想.{0,5}(?:办法|怎么办)')]
    for b in script['beats']:
        for i,q in enumerate(b['steps'],1):
            if q['kind']!='dialogue':continue
            for code,pattern in rules:
                if re.search(pattern,q['text']):findings.append({'code':code,'evidence_ref':f"{b['id']}.S{i:02}",'evidence_text':q['text']})
    b1=script['beats'][0]['steps'];notice=[];deliver=[]
    for i,q in enumerate(b1):
        if q['kind']=='dialogue' and q['speaker'].startswith('周姐') and '公司' in q['text'] and re.search(r'(?:让|要|要求|决定|不留|不续).{0,30}(?:离开|离职|走|不留|不要)',q['text']):notice.append(i)
        if q['kind']=='action' and re.search(r'推|送',q['text']) and re.search(r'纸|申请|笔',q['text']):deliver.append(i)
    if not notice:findings.append({'code':'COMPANY_DEPARTURE_NOTICE_NOT_EXPLICIT','evidence_ref':'B1','evidence_text':'No actual Zhou dialogue explicitly names company-required departure; premise/event excluded.'})
    if deliver and (not notice or deliver[0]<notice[0]):findings.append({'code':'PAPER_BEFORE_COMPANY_NOTICE','evidence_ref':f'B1.S{deliver[0]+1:02}','evidence_text':b1[deliver[0]]['text']})
    return findings
