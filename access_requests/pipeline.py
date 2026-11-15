"""Validated extraction followed by deterministic human-review routing."""
import re
from .validation import validate_reply
from .prompt import PROMPT

REQUIRED = ('request_id','request_date','requester','team','system','environment',
            'permission','business_purpose','start_date','end_date','manager')

def route(extraction, document_id, message=""):
    attack = re.search(r"SYSTEM OVERRIDE:.*", message, re.I | re.S)
    if attack or any("override" in i.lower() for i in extraction["issues"]):
        if attack and attack[0] not in extraction["supporting_quotes"]:
            extraction["supporting_quotes"].append(attack[0])
        if not any("override" in i.lower() for i in extraction["issues"]):
            extraction["issues"].append("instruction-override attempt")
        return "review", "IT Service Desk", "inspect-message"
    issues = extraction['issues']
    if extraction['kind'] == 'withdrawal' and extraction['request_id'] and extraction['request_date']:
        return 'review','IT Service Desk','confirm-withdrawal'
    identifier = re.fullmatch(r'(IT-\d+)\.json', document_id)
    mismatch = identifier and extraction['request_id'] and identifier[1] != extraction['request_id']
    reversed_dates = (extraction['start_date'] and extraction['end_date']
                      and extraction['start_date'] > extraction['end_date'])
    if mismatch and not any('mismatch' in i for i in issues):
        issues.append('identifier mismatch: ' + document_id + ' / ' + extraction['request_id'])
    if reversed_dates and not any('start_date' in i for i in issues):
        issues.append('start_date after end_date')
    if (extraction['kind'] in ('other', None) or any(extraction[k] is None for k in REQUIRED)
            or mismatch or reversed_dates or any('conflict' in i.lower() for i in issues)):
        return 'needs-information','IT Service Desk','clarify'
    if extraction['environment'] == 'production' or extraction['permission'] in ('write','admin'):
        return 'review','Security Review','review-risk-then-owner'
    return 'review','System Owner','review-request'

def process(document, provider):
    reply = provider.extract(PROMPT + '\n' + document.message)
    extraction = validate_reply(reply)
    status, owner, action = route(extraction, document.document_id, document.message)
    return dict(document_id=document.document_id, source_sha256=document.source_sha256,
                extraction=extraction,status=status,owner=owner,next_action=action,
                error=None,response_source=reply.get('response_source',provider.response_source))
