"""A response must complete before JSON/schema validation can admit it."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'snapshot.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)

class InvalidResponse(Exception):
    pass

def validate_reply(reply):
    if not isinstance(reply, dict) or reply.get('status') != 'completed':
        raise InvalidResponse('refused or incomplete response')
    if reply.get('refusal'):
        raise InvalidResponse('refusal')
    try:
        extraction = json.loads(reply['output_text'])
        VALIDATOR.validate(extraction)
    except (KeyError, TypeError, ValueError, __import__('jsonschema').ValidationError) as error:
        raise InvalidResponse('malformed extraction: ' + type(error).__name__) from None
    return extraction
