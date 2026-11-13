"""Compare observations with independently source-authored plan expectations."""
import json
from pathlib import Path

FIELDS = ('request_id', 'request_date', 'kind', 'requester', 'team', 'system',
          'environment', 'permission', 'start_date', 'end_date', 'manager')


def load_oracles(directory):
    return [json.loads((Path(directory) / f'T{i:02}.json').read_text()) for i in range(5, 26)]


def compare(records, oracles):
    by_document = {}
    for record in records:
        if record['document_id'] in by_document:
            raise ValueError('Duplicate current observation for ' + record['document_id'])
        by_document[record['document_id']] = record
    report = dict(exact=0, total=len(oracles) * len(FIELDS), purpose_exact=0,
                  purpose_total=len(oracles), factual_errors=[], purpose_differences=[],
                  quote_errors=[], issue_errors=[], observation='mock' if records and all(
                      r.get('response_source') == 'mock' for r in records) else 'provider or mixed',
                  response_sources=sorted({r.get('response_source', 'unknown') for r in records}),
                  configurations=[], sources=[])
    for record in records:
        config = record.get('provenance', {})
        if config not in report['configurations']:
            report['configurations'].append(config)
    for oracle in oracles:
        document = oracle['document_id']
        record = by_document.get(document, {})
        actual = record.get('extraction') or {}
        report['sources'].append(dict(document_id=document, input_path=oracle['input_path'],
                                      expected_source=oracle['plan_source'], message=oracle['message'],
                                      expected_facts=oracle['facts']))
        for field in FIELDS:
            if field in actual and actual[field] == oracle['facts'][field]:
                report['exact'] += 1
            else:
                report['factual_errors'].append(dict(document_id=document, field=field,
                    expected=oracle['facts'][field], actual=actual.get(field, '<missing>')))
        purpose = 'business_purpose'
        if purpose in actual and actual[purpose] == oracle['facts'][purpose]:
            report['purpose_exact'] += 1
        else:
            report['purpose_differences'].append(dict(document_id=document,
                expected=oracle['facts'][purpose], actual=actual.get(purpose, '<missing>')))
        quotes = actual.get('supporting_quotes')
        if not isinstance(quotes, list) or not quotes or any(
                not isinstance(q, str) or q not in oracle['message'] for q in quotes):
            report['quote_errors'].append(document)
        issue_text = ' '.join(actual.get('issues', [])).lower().replace('_', ' ')
        if any(not any(term.lower() in issue_text for term in alternatives)
               for alternatives in oracle['issue_groups']):
            report['issue_errors'].append(document)
    return report


def render_report(report):
    observation_note = (
        'These saved mock results measure pipeline and comparator behavior,\n'
        'not live model accuracy. No live call was made.'
        if report['observation'] == 'mock' else
        'Provider or mixed observations; inspect response_sources and producing settings below.\n'
        'This comparator does not establish general model accuracy.'
    )
    return f'''# Accuracy observations

Observation: **{report['observation']}**. {observation_note}

Exact matches: **{report['exact']}/{report['total']}** for the 11 non-purpose scalar fields.
All 21 documents count, including nulls, conflicts and failures. Missing keys fail even
when the expected value is null. Each scalar counts once, without partial credit.

Business purpose: **{report['purpose_exact']}/{report['purpose_total']}** exact reference sentences.
No free-text normalization is applied. Source-supported alternative wording needs human
inspection and can be factually correct despite failing this separate exact match.
Arrays are excluded from the scalar denominator. Quotes are checked as exact decoded-message
substrings; issues are checked for the expected diagnostic concepts, without requiring
one fixed sentence. These checks do not establish that all live facts would be supported.

Expectations in tests/expected/T05.json through T25.json were authored from planning/plan.md,
original messages and office policy before implementation. Each oracle retains the whole
source message, source/policy quotes and the chosen reference purpose. SYN-001 is a separately
authored paraphrase. The saved wrong-date negative control scores 230/231 and identifies
IT-001 end_date (expected 2026-11-06, actual 2026-11-09). Missing documents and missing null
keys are also tested. No expectations are generated from measured outputs.

Full comparison, factual errors, purpose differences, evidence checks and producing settings:

```json
{json.dumps(report, indent=2)}
```
'''
