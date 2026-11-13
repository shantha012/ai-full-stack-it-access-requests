"""Provider adapters for extraction replies."""

import json
from pathlib import Path
from threading import Lock
from time import time
from typing import Callable, Optional, Union


class MockProvider:
    """Replay a saved envelope without credentials or network access.

    Record each invocation before waiting on the optional barrier so tests can
    inspect pending work. The injected clock makes call timestamps reproducible.
    Envelopes are decoded afresh so callers cannot mutate later replies.
    """

    def __init__(
        self,
        fixture_path: Union[str, Path],
        *,
        clock: Callable[[], float] = time,
        barrier: Optional[Callable[[], None]] = None,
    ) -> None:
        self._fixture_path = Path(fixture_path)
        self._clock = clock
        self._barrier = barrier
        self._calls: list[dict] = []
        self._lock = Lock()

    @property
    def calls(self) -> list[dict]:
        """Return an independent snapshot of recorded invocations."""
        with self._lock:
            return [dict(call) for call in self._calls]

    def extract(self, message: str) -> dict:
        """Return the fixture unchanged, including error or incomplete replies."""
        with self._lock:
            self._calls.append({"message": message, "started_at": self._clock()})
        if self._barrier is not None:
            self._barrier()
        return json.loads(self._fixture_path.read_text(encoding="utf-8"))


class HTTPProvider:
    """Chat Completions adapter; credentials are loaded only on invocation.

    Transport accepts (urllib Request, timeout) and returns a decoded envelope.
    Diagnostics never echo provider content, URLs or exception messages.
    """
    def __init__(self, *, endpoint='https://api.openai.com/v1/chat/completions',
                 model='gpt-4o-mini', timeout=30, temperature=0,
                 transport=None, credential=None, environment=None):
        self.endpoint, self.model = endpoint, model
        self.timeout, self.temperature = timeout, temperature
        self._transport = transport or self._send
        self._credential, self._environment = credential, environment

    @staticmethod
    def _send(request, timeout):
        import urllib.request
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    def evidence(self):
        from .prompts import build_messages
        from .validation import SCHEMA_PATH
        return dict(provider='openai-compatible', endpoint=self.endpoint, model=self.model,
                    timeout=self.timeout, temperature=self.temperature,
                    messages=build_messages('<message supplied separately>'),
                    schema=json.loads(SCHEMA_PATH.read_text()))

    def extract(self, message):
        import os
        import urllib.request
        import urllib.error
        from .prompts import build_messages
        from .validation import SCHEMA_PATH
        source = 'openai-compatible/' + self.model
        def failure(detail, **extra):
            return dict(response_source=source, error=detail, **extra)
        credential = self._credential
        if credential is None:
            environment = os.environ if self._environment is None else self._environment
            credential = environment.get('API_KEY')
        if not credential:
            return failure('Missing live credential: set API_KEY before live invocation')
        body = dict(model=self.model, temperature=self.temperature,
                    messages=build_messages(message), response_format=dict(
                        type='json_schema', json_schema=dict(name='access_request', strict=True,
                            schema=json.loads(SCHEMA_PATH.read_text()))))
        request = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(),
                    headers={'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json'})
        try:
            response = self._transport(request, self.timeout)
            choice = response['choices'][0]
            return dict(response_source=source, error=None,
                        finish_reason=choice['finish_reason'],
                        refusal=choice['message'].get('refusal'),
                        output_text=choice['message'].get('content'))
        except urllib.error.HTTPError as exc:
            return failure(f'Provider HTTP {exc.code}; retry extraction', retryable=exc.code in (429, 503))
        except (TimeoutError, OSError):
            return failure('Provider transport failure; check connectivity and retry extraction', retryable=True)
        except (KeyError, IndexError, TypeError, ValueError):
            return failure('Provider response envelope malformed; retry extraction')
