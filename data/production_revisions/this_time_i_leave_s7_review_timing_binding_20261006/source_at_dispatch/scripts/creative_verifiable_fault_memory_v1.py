"""Build immutable request input memory for an explicit manual full revision."""
from copy import deepcopy
import hashlib,json
VERSION='verified_local_fault_memory/v1'
BINDING_KEYS=('raw_script_sha256','local_input_sha256','current_shot')


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def build(receipts,current_binding,stage_prefix,current_feedback):
 if set(current_binding)!=set(BINDING_KEYS) or any(not current_binding[k] for k in BINDING_KEYS):raise ValueError('complete current source and start-state binding required')
 history=[];ordinals=set()
 for receipt in sorted(receipts,key=lambda row:row['ordinal']):
  if not receipt['label'].startswith(stage_prefix):continue
  if receipt['ordinal'] in ordinals:raise ValueError('duplicate prior revision identity')
  ordinals.add(receipt['ordinal']);request=receipt['request'];prov=request['input_provenance']
  if any(prov.get(k)!=current_binding[k] for k in BINDING_KEYS):raise ValueError('prior feedback belongs to changed source/shot/start state; re-audit, do not replay blindly')
  faults=[]
  for message in request['messages']:
   try:payload=json.loads(message['content'])
   except (ValueError,TypeError):continue
   if isinstance(payload,dict) and payload.get('verified_faults'):faults.append(deepcopy(payload['verified_faults']))
  history.append({'ordinal':receipt['ordinal'],'request_sha256':receipt.get('request_sha256',digest(request)),'known_status':receipt['status'],'verified_feedback_inputs':faults})
 return {'schema':VERSION,'active_binding':deepcopy(current_binding),'precedence':'Earlier verified constraints remain active unless explicitly corrected by a later source audit. Submit one complete new draft; never splice earlier outputs.','history':history,'current_verified_feedback':deepcopy(current_feedback),'automatic_retry':False,'model_output_manually_patched':False}
