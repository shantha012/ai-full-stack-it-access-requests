"""Validated extraction followed by deterministic human-review routing."""
import re
from .validation import validate_reply, InvalidResponse
from .provider import ProviderError
import shlex
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

def error_record(document, category, explanation, origin='mock'):
    return dict(document_id=document.document_id, source_sha256=document.source_sha256,
                extraction=None,status='error',owner='IT Service Desk',next_action='retry-extraction',
                error=dict(category=category,message=explanation,
                           retry_command='python -m access_requests retry ' + shlex.quote(document.document_id)),
                response_source=origin)

def process(document, provider, settings=None):
    from .config import Settings
    settings = settings or Settings()
    try:
        reply = (provider.extract_source(document.message) if hasattr(provider,'extract_source')
                 else provider.extract(settings.prompt + '\n' + document.message))
        extraction = validate_reply(reply)
    except ProviderError:
        # Exception payloads may contain credentials; never retain them.
        return error_record(document,'provider','Provider unavailable; retry this document.',provider.response_source)
    except InvalidResponse:
        category = ('refusal' if reply.get('status') == 'refused' or reply.get('refusal') else
                    'incomplete' if reply.get('status') != 'completed' else 'invalid-response')
        return error_record(document,category,category + ': retry extraction.',provider.response_source)
    status, owner, action = route(extraction, document.document_id, document.message)
    if owner == 'System Owner':
        match = re.search(r'Complete staging/read requests go to (.+?) with status review', settings.policy)
        if match:
            owner = match[1]
    return dict(document_id=document.document_id, source_sha256=document.source_sha256,
                extraction=extraction,status=status,owner=owner,next_action=action,
                error=None,response_source=reply.get('response_source',provider.response_source))

class Dispatcher:
    def __init__(self):
        self.documents = {}
        self.results = {}

    def run(self, document, provider):
        self.documents[document.document_id] = document
        self.results[document.document_id] = process(document, provider)
        return self.results[document.document_id]

    def retry(self, document_id, provider):
        return self.run(self.documents[document_id], provider)
