"""Full structured validation feedback, no truncation or program-written model repair."""
from copy import deepcopy
from jsonschema import ValidationError
from .serial_story_runtime_v2 import Runtime as PreviousRuntime, RepairRequired, PauseRequested, run_lock
from .serial_story_contract_v4 import COVERAGE_RULES, ContractErrors
from .corpus_screenplay_v1 import digest


class Runtime(PreviousRuntime):
    def phase(self,name,payload,schema,validator,prompt,role):
        if (self.run/'PAUSE_REQUESTED.json').exists(): raise PauseRequested()
        self.data['phases'][name]={'payload':payload,'role':role}
        payload=deepcopy(payload)
        if name.startswith('MATERIAL_') and not name.startswith('MATERIAL_REVIEW_'):
            payload['material_contract_rules']=COVERAGE_RULES
            prompt+='\n'+'\n'.join(COVERAGE_RULES.values())
        if name in self.data['corrections']: payload['required_corrections']=self.data['corrections'][name]
        self.save()
        for attempt in range(2):
            actual=name+(f'_FORMAT_{attempt}' if attempt else '')
            key=digest({'name':actual,'role':role,'prompt':prompt,'payload':payload,'schema':schema})
            value=self.native(key,actual,role,prompt,payload,schema)
            try: return validator(value)
            except (ValueError,ValidationError,TypeError,KeyError) as exc:
                errors=exc.errors if isinstance(exc,ContractErrors) else [{'code':type(exc).__name__,'message':str(exc)}]
                self.record(name+f'_INVALID_{attempt}.json',{'errors':errors,'value_sha256':digest(value)})
                if attempt: raise
                payload={**payload,'invalid_output':value,'validation_errors':errors,
                         'repair_instruction':'逐条修复全部列出的问题，返回完整当前产物；不得删除真实事实、伪造来源或只补一个字段。'}
