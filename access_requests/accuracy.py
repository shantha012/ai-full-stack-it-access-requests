"""Compare frozen source expectations with observations, retaining the full denominator."""
import json

FIELDS=('request_id','request_date','kind','requester','team','system','environment','permission',
        'business_purpose','start_date','end_date','manager')

def compare(records, expectations):
    actual={r['document_id']:r for r in records}
    result=dict(denominator=len(expectations)*len(FIELDS),resolved_matches=0,differences=[],unresolved=[],
                missing_or_failed_cells=0,final_score=None,observations=[])
    for document_id, reference in sorted(expectations.items()):
        record=actual.get(document_id)
        extraction=record.get('extraction') if record else None
        if extraction is None: result['missing_or_failed_cells']+=len(FIELDS)
        for field in FIELDS:
            cell=dict(document_id=document_id,field=field,expected=reference['scalars'][field],
                      actual=extraction.get(field) if extraction else '[missing/failed]')
            if field in reference.get('unresolved',[]):
                result['unresolved'].append(cell)
            elif extraction is not None and cell['expected']==cell['actual']:
                result['resolved_matches']+=1
            else:
                result['differences'].append(cell)
        result['observations'].append(dict(document_id=document_id,
            response_source=record.get('response_source') if record else 'missing',
            settings_fingerprint=record.get('settings_fingerprint') if record else None,
            producing_settings=record.get('producing_settings') if record else None,
            policy_version=record.get('policy_version') if record else None,
            routing={k:record.get(k) if record else None for k in ('status','owner','next_action')},
            supporting_quotes=extraction.get('supporting_quotes',[]) if extraction else [],
            issues=extraction.get('issues',[]) if extraction else []))
    if not result['unresolved']:
        result['final_score']=result['resolved_matches']/result['denominator'] if result['denominator'] else 0
    return result

def render_report(result, expectations):
    lines=['# Accuracy comparison','',
        'Expected facts were frozen from planning/plan.md L01–L20 and A01 before measurement.',
        'Exact string comparison; null equals only null. No case, whitespace, or date normalization.',
        'All 21 documents and 12 scalar fields remain in the denominator: 252 cells.',
        'A missing/failed record contributes 12 missing/failed cells. Ambiguous cells remain unresolved.',
        'Purpose spans are reference wording pending Q-21/Q-54; IT-006 permission awaits Q-29.',
        'No finalized full-corpus score is claimed while any cell is unresolved.',
        'Mock agreement checks reproducibility and comparison plumbing; no live accuracy was measured.','',
        f"Resolved matches: {result['resolved_matches']}; factual differences: {len(result['differences'])}; "
        f"unresolved: {len(result['unresolved'])}; missing/failed cells: {result['missing_or_failed_cells']}.",'',
        '## Frozen expectations','', '| Document | Field | Expected | Source ledger |','|---|---|---|---|']
    for doc,ref in sorted(expectations.items()):
        for field in FIELDS:
            value=json.dumps(ref['scalars'][field],ensure_ascii=False).replace('|','\\|')
            suffix=' (unresolved reference)' if field in ref.get('unresolved',[]) else ''
            lines.append(f"| {doc} | {field} | {value}{suffix} | {ref['source']} / {ref['ledger']} |")
    lines+=['','## Every factual difference','',json.dumps(result['differences'],indent=2),
            '','## Unresolved cells','',json.dumps(result['unresolved'],indent=2),
            '','## Observations: origin, configuration, routing and source evidence','',
            'Routing, quotes and issues are reported separately from the scalar denominator.',
            'Inspect exact quotes against decoded source and policy; the report does not certify live extraction quality.',
            '```json',json.dumps(result['observations'],indent=2),'```','']
    return '\n'.join(lines)
