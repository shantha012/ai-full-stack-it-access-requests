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
