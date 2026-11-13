"""Validate provider completion, extraction structure and exact source evidence.

Routing is a separate concern; successful validation does not approve access.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "snapshot.schema.json"


class ExtractionError(ValueError):
    """A provider reply is unusable for successful intake."""


def _reject_constant(value: str) -> None:
    raise ExtractionError("Provider output contains a non-JSON numeric constant")


def validate_response(reply: dict, message: str) -> dict:
    """Return schema-valid source-quoted extraction or raise a diagnostic error.

    Check completion before parsing so valid-looking partial content cannot be
    published. Error diagnostics omit provider content and extracted values.
    """
    if not isinstance(reply, dict):
        raise ExtractionError("Provider reply must be an envelope object")
    if reply.get("error") is not None:
        raise ExtractionError("Provider reported an extraction error; retry extraction")
    if reply.get("refusal") is not None:
        raise ExtractionError("Provider refused extraction; inspect the source before retrying")
    if reply.get("finish_reason") != "stop":
        raise ExtractionError("Provider response is incomplete; retry extraction")
    text = reply.get("output_text")
    if not isinstance(text, str):
        raise ExtractionError("Provider output_text must be a JSON string")
    try:
        extraction = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"Provider output is malformed JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    error = next(validator.iter_errors(extraction), None)
    if error is not None:
        raise ExtractionError(f"Extraction violates schema constraint: {error.validator}")

    for index, quote in enumerate(extraction["supporting_quotes"]):
        if quote not in message:
            raise ExtractionError(
                f"Supporting quote {index + 1} is not an exact decoded-message substring"
            )
    return extraction
