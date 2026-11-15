"""Read source facts exclusively from the decoded message; identify original bytes."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

@dataclass(frozen=True)
class Document:
    document_id: str
    source_sha256: str
    message: str
    raw: bytes

def read_document(path):
    path = Path(path)
    raw = path.read_bytes()
    export = json.loads(raw.decode('utf-8'))
    if not isinstance(export.get('message'), str):
        raise ValueError('export message must be a string')
    return Document(path.name, hashlib.sha256(raw).hexdigest(), export['message'], raw)
