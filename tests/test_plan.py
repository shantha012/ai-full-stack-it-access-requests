"""Executable plan cases; fixtures are authored from source before implementation."""

import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import subprocess
import sys
import time
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


    def _http_provider(self, fixture="http-success.json", **settings):
        from access_requests.providers import HTTPProvider
        reply = json.loads((MOCKS / fixture).read_text())
        transport = mock.Mock(return_value=reply)
        return HTTPProvider(transport=transport, credential="sentinel-credential", **settings), transport

    def test_T26(self):
        from access_requests.sources import load_source
        from access_requests.intake import process_response
        from access_requests.providers import HTTPProvider
        provider, transport = self._http_provider(endpoint="https://provider.invalid/chat", model="configured-model", temperature=0)
        source = load_source(ROOT / "materials/requests/IT-001.json")
        record = process_response(source, provider.extract(source.message))
        expected = json.loads((EXPECTED / "T05.json").read_text())
        for field, value in expected["facts"].items():
            self.assertEqual(record["extraction"][field], value)
        request, timeout = transport.call_args.args
        self.assertEqual(request.full_url, "https://provider.invalid/chat")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "configured-model")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["messages"][1]["content"], source.message)
        self.assertEqual(body["response_format"]["json_schema"]["schema"], json.loads((ROOT / "snapshot.schema.json").read_text()))
        self.assertNotIn("sentinel-credential", json.dumps(provider.evidence()))
        self.assertNotIn("sentinel-credential", repr(provider))
        missing = HTTPProvider(transport=transport, environment={})
        failure = missing.extract(source.message)
        self.assertIn("credential", failure["error"].lower())
        self.assertEqual(transport.call_count, 1)

    def _assert_failure(self, reply, diagnostic):
        from access_requests.sources import load_source
        from access_requests.intake import process_response
        record = process_response(load_source(ROOT / "materials/requests/IT-001.json"), reply)
        self.assertIsNone(record["extraction"])
        self.assertEqual((record["status"], record["owner"], record["next_action"]),
                         ("error", "IT Service Desk", "retry-extraction"))
        self.assertIn(diagnostic, record["error"].lower())
        self.assertIn("retry", record["retry_command"])
        self.assertNotIn("sentinel-credential", json.dumps(record))

    def test_T27(self):
        from access_requests.providers import HTTPProvider
        import urllib.error
        for failure in (TimeoutError("sentinel-credential"),
                        urllib.error.HTTPError("https://x", 429, "sentinel-credential", {}, None),
                        urllib.error.HTTPError("https://x", 503, "sentinel-credential", {}, None)):
            with self.subTest(error=type(failure).__name__):
                provider = HTTPProvider(transport=mock.Mock(side_effect=failure), credential="sentinel-credential")
                self._assert_failure(provider.extract("source"), "provider")
        self._assert_failure(json.loads((MOCKS / "provider-error.json").read_text()), "provider")

    def test_T28(self):
        provider, _ = self._http_provider("http-refusal.json")
        self._assert_failure(provider.extract("source"), "refus")
        self._assert_failure(json.loads((MOCKS / "refusal.json").read_text()), "refus")

    def test_T29(self):
        for fixture in ("http-length.json", "http-cutoff.json"):
            provider, _ = self._http_provider(fixture)
            self._assert_failure(provider.extract("source"), "incomplete")


    def _store(self):
        from access_requests.storage import Store
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Store(Path(temporary.name) / "records.sqlite")

    def _source(self, name="IT-001.json"):
        from access_requests.sources import load_source
        return load_source(ROOT / "materials/requests" / name)

    def _mock(self, name="IT-001-success.json"):
        from access_requests.providers import MockProvider
        return MockProvider(MOCKS / name, clock=lambda: 0)

    def test_T30(self):
        store, provider = self._store(), self._mock()
        first = store.process(self._source(), provider)
        second = store.process(self._source(), provider)
        self.assertEqual(first, second)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(store.queue()), 1)
        self.assertEqual(len(store.history("IT-001.json")), 1)
        self.assertEqual(second["extraction"]["end_date"], "2026-11-06")

    def test_T31(self):
        from access_requests.sources import load_source
        store = self._store()
        original = self._source()
        first = store.process(original, self._mock())
        path = store.path.parent / "IT-001.json"
        path.write_bytes(original.raw_bytes.replace(b"2026-11-06", b"2026-11-09"))
        source = load_source(path)
        latest = store.process(source, self._mock("IT-001-updated-success.json"))
        self.assertEqual(latest["extraction"]["end_date"], "2026-11-09")
        self.assertEqual(latest["source_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotEqual(first["source_sha256"], latest["source_sha256"])
        self.assertEqual([r["extraction"]["end_date"] for r in store.history("IT-001.json")], ["2026-11-06", "2026-11-09"])
        self.assertEqual(store.source_bytes("IT-001.json", first["source_sha256"]), original.raw_bytes)

    def test_T32(self):
        store = self._store()
        first = store.process(self._source(), self._mock())
        failure = store.process(self._source(), self._mock("provider-error.json"), force=True)
        self.assertIsNone(failure["extraction"])
        self.assertEqual(failure["status"], "error")
        self.assertEqual(store.queue(), [failure])
        self.assertEqual(store.history("IT-001.json")[0], first)
        self.assertEqual(len(store.history("IT-001.json")), 2)

    def test_T33(self):
        from access_requests.sources import load_source
        store = self._store()
        store.process(self._source(), self._mock())
        path = store.path.parent / "IT-099.json"
        path.write_bytes(self._source().raw_bytes)
        other = store.process(load_source(path), self._mock())
        self.assertEqual(other["extraction"]["request_id"], "IT-001")
        self.assertEqual(other["status"], "needs-information")
        self.assertIn("mismatch", " ".join(other["extraction"]["issues"]).lower())
        store.process(self._source("IT-002.json"), self._mock("IT-002-success.json"))
        self.assertEqual(len(store.queue()), 3)

    def test_T34(self):
        store, provider = self._store(), self._mock()
        source = self._source()
        first = store.process(source, provider, config={"model": "mock-v1"})
        changed = store.process(source, provider, config={"model": "mock-v2"})
        self.assertEqual(len(provider.calls), 2)
        self.assertNotEqual(first["provenance"]["extraction_hash"], changed["provenance"]["extraction_hash"])
        policy = {"version": "TEST-ONLY", "system_owner": "Test Review Owner"}
        rerouted = store.process(source, provider, config={"model": "mock-v2"}, policy=policy)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(rerouted["owner"], "Test Review Owner")
        self.assertNotEqual(changed["provenance"]["policy_hash"], rerouted["provenance"]["policy_hash"])
        self.assertEqual(rerouted["provenance"]["producing_config"], {"model": "mock-v2"})
        self.assertEqual(len(store.history(source.document_id)), 3)


    def _cli(self, *args, control=None):
        environment = dict(os.environ)
        if control:
            environment["TEST_CONTROL"] = str(control)
        return subprocess.Popen([sys.executable, str(ROOT / "tests/cli_runner.py"), *map(str, args)],
                                cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _wait_for(self, predicate, process=None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            if process and process.poll() is not None:
                self.fail("worker exited early: " + str(process.communicate()))
            time.sleep(.02)
        self.fail("timed out waiting for worker state")

    def _finish(self, process):
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        return json.loads(stdout)

    def test_T35(self):
        store = self._store()
        control = store.path.parent
        (control / "hold-IT-002").touch()
        process = self._cli("intake", "--db", store.path, "--mocks", MOCKS, "--workers", 2,
                            ROOT / "materials/requests/IT-001.json", ROOT / "materials/requests/IT-002.json", control=control)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        try:
            self._wait_for(lambda: (control / "entered-IT-002").exists(), process)
            self._wait_for(lambda: any(r.get("extraction") for r in store.queue()), process)
            records = self._finish(self._cli("queue", "--db", store.path))
            self.assertEqual(records[0]["extraction"]["requester"], "Maya Chen")
            self.assertEqual(records[1]["state"], "running")
            self.assertIsNone(process.poll())
        finally:
            (control / "release-IT-002").touch()
        self._finish(process)
        self.assertEqual(store.queue()[1]["owner"], "Security Review")

    def test_T36(self):
        store = self._store()
        from access_requests.workers import intake
        providers = {"IT-001.json": self._mock("provider-error.json"), "IT-002.json": self._mock("IT-002-success.json")}
        intake(store, [self._source(), self._source("IT-002.json")], lambda source: providers[source.document_id], workers=2)
        one, two = store.queue()
        self.assertEqual(one["status"], "error")
        self.assertIsNone(one["extraction"])
        self.assertEqual(two["owner"], "Security Review")
        self.assertEqual(two["extraction"]["requester"], "Owen Reed")

    def test_T37(self):
        store = self._store()
        control = store.path.parent
        (control / "hold-IT-001").touch()
        args = ("intake", "--db", store.path, "--mocks", MOCKS, ROOT / "materials/requests/IT-001.json")
        first = self._cli(*args, control=control)
        self.addCleanup(lambda: first.kill() if first.poll() is None else None)
        try:
            self._wait_for(lambda: (control / "entered-IT-001").exists(), first)
            self._finish(self._cli(*args, control=control))
        finally:
            (control / "release-IT-001").touch()
        self._finish(first)
        records = self._finish(self._cli("queue", "--db", store.path))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["extraction"]["end_date"], "2026-11-06")
        self.assertEqual(len(store.history("IT-001.json")), 1)
        self.assertEqual((control / "calls").read_text().splitlines(), ["IT-001"])


    def test_T38(self):
        from access_requests.storage import Store
        from access_requests.intake import process_response
        store = self._store()
        control = store.path.parent
        (control / "hold-IT-002").touch()
        worker = self._cli("intake", "--db", store.path, "--mocks", MOCKS,
                           ROOT / "materials/requests/IT-001.json", ROOT / "materials/requests/IT-002.json", control=control)
        self.addCleanup(lambda: worker.kill() if worker.poll() is None else None)
        self._wait_for(lambda: (control / "entered-IT-002").exists(), worker)
        self._wait_for(lambda: any(r.get("extraction") for r in store.queue()), worker)
        worker.kill()
        worker.communicate(timeout=5)
        before = store.queue()[0]
        with store.connection() as db:
            stale = db.execute("SELECT id,token,lease FROM attempts WHERE state='running'").fetchone()
        future = Store(store.path, clock=lambda: stale["lease"] + 1)
        self.assertEqual(future.recover(), 1)
        source = store.source_for(stale["id"])
        record = process_response(source, self._mock("IT-002-success.json").extract(source.message))
        self.assertFalse(future.publish(stale["id"], stale["token"], record))
        result = self._finish(self._cli("resume", "--db", store.path))
        self.assertEqual(store.queue()[0], before)
        self.assertEqual(store.queue()[1]["extraction"]["requester"], "Owen Reed")
        self.assertEqual((control / "calls").read_text().splitlines().count("IT-001"), 1)
        self.assertEqual(len(result), 2)

    def test_T39(self):
        from access_requests.exports import publish_generation, read_generation
        from access_requests.sources import load_source
        store = self._store()
        old = store.process(self._source(), self._mock())
        destination = store.path.parent / "exports"
        publish_generation(store, destination)
        old_generation = read_generation(destination)
        path = store.path.parent / "IT-001.json"
        path.write_bytes(self._source().raw_bytes.replace(b"2026-11-06", b"2026-11-09"))
        updated = load_source(path)
        original_publish = store._publish
        def crash_db(*args):
            original_publish(*args)
            raise RuntimeError("crash before commit")
        with mock.patch.object(store, "_publish", side_effect=crash_db):
            with self.assertRaises(RuntimeError):
                store.process(updated, self._mock("IT-001-updated-success.json"))
        self.assertEqual(store.queue()[0]["state"], "running")
        self.assertEqual(read_generation(destination), old_generation)
        with store.connection() as db:
            lease = db.execute("SELECT MAX(lease) FROM attempts").fetchone()[0]
        from access_requests.storage import Store
        recovery = Store(store.path, clock=lambda: lease + 1)
        recovery.recover()
        from access_requests.workers import run_attempt
        attempt = store.queue()[0]["attempt_id"]
        run_attempt(store, attempt, lambda source: self._mock("IT-001-updated-success.json"))
        def crash(stage):
            if stage == "before_switch":
                raise RuntimeError("crash at export switch")
        with self.assertRaises(RuntimeError):
            publish_generation(store, destination, hook=crash)
        self.assertEqual(read_generation(destination), old_generation)
        publish_generation(store, destination)
        generation = read_generation(destination)
        extraction, queue = generation["extractions"][0], generation["queue"][0]
        self.assertEqual(extraction["extraction"]["end_date"], "2026-11-09")
        for key in ("document_id", "attempt_id", "source_sha256"):
            self.assertEqual(queue[key], extraction[key])
        self.assertEqual(store.history("IT-001.json")[0], old)

    def test_T40(self):
        from access_requests.workers import run_attempt
        import shlex
        store = self._store()
        failure = store.process(self._source(), self._mock("provider-error.json"))
        command = shlex.split(failure["retry_command"])
        self.assertEqual(command[:3], ["python3", "-m", "access_requests"])
        recovered = self._finish(self._cli(*command[3:]))
        self.assertEqual(recovered["extraction"]["end_date"], "2026-11-06")
        self.assertEqual(len(store.history("IT-001.json")), 2)
        clock = [100.0]
        store.clock = lambda: clock[0]
        provider = self._mock("IT-001-success.json")
        saved_error = json.loads((MOCKS / "provider-error.json").read_text())
        saved_error["retryable"] = True
        provider.extract = mock.Mock(side_effect=[saved_error, saved_error, json.loads((MOCKS / "IT-001-success.json").read_text())])
        attempt = store.enqueue(self._source(), force=True)
        sleeps = []
        def advance(delay):
            self.assertEqual(store.queue()[0]["state"], "running")
            sleeps.append(delay)
            clock[0] += delay
        run_attempt(store, attempt, lambda source: provider, max_retries=2, sleep=advance)
        self.assertEqual(sleeps, [1, 2])
        self.assertEqual(provider.extract.call_count, 3)
        self.assertEqual(store.queue()[0]["status"], "review")
        provider.extract = mock.Mock(return_value=saved_error)
        attempt = store.enqueue(self._source(), force=True)
        run_attempt(store, attempt, lambda source: provider, max_retries=2, sleep=advance)
        self.assertEqual(provider.extract.call_count, 3)
        self.assertEqual(store.queue()[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
