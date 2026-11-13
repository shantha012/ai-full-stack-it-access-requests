"""Load message exports while preserving their original byte identity."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Union


class SourceError(ValueError):
    """An input export cannot supply a decoded source message."""


@dataclass(frozen=True)
class Source:
    document_id: str
    source_sha256: str
    raw_bytes: bytes
    message: str


def load_source(path: Union[str, Path]) -> Source:
    """Use filename/raw bytes for identity and only message for business facts."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SourceError(f"Cannot read source file {path.name}") from exc
    try:
        export = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"Source file {path.name} must contain UTF-8 JSON") from exc
    if not isinstance(export, dict) or not isinstance(export.get("message"), str):
        raise SourceError(f"Source file {path.name} must contain a message string")
    return Source(
        document_id=path.name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=raw,
        message=export["message"],
    )
