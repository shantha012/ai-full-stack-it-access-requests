"""Publish immutable paired artifacts from one committed database snapshot."""
import json
import os
from pathlib import Path
import uuid


def _write(path, content):
    with path.open('w', encoding='utf-8') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def publish_generation(store, directory, *, hook=lambda stage: None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    records = store.snapshot()
    generation = 'generation-' + uuid.uuid4().hex
    target = directory / generation
    target.mkdir()
    _write(target / 'extractions.jsonl', ''.join(json.dumps(row, sort_keys=True) + '\n' for row in records))
    queue = [{key: row[key] for key in ('document_id', 'source_sha256', 'attempt_id', 'status', 'owner',
                                       'next_action', 'error', 'response_source')} for row in records]
    _write(target / 'queue.json', json.dumps(queue, indent=2) + '\n')
    # fsync files and their directory before making the generation discoverable.
    descriptor = os.open(target, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reference = directory / ('.CURRENT-' + uuid.uuid4().hex)
    _write(reference, generation + '\n')
    hook('before_switch')
    os.replace(reference, directory / 'CURRENT')
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    hook('after_switch')
    return generation


def read_generation(directory):
    directory = Path(directory)
    generation = (directory / 'CURRENT').read_text().strip()
    if Path(generation).name != generation or not generation.startswith('generation-'):
        raise ValueError('Invalid generation reference')
    target = directory / generation
    return dict(extractions=[json.loads(line) for line in (target / 'extractions.jsonl').read_text().splitlines()],
                queue=json.loads((target / 'queue.json').read_text()))
