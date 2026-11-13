"""Executable plan cases; fixtures are authored from source before implementation."""

import json
import os
from pathlib import Path
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import unittest
from unittest import mock
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / "tests" / "mock_responses"


class TestPlan(unittest.TestCase):
    def test_T01(self):
        """Saved envelopes, observable calls, clock/barrier injection, no key/network."""
        message = json.loads(
            (ROOT / "materials" / "requests" / "IT-001.json").read_bytes()
        )["message"]
        original_getitem = type(os.environ).__getitem__

        def guarded_getitem(environ, key):
            if key == "API_KEY":
                raise AssertionError("mock provider read API_KEY")
            return original_getitem(environ, key)

        network_forbidden = mock.Mock(
            side_effect=AssertionError("mock provider opened the network")
        )
        with (
            mock.patch.object(type(os.environ), "__getitem__", guarded_getitem),
            mock.patch.object(socket, "socket", network_forbidden),
            mock.patch.object(urllib.request, "urlopen", network_forbidden),
        ):
            from access_requests.providers import MockProvider

            clock = mock.Mock(return_value=123.5)
            for name in (
                "IT-001-success.json", "provider-error.json",
                "refusal.json", "interrupted.json",
            ):
                with self.subTest(envelope=name):
                    path = MOCKS / name
                    # Read the saved input independently, never from adapter output.
                    expected = json.loads(path.read_text(encoding="utf-8"))
                    provider = MockProvider(path, clock=clock)
                    self.assertEqual(provider.calls, [])
                    reply = provider.extract(message)
                    self.assertEqual(reply, expected)
                    self.assertEqual(reply["response_source"], "mock")
                    self.assertEqual(provider.calls, [
                        {"message": message, "started_at": 123.5}
                    ])
                    # Each invocation returns a fresh saved envelope.
                    reply["response_source"] = "modified by caller"
                    self.assertEqual(provider.extract(message), expected)
                    self.assertEqual(len(provider.calls), 2)
            self.assertEqual(clock.call_count, 8)

            entered, release = Event(), Event()

            def barrier():
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("test did not release mock provider")

            provider = MockProvider(
                MOCKS / "IT-001-success.json", clock=lambda: 456.0,
                barrier=barrier,
            )
            with ThreadPoolExecutor(max_workers=1) as worker:
                pending = worker.submit(provider.extract, message)
                try:
                    self.assertTrue(entered.wait(timeout=2), "barrier was not called")
                    self.assertFalse(pending.done())
                    self.assertEqual(provider.calls, [
                        {"message": message, "started_at": 456.0}
                    ])
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=2), json.loads(
                    (MOCKS / "IT-001-success.json").read_text(encoding="utf-8")
                ))
        network_forbidden.assert_not_called()


if __name__ == "__main__":
    unittest.main()
