"""Executable plan cases; fixtures are authored from source before implementation."""

import hashlib
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
EXPECTED = ROOT / "tests" / "expected"


class TestPlan(unittest.TestCase):
    def setUp(self):
        """Enforce offline execution and reject credential reads in every case."""
        original_getitem = type(os.environ).__getitem__

        def guarded_getitem(environ, key):
            if key == "API_KEY":
                raise AssertionError("a test attempted to read API_KEY")
            return original_getitem(environ, key)

        def forbidden(*args, **kwargs):
            raise AssertionError("a test attempted network access")

        for patcher in (
            mock.patch.object(type(os.environ), "__getitem__", guarded_getitem),
            mock.patch.object(socket, "socket", forbidden),
            mock.patch.object(socket, "create_connection", forbidden),
            mock.patch.object(urllib.request, "urlopen", forbidden),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def test_T02(self):
        """Load original bytes/filename/message, independent of export metadata."""
        from access_requests.providers import MockProvider
        from access_requests.sources import load_source
        from access_requests.validation import validate_response

        cases = json.loads((EXPECTED / "T02.json").read_text(encoding="utf-8"))["cases"]
        expected_facts = json.loads((EXPECTED / "IT-001.json").read_text(encoding="utf-8"))
        provider = MockProvider(MOCKS / "IT-001-success.json", clock=lambda: 0.0)
        hashes = []
        for case in cases:
            with self.subTest(source=case["path"]):
                path = ROOT / case["path"]
                raw = path.read_bytes()
                source = load_source(path)
                self.assertEqual(source.document_id, case["document_id"])
                self.assertEqual(source.raw_bytes, raw)
                self.assertEqual(source.source_sha256, hashlib.sha256(raw).hexdigest())
                self.assertEqual(source.message, case["message"])
                self.assertEqual(len(source.message.split()), case["words"])
                reply = provider.extract(source.message)
                self.assertEqual(validate_response(reply, source.message), expected_facts)
                hashes.append(source.source_sha256)
        # Misleading subject/timestamp cannot enter the provider's source text.
        self.assertEqual(provider.calls[0]["message"], provider.calls[1]["message"])
        self.assertNotEqual(hashes[0], hashes[1])
        compact_path = ROOT / "tests" / "inputs" / "IT-001-compact.json"
        compact = load_source(compact_path)
        self.assertEqual(compact.message, cases[0]["message"])
        self.assertEqual(compact.source_sha256, hashlib.sha256(compact_path.read_bytes()).hexdigest())
        self.assertNotEqual(compact.source_sha256, hashes[0])

    def test_T03(self):
        """Required fields, types, enums, JSON and completion precede routing."""
        from access_requests.sources import load_source
        from access_requests.validation import ExtractionError, validate_response

        source = load_source(ROOT / "materials" / "requests" / "IT-001.json")
        replies = json.loads((MOCKS / "schema-variants.json").read_text(encoding="utf-8"))
        expected = json.loads((EXPECTED / "T03.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual([case["id"] for case in replies], [case["id"] for case in expected])
        for response, oracle in zip(replies, expected):
            with self.subTest(variant=oracle["id"]):
                if oracle["valid"]:
                    self.assertEqual(
                        validate_response(response["reply"], source.message),
                        oracle["extraction"],
                    )
                else:
                    with self.assertRaises(ExtractionError) as caught:
                        validate_response(response["reply"], source.message)
                    self.assertTrue(str(caught.exception).strip(), "validation error needs a diagnostic")

    def test_T04(self):
        """Quotes must be substrings of decoded source, including real newlines."""
        from access_requests.providers import MockProvider
        from access_requests.sources import load_source
        from access_requests.validation import ExtractionError, validate_response

        original = load_source(ROOT / "materials" / "requests" / "IT-001.json")
        newline = load_source(ROOT / "tests" / "inputs" / "newline.json")
        for source, reply_file, expected_file in (
            (original, "IT-001-success.json", "IT-001.json"),
            (newline, "quotes-valid.json", "newline.json"),
        ):
            with self.subTest(valid=reply_file):
                reply = MockProvider(MOCKS / reply_file, clock=lambda: 0.0).extract(source.message)
                result = validate_response(reply, source.message)
                self.assertEqual(result, json.loads((EXPECTED / expected_file).read_text(encoding="utf-8")))
                for quote in result["supporting_quotes"]:
                    self.assertIn(quote, source.message)
        for source, reply_file in (
            (original, "quotes-invalid.json"),
            (newline, "quotes-escaped-newline.json"),
        ):
            with self.subTest(invalid=reply_file):
                reply = MockProvider(MOCKS / reply_file, clock=lambda: 0.0).extract(source.message)
                with self.assertRaises(ExtractionError) as caught:
                    validate_response(reply, source.message)
                self.assertTrue(str(caught.exception).strip(), "invalid quote needs a diagnostic")

    def _assert_semantic_record(self, oracle):
        """Check independent plan facts, evidence and human review routing."""
        from access_requests.intake import process_response
        from access_requests.providers import MockProvider
        from access_requests.sources import load_source

        source = load_source(ROOT / oracle["input_path"])
        self.assertEqual(source.message, oracle["message"])
        reply = MockProvider(MOCKS / oracle["response_path"], clock=lambda: 0.0).extract(source.message)
        record = process_response(source, reply)
        self.assertEqual(record["document_id"], oracle["document_id"])
        self.assertEqual(record["source_sha256"], hashlib.sha256(source.raw_bytes).hexdigest())
        self.assertEqual(record["response_source"], "mock")
        self.assertIsNone(record["error"])
        for field, value in oracle["facts"].items():
            with self.subTest(field=field):
                self.assertIn(field, record["extraction"])
                self.assertEqual(record["extraction"][field], value)
        for field, value in oracle["route"].items():
            self.assertEqual(record[field], value)
        self.assertIn(record["status"], ("review", "needs-information"))
        self.assertNotIn(record["next_action"], ("grant", "approve", "approved"))

        quotes = record["extraction"]["supporting_quotes"]
        self.assertTrue(quotes, "retain evidence for these source-grounded cases")
        for quote in quotes:
            self.assertIn(quote, source.message)
        for fragment in oracle["evidence_fragments"]:
            self.assertTrue(any(fragment in quote for quote in quotes),
                            f"missing evidence of {fragment!r}")

        # Match diagnostic meaning without requiring a single sentence or code.
        issue_text = " ".join(record["extraction"]["issues"]).lower().replace("_", " ")
        for alternatives in oracle["issue_groups"]:
            self.assertTrue(any(term.lower() in issue_text for term in alternatives),
                            f"issues do not explain {alternatives!r}: {issue_text}")
        if not oracle["has_fact_issues"]:
            self.assertNotRegex(issue_text, r"\b(missing|absent|conflicting|unresolved)\b")

    def _assert_plan_semantics(self, case_id):
        """One named case owns its original message and listed policy subcases.

        Canned replies establish local pipeline behavior, not model fidelity.
        Inspect the prompt manually alongside these checks when implementing.
        """
        from access_requests.prompts import build_messages

        oracle = json.loads((EXPECTED / f"{case_id}.json").read_text(encoding="utf-8"))
        messages = build_messages(oracle["message"])
        # Keep exported messages as data in their own user role. In particular,
        # the T10 attack must never become part of the system instructions.
        self.assertEqual([item["role"] for item in messages], ["system", "user"])
        self.assertEqual(messages[1]["content"], oracle["message"])
        self.assertNotIn(oracle["message"], messages[0]["content"])
        policy = (ROOT / "materials" / "office-policy.md").read_text(encoding="utf-8")
        self.assertIn(policy, messages[0]["content"])
        schema = json.loads((ROOT / "snapshot.schema.json").read_text(encoding="utf-8"))
        for field in schema["required"]:
            self.assertIn(field, messages[0]["content"])
        self.assertIn("additionalProperties", messages[0]["content"])
        self._assert_semantic_record(oracle)
        variants = json.loads((EXPECTED / "step3-variants.json").read_text(encoding="utf-8"))
        for variant in variants:
            if variant["plan_case"] == case_id:
                with self.subTest(variant=variant["name"]):
                    self._assert_semantic_record(variant)

    def test_T05(self):
        """Complete IT-001: staging/read awaits system owner review."""
        self._assert_plan_semantics("T05")

    def test_T06(self):
        """IT-002 and complete new/change risk predicates await security review."""
        self._assert_plan_semantics("T06")

    def test_T07(self):
        """Missing facts remain null; every new/change required fact clarifies."""
        self._assert_plan_semantics("T07")

    def test_T08(self):
        """Uncorrected environment conflict stays null with both alternatives."""
        self._assert_plan_semantics("T08")

    def test_T09(self):
        """Withdrawal rule requires id/date and tolerates other absent facts."""
        self._assert_plan_semantics("T09")

    def test_T10(self):
        """Embedded override stays evidence and precedes every ordinary route."""
        self._assert_plan_semantics("T10")

    def test_T11(self):
        """IT-007 requests write, replacing existing read access."""
        self._assert_plan_semantics("T11")

    def test_T12(self):
        """Explicit environment correction selects staging over production."""
        self._assert_plan_semantics("T12")

    def test_T13(self):
        """IT-009's absent manager remains null and requires clarification."""
        self._assert_plan_semantics("T13")

    def test_T14(self):
        """Missing end date clarifies before production risk review."""
        self._assert_plan_semantics("T14")

    def test_T15(self):
        """Relative dates stay unresolved rather than being calculated."""
        self._assert_plan_semantics("T15")

    def test_T16(self):
        """Complete staging/admin request awaits security review."""
        self._assert_plan_semantics("T16")

    def test_T17(self):
        """Complete production/read request awaits security review."""
        self._assert_plan_semantics("T17")

    def test_T18(self):
        """Reversed dates stay explicit and clarify, including production/admin."""
        self._assert_plan_semantics("T18")

    def test_T19(self):
        """Explicit date correction replaces the earlier access window."""
        self._assert_plan_semantics("T19")

    def test_T20(self):
        """Retain stated IT-061 while document IT-016.json clarifies mismatch."""
        self._assert_plan_semantics("T20")

    def test_T21(self):
        """Other/null kind requires clarification, including otherwise risk facts."""
        self._assert_plan_semantics("T21")

    def test_T22(self):
        """Complete IT-018 staging/read request awaits system owner review."""
        self._assert_plan_semantics("T22")

    def test_T23(self):
        """IT-019 requests read instead of prior write; production remains risk."""
        self._assert_plan_semantics("T23")

    def test_T24(self):
        """Uncorrected manager conflict stays null with both named alternatives."""
        self._assert_plan_semantics("T24")

    def test_T25(self):
        """Independently authored paraphrase retains the plan's explicit facts."""
        self._assert_plan_semantics("T25")


if __name__ == "__main__":
    unittest.main()
