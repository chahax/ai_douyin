"""Independent65536-token complete screenplay allowance; old client unchanged.

Official M3.1 Chat Completions max_completion_tokens limit is524288; this
bounded run selects65536 only for its complete_script stage. Parent transport
still owns exact serialized wire, endpoint, original response and single send.
"""
from copy import deepcopy
from scripts import creative_m31_flash_role_clients_v1 as original
from scripts.creative_resume_dispatch_v3 import digest

VERSION='creative_m31_screenplay_role_clients/v1'
BODY_CAP=65536
OFFICIAL='https://platform.minimax.cn/docs/api-reference/text-chat-openai'


def expected_wire_request(request):
    current=deepcopy(request)
    cap=current.get('parameters',{}).get('max_completion_tokens')
    if current.get('role')=='writer' and current.get('stage')=='complete_script':
        if type(cap) is not int or cap!=BODY_CAP:raise ValueError('screenplay body exact65536 output allowance required')
        # Reuse every old validation, then explicitly map the separately verified
        # output field. Never mutate old constants or an existing request.
        current['parameters']['max_completion_tokens']=original.WRITER_MAX_COMPLETION_TOKENS
        wire=original.expected_wire_request(current)
        wire['max_completion_tokens']=BODY_CAP
        return wire
    return original.expected_wire_request(current)


class ScreenplayRoleClients(original.M31FlashRoleClients):
    def __init__(self,*,expected_request,**kwargs):
        wire=expected_wire_request(expected_request)
        validation_request=deepcopy(expected_request)
        if validation_request['role']=='writer' and validation_request['stage']=='complete_script':
            validation_request['parameters']['max_completion_tokens']=original.WRITER_MAX_COMPLETION_TOKENS
        super().__init__(expected_request=validation_request,**kwargs)
        self._request=deepcopy(expected_request);self._request_sha256=digest(self._request)
        self._wire=wire;self._wire_sha256=digest(wire)

    def call(self,*args,**kwargs):
        evidence=kwargs.get('evidence')
        if evidence is not None:
            evidence.record('independent_screenplay_output_allowance',{'client_extension_version':VERSION,
                'logical_request_sha256':self._request_sha256,'max_completion_tokens':self._request['parameters']['max_completion_tokens'],
                'official_reference':OFFICIAL,'official_maximum':524288,'automatic_retry':False})
        return super().call(*args,**kwargs)


def make_client_factory(request,**kwargs):
    frozen=deepcopy(request)
    return lambda:ScreenplayRoleClients(expected_request=frozen,**kwargs)
