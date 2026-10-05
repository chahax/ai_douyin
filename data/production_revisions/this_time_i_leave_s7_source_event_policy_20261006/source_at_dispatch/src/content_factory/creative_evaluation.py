"""Offline evaluation and honest cost accounting; no provider client is imported."""
from collections import defaultdict
from copy import deepcopy
import math
import statistics

DEFAULT_CONFIG={'schema_version':'creative_eval_config/v1','automatic_paid_execution':False,
 'dataset':{'approved_independent_cases':80,'holdout_cases':40,'categories':['action','interaction','space','camera'],
            'per_category_error':10,'per_category_correct':10,'holdout_per_category_error':5,'holdout_per_category_correct':5,'repetitions':3,'screening_development_cases':12},
 'quality':{'major_recall':1.0,'all_recall':0.95,'per_category_recall':0.90,'correct_false_positive_max':0.05,'decidable_unknown_max':0.05,'references_valid':1.0,'required_evidence_present':1.0},
 'repair':{'cases':12,'min_success':11,'new_major_max':0,'per_category':3},
 'production':{'independent_briefs':6,'min_qualified':5,'max_content_repairs':1,'boundary_cases':10,'boundary_correct':10},
 'optimization':{'input_token_reduction':0.30,'comparable_model_cost_reduction':0.20,'median_latency_reduction':0.20,'p95_latency_increase_max':0.10,'human_active_minutes_increase_max':0.0}}


def rate(numerator,denominator):return None if denominator==0 else numerator/denominator


def wilson(n,n_total):
    if n_total==0:return None
    z=1.959963984540054;p=n/n_total;den=1+z*z/n_total
    center=(p+z*z/(2*n_total))/den;half=z*math.sqrt(p*(1-p)/n_total+z*z/(4*n_total*n_total))/den
    return [max(0,center-half),min(1,center+half)]


def metric(n,d):return {'numerator':n,'denominator':d,'rate':rate(n,d),'wilson_95':wilson(n,d)}


def validate_dataset(cases,config=None):
    config=config or DEFAULT_CONFIG;ids=[c['case_id'] for c in cases]
    if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_CASE_ID')
    approved=[c for c in cases if c['label_status']=='approved']
    for case in approved:
        if not case.get('adjudication',{}).get('approved_by') or not case['adjudication'].get('approved_at'):raise ValueError('APPROVED_LABEL_MISSING_ADJUDICATION')
    splits=defaultdict(set)
    for case in cases:splits[case['source_family']].add(case['split'])
    leaks=[family for family,parts in splits.items() if 'development' in parts and 'holdout' in parts]
    holdout=[c for c in approved if c['split']=='holdout' and not c.get('used_for_prompt_tuning',False)]
    independent={c['independence_group'] for c in approved};failures=[]
    cfg=config['dataset']
    if len(independent)<cfg['approved_independent_cases']:failures.append('APPROVED_INDEPENDENT_SAMPLE_SHORTFALL')
    if len({c['independence_group'] for c in holdout})<cfg['holdout_cases']:failures.append('FROZEN_HOLDOUT_SHORTFALL')
    if leaks:failures.append('SOURCE_FAMILY_SPLIT_LEAKAGE')
    for category in cfg['categories']:
        for kind,required in [('error',cfg['per_category_error']),('correct',cfg['per_category_correct'])]:
            selected={c['independence_group'] for c in approved if c['category']==category and c['case_kind']==kind}
            if len(selected)<required:failures.append(f'CATEGORY_SHORTFALL:{category}:{kind}')
        for kind,required in [('error',cfg['holdout_per_category_error']),('correct',cfg['holdout_per_category_correct'])]:
            selected={c['independence_group'] for c in holdout if c['category']==category and c['case_kind']==kind}
            if len(selected)<required:failures.append(f'HOLDOUT_CATEGORY_SHORTFALL:{category}:{kind}')
    return {'case_count':len(cases),'approved_case_count':len(approved),'candidate_case_count':len(cases)-len(approved),
            'approved_independent_count':len(independent),'holdout_count':len(holdout),'source_family_count':len(splits),
            'failures':failures,'qualified':not failures,'gold_labels_missing':len(cases)-len(approved),'source_family_leaks':leaks}


def score_review_runs(cases,runs,config=None):
    config=config or DEFAULT_CONFIG;by_id={c['case_id']:c for c in cases};seen=set();groups=defaultdict(list)
    for row in runs:
        key=(row['variant'],row['repeat'],row['case_id'])
        if key in seen:raise ValueError('DUPLICATE_EVALUATION_EXECUTION')
        seen.add(key)
        if row['case_id'] not in by_id:raise ValueError('UNKNOWN_EVALUATION_CASE')
        groups[(row['variant'],row['repeat'])].append(row)
    results=[]
    for (variant,repeat),rows in sorted(groups.items()):
        # Candidates may be inspected, but cannot contribute to acceptance rates.
        usable=[r for r in rows if by_id[r['case_id']]['label_status']=='approved' and by_id[r['case_id']]['split']=='holdout' and not by_id[r['case_id']].get('used_for_prompt_tuning',False) and by_id[r['case_id']]['case_kind'] in ('error','correct')]
        major_n=major_d=all_n=all_d=fp=correct=correct_unknown=unknown=refs=evidence=0;categories=defaultdict(lambda:[0,0]);major_passes=[]
        for row in usable:
            case=by_id[row['case_id']];expected=case.get('expected_issues',[])
            found=set(row.get('found_issue_ids',[])) if row['status']=='failed' else set()
            majors=[i['issue_id'] for i in expected if i['severity'] in ('major','blocking')]
            major_d+=len(majors);major_n+=len(set(majors)&found)
            all_d+=len(expected);all_n+=len({i['issue_id'] for i in expected}&found)
            categories[case['category']][0]+=len({i['issue_id'] for i in expected}&found);categories[case['category']][1]+=len(expected)
            if majors and row['status']=='passed':major_passes.append(row['case_id'])
            if case['case_kind']=='correct':
                correct+=1;fp+=int(row['status']=='failed' or bool(row.get('found_issue_ids')))
                correct_unknown+=int(row['status']=='unknown' and row.get('unknown_disposition','review_required') in ('review_required','blocked'))
            unknown+=int(row['status']=='unknown' and row.get('unknown_disposition','review_required') in ('review_required','blocked'))
            refs+=int(row.get('references_valid') is True);evidence+=int(row.get('required_evidence_present') is True)
        stats={'major_recall':metric(major_n,major_d),'all_recall':metric(all_n,all_d),'correct_false_positive':metric(fp,correct),'correct_unknown_blocked':metric(correct_unknown,correct),
               'decidable_unknown':metric(unknown,len(usable)),'references_valid':metric(refs,len(usable)),'required_evidence_present':metric(evidence,len(usable)),
               'per_category_recall':{k:metric(*v) for k,v in categories.items()},'major_passed_case_ids':major_passes}
        failures=[];q=config['quality']
        for key,limit in [('major_recall',q['major_recall']),('all_recall',q['all_recall']),('references_valid',1),('required_evidence_present',1)]:
            if stats[key]['rate'] is None or stats[key]['rate']<limit:failures.append(key)
        for key,limit in [('correct_false_positive',q['correct_false_positive_max']),('decidable_unknown',q['decidable_unknown_max'])]:
            if stats[key]['rate'] is None or stats[key]['rate']>limit:failures.append(key)
        for category in config['dataset']['categories']:
            value=stats['per_category_recall'].get(category,metric(0,0))
            if value['rate'] is None or value['numerator']<math.ceil(q['per_category_recall']*value['denominator']):failures.append('per_category:'+category)
        results.append({'variant':variant,'repeat':repeat,'eligible_count':len(usable),'excluded_unapproved_or_development':len(rows)-len(usable),'metrics':stats,'failures':failures,'quality_passed':not failures})
    dataset=validate_dataset(cases,config);variants={r['variant'] for r in runs};needed=config['dataset']['repetitions']
    complete=bool(variants) and all({r['repeat'] for r in results if r['variant']==v}==set(range(1,needed+1)) for v in variants)
    expected={c['case_id'] for c in cases if c['label_status']=='approved' and c['split']=='holdout' and c['case_kind'] in ('error','correct') and not c.get('used_for_prompt_tuning',False)}
    complete=complete and all({r['case_id'] for r in rows}==expected for rows in groups.values())
    flip=[]
    for variant in variants:
        outcomes=defaultdict(set)
        for row in runs:
            if row['variant']==variant:outcomes[row['case_id']].add(row['status'])
        flip.extend({'variant':variant,'case_id':cid} for cid,statuses in outcomes.items() if len(statuses)>1 and any(i['severity'] in ('major','blocking') for i in by_id[cid].get('expected_issues',[])))
    return {'dataset':dataset,'per_repeat':results,'complete_repetitions':complete,'major_conclusion_flips':flip,
            'holdout_repeated_validation_passed':dataset['qualified'] and complete and not flip and all(r['quality_passed'] for r in results),
            'independence_warning':'Repeated results are correlated; do not count repeated executions as independent cases.'}


def normalize_call(record,source_path):
    meta=record.get('response_metadata',{});usage=meta.get('usage',{})
    def get(key):return meta.get(key,usage.get(key))
    return {'source_path':str(source_path),'response_id':meta.get('response_id'),'provider':meta.get('provider'),
            'requested_model':meta.get('requested_model'),'response_model':meta.get('response_model'),
            'input_tokens':get('prompt_tokens'),'output_tokens':get('completion_tokens'),'total_tokens':get('total_tokens'),
            'cache_hit_input_tokens':get('prompt_cache_hit_tokens'),'cache_miss_input_tokens':get('prompt_cache_miss_tokens'),
            'reasoning_tokens':get('reasoning_tokens'),'reasoning_included_in_output':None,
            'requested_at':record.get('started_at'),'completed_at':record.get('completed_at'),'latency_seconds':record.get('latency_seconds'),
            'price_version':meta.get('price_version'),'currency':meta.get('currency'),'billed_amount':meta.get('billed_amount'),
            'estimated_amount':None,'amount_status':'actual' if meta.get('billed_amount') is not None else 'unknown',
            'usage_receipt_available':bool(meta),'retry_or_repair_parent':record.get('source_sha256'),
            'cache_scenario':'natural_unknown' if get('prompt_cache_hit_tokens') is None else 'natural_reported'}


def estimate_call(call,price,*,cache_scenario='natural'):
    result=deepcopy(call);result.update(price_version=price['version'],currency=price['currency'],cache_scenario=cache_scenario)
    if call.get('billed_amount') is not None:return result
    output=call.get('output_tokens');hit=call.get('cache_hit_input_tokens');miss=call.get('cache_miss_input_tokens')
    if cache_scenario=='all_uncached_comparison':hit=0;miss=call.get('input_tokens')
    elif cache_scenario!='natural':raise ValueError('UNSUPPORTED_CACHE_SCENARIO')
    if None in (output,hit,miss):return result
    # Reasoning is never added a second time to completion tokens.
    result['estimated_amount']=(hit*price['cached_input_per_million']+miss*price['uncached_input_per_million']+output*price['output_per_million'])/1_000_000
    result['amount_status']='estimated';return result


def summarize_cost(calls,human_sessions,qualified_handoffs):
    unique=[];seen=set()
    for call in calls:
        key=(call.get('provider'),call.get('response_id')) if call.get('response_id') else None
        if key and key in seen:continue
        if key:seen.add(key)
        unique.append(call)
    providers={}
    for provider in sorted({c.get('provider') or 'unknown' for c in unique}):
        rows=[c for c in unique if (c.get('provider') or 'unknown')==provider]
        def total(field):return sum(c[field] for c in rows) if all(c.get(field) is not None for c in rows) else None
        money=defaultdict(list)
        for c in rows:money[c.get('currency') or 'unknown'].append(c)
        amounts={currency:{'amount':sum(c['billed_amount'] if c.get('billed_amount') is not None else c['estimated_amount'] for c in subset) if all(c.get('billed_amount') is not None or c.get('estimated_amount') is not None for c in subset) else None,
                          'actual_only':all(c.get('billed_amount') is not None for c in subset),'missing_amount_calls':sum(c.get('billed_amount') is None and c.get('estimated_amount') is None for c in subset)} for currency,subset in money.items()}
        providers[provider]={'calls':len(rows),'input_tokens':total('input_tokens'),'output_tokens':total('output_tokens'),'reported_total_tokens':total('total_tokens'),'cost_by_currency':amounts}
    human_complete=bool(human_sessions) and all(h.get('active_minutes') is not None and h.get('hourly_rate') is not None and h.get('currency') for h in human_sessions)
    human_by_currency=defaultdict(float)
    if human_complete:
        for h in human_sessions:human_by_currency[h['currency']]+=h['active_minutes']/60*h['hourly_rate']
    currencies={currency for p in providers.values() for currency in p['cost_by_currency']}
    total_model=None;combined=None;currency=None
    if len(currencies)==1 and 'unknown' not in currencies:
        currency=next(iter(currencies));amounts=[p['cost_by_currency'][currency]['amount'] for p in providers.values()]
        if all(a is not None for a in amounts):total_model=sum(amounts)
        if total_model is not None and human_complete and set(human_by_currency)=={currency}:combined=total_model+human_by_currency[currency]
    return {'call_count':len(unique),'providers':providers,'qualified_handoffs':qualified_handoffs,'model_cost':total_model,'total_cost_including_active_human':combined,'currency':currency,
            'human_active_minutes':sum(h['active_minutes'] for h in human_sessions) if human_sessions and all(h.get('active_minutes') is not None for h in human_sessions) else None,
            'human_wait_minutes':sum(h['wait_minutes'] for h in human_sessions) if human_sessions and all(h.get('wait_minutes') is not None for h in human_sessions) else None,
            'cost_per_qualified_handoff':combined/qualified_handoffs if qualified_handoffs>0 and combined is not None else None,
            'missing_fields_are_zero':False,'cross_currency_conversion':'not_performed; explicit dated FX required','actual_cost_reduction_verified':False}


def percentile95(values):
    if not values:return None
    values=sorted(values);index=(len(values)-1)*0.95;lo=math.floor(index);hi=math.ceil(index)
    return values[lo]+(values[hi]-values[lo])*(index-lo)


def optimization_admission(pairs,quality_passed,config=None):
    cfg=(config or DEFAULT_CONFIG)['optimization'];fields=('input_tokens','model_cost','wall_seconds','human_active_minutes');result={};failures=[]
    if not quality_passed:failures.append('QUALITY_GATE_NOT_PASSED')
    for field in fields:
        if not pairs or any(row.get(side,{}).get(field) is None for row in pairs for side in ('baseline','candidate')):
            result[field]={'status':'unverified','baseline':None,'candidate':None};failures.append('MISSING:'+field);continue
        old=[r['baseline'][field] for r in pairs];new=[r['candidate'][field] for r in pairs]
        a=statistics.median(old) if field=='wall_seconds' else sum(old);b=statistics.median(new) if field=='wall_seconds' else sum(new)
        reduction=(a-b)/a if a>0 else None;result[field]={'status':'measured','baseline':a,'candidate':b,'reduction':reduction}
        limit={'input_tokens':cfg['input_token_reduction'],'model_cost':cfg['comparable_model_cost_reduction'],'wall_seconds':cfg['median_latency_reduction'],'human_active_minutes':0}[field]
        if reduction is None or reduction<limit:failures.append('TARGET_NOT_MET:'+field)
        if field=='model_cost' and any(r.get('cost_comparable') is not True or r.get('actual_cost') is not True for r in pairs):failures.append('COST_NOT_ACTUAL_COMPARABLE')
        if field=='wall_seconds':
            old95=percentile95(old);new95=percentile95(new);result['p95_seconds']={'baseline':old95,'candidate':new95,'sample_count':len(pairs),'descriptive_only':True}
            if new95>old95*(1+cfg['p95_latency_increase_max']):failures.append('P95_REGRESSION')
    return {'optimization_verified':not failures,'metrics':result,'failures':failures}


def score_repair_runs(rows,config=None):
    cfg=(config or DEFAULT_CONFIG)['repair'];eligible=[r for r in rows if r.get('label_status')=='approved']
    ids=[r['case_id'] for r in eligible]
    if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_REPAIR_CASE')
    success=sum(r.get('original_major_resolved') is True and r.get('new_major_count')==0 for r in eligible)
    new_major=sum(r.get('new_major_count',0) for r in eligible if r.get('new_major_count') is not None)
    complete=all(r.get('new_major_count') is not None and r.get('original_major_resolved') is not None for r in eligible)
    categories={c:sum(r.get('category')==c for r in eligible) for c in (config or DEFAULT_CONFIG)['dataset']['categories']}
    passed=len(eligible)>=cfg['cases'] and success>=math.ceil(len(eligible)*cfg['min_success']/cfg['cases']) and new_major<=cfg['new_major_max'] and complete and all(n>=cfg['per_category'] for n in categories.values())
    return {'qualified':passed,'approved_cases':len(eligible),'success':metric(success,len(eligible)),'new_major_count':new_major if complete else None,'per_category_cases':categories,'required_cases':cfg['cases']}


def score_production_runs(normal,boundary,config=None):
    cfg=(config or DEFAULT_CONFIG)['production'];approved=[r for r in normal if r.get('human_review_approved') is True]
    independent={r['brief_source_id'] for r in normal};qualified=sum(r.get('qualified_handoff') is True and r.get('unresolved_major_count')==0 and r.get('content_repairs',999)<=cfg['max_content_repairs'] for r in approved)
    first=sum(r.get('qualified_handoff') is True and r.get('content_repairs')==0 and r.get('unresolved_major_count')==0 for r in approved)
    b_independent={r['case_id'] for r in boundary};bcorrect=sum(r.get('human_expected_route_approved') is True and r.get('actual_route')==r.get('expected_route') and r.get('silent_story_change') is False for r in boundary)
    if len(independent)!=len(normal) or len(b_independent)!=len(boundary):raise ValueError('REPEATED_BRIEF_OR_BOUNDARY_NOT_INDEPENDENT')
    return {'normal_passed':len(independent)>=cfg['independent_briefs'] and qualified>=math.ceil(len(normal)*cfg['min_qualified']/cfg['independent_briefs']),'boundary_passed':len(boundary)>=cfg['boundary_cases'] and bcorrect==len(boundary),
            'qualified':metric(qualified,len(normal)),'first_draft_qualified':metric(first,len(normal)),'boundary_correct':metric(bcorrect,len(boundary)),
            'unknown_human_review_count':len(normal)-len(approved)}
