"""Provider interface and deterministic saved-response implementation."""
import json
from pathlib import Path
from threading import Lock
from typing import Protocol

class ProviderError(Exception):
    pass

class Provider(Protocol):
    def extract(self, message: str) -> dict: ...

class MockProvider:
    response_source = 'mock'

    def __init__(self, directory, script):
        self.directory = Path(directory)
        self.script = iter(script)
        self.calls = 0
        self.barrier = None
        self._lock = Lock()

    def extract(self, message):
        with self._lock:
            self.calls += 1
            name = next(self.script)
        if self.barrier:
            entered, release = self.barrier
            entered.set()
            if not release.wait(30):
                raise ProviderError('mock barrier timeout')
        reply = json.loads((self.directory / (name + '.json')).read_text())
        if 'error' in reply:
            raise ProviderError(reply['error'])
        return reply
