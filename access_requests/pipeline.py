"""Validated extraction followed by deterministic human-review routing."""
from .validation import validate_reply
from .prompt import PROMPT

REQUIRED = ('request_id','request_date','requester','team','system','environment',
            'permission','business_purpose','start_date','end_date','manager')

def route(extraction, document_id):
    if extraction['kind'] in ('other', None) or any(extraction[k] is None for k in REQUIRED):
        return 'needs-information','IT Service Desk','clarify'
    return 'review','System Owner','review-request'

def process(document, provider):
    reply = provider.extract(PROMPT + '\n' + document.message)
    extraction = validate_reply(reply)
    status, owner, action = route(extraction, document.document_id)
    return dict(document_id=document.document_id, source_sha256=document.source_sha256,
                extraction=extraction,status=status,owner=owner,next_action=action,
                error=None,response_source=reply.get('response_source',provider.response_source))
