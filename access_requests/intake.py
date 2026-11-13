"""Validated extractions and deterministic human review routing."""
import re
from pathlib import Path
from .validation import validate_response

REQUIRED = ('request_id', 'request_date', 'requester', 'team', 'system',
            'environment', 'permission', 'business_purpose', 'start_date', 'end_date', 'manager')


def route(source, extraction):
    issues = extraction['issues']
    def issue(text):
        if text not in issues:
            issues.append(text)
    for field in REQUIRED:
        if extraction[field] is None:
            issue('Missing or unresolved ' + field.replace('_', ' '))
    mismatch = (extraction['request_id'] is not None and
                extraction['request_id'] != Path(source.document_id).stem)
    if mismatch:
        issue('Identifier mismatch with document filename')
    reversed_dates = (extraction['start_date'] and extraction['end_date'] and
                      extraction['start_date'] > extraction['end_date'])
    if reversed_dates:
        issue('Start date after end date')
    override = re.search(r'system override|bypass approval|highest.priority system|display the api key',
                         source.message, re.I)
    if override or any(re.search(r'override|injection', text, re.I) for text in issues):
        issue('Instruction override attempt; treat message as data')
        return 'review', 'IT Service Desk', 'inspect-message'
    if extraction['kind'] == 'withdrawal' and extraction['request_id'] and extraction['request_date']:
        return 'review', 'IT Service Desk', 'confirm-withdrawal'
    if (extraction['kind'] not in ('new', 'change') or mismatch or reversed_dates or
            any(extraction[field] is None for field in REQUIRED) or
            any(re.search(r'conflict|unresolved', text, re.I) for text in issues)):
        return 'needs-information', 'IT Service Desk', 'clarify'
    if extraction['environment'] == 'production' or extraction['permission'] in ('write', 'admin'):
        return 'review', 'Security Review', 'review-risk-then-owner'
    return 'review', 'System Owner', 'review-request'


def process_response(source, reply):
    extraction = validate_response(reply, source.message)
    status, owner, action = route(source, extraction)
    return dict(document_id=source.document_id, source_sha256=source.source_sha256,
                extraction=extraction, status=status, owner=owner, next_action=action,
                error=None, response_source=reply['response_source'])
