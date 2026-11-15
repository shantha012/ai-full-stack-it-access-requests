"""Admit only completed, schema-valid responses with exact source quotations."""
import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'snapshot.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

class InvalidResponse(Exception):
    pass

def validate_reply(reply, message):
    if not isinstance(reply, dict) or reply.get('status') != 'completed':
        raise InvalidResponse('refused or incomplete response')
    if reply.get('refusal'):
        raise InvalidResponse('refusal')
    try:
        extraction = json.loads(reply['output_text'])
        VALIDATOR.validate(extraction)
    except (KeyError, TypeError, ValueError, __import__('jsonschema').ValidationError) as error:
        raise InvalidResponse('malformed extraction: ' + type(error).__name__) from None
    for field in ('request_date', 'start_date', 'end_date'):
        value = extraction[field]
        if value is not None and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value) is None:
            raise InvalidResponse('date does not use YYYY-MM-DD: ' + field)
    if any(quote not in message for quote in extraction['supporting_quotes']):
        raise InvalidResponse('supporting quote is not an exact substring of the decoded message')
    return extraction
