import json
import tempfile
from pathlib import Path
from support import OfflineTest, ROOT, MOCKS

class DurableCase(OfflineTest):
    def setUp(self):
        super().setUp()
        from access_requests.engine import Engine
        from access_requests.storage import Store
        from access_requests.provider import MockProvider
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'state.sqlite'); self.engine=Engine(self.store)
        self.provider=lambda *names: MockProvider(MOCKS,names)
        self.one=ROOT/'materials/requests/IT-001.json'
        self.two=ROOT/'materials/requests/IT-002.json'

class T17(DurableCase):
    def test_unchanged_success_and_failure_reused(self):
        for path, reply in ((self.one,'it-001'),(self.two,'unavailable')):
            first=self.engine.intake([path],self.provider(reply))[0]
            unused=self.provider()
            second=self.engine.intake([path],unused)[0]
            self.assertEqual(first,second)
            self.assertEqual(unused.calls,0)
        self.assertEqual(len(self.store.current()),2)
        self.assertEqual(len(self.store.attempts()),2)

class T18(DurableCase):
    def test_changed_source_retains_old_hash_and_result(self):
        first=self.engine.intake([self.one],self.provider('it-001'))[0]
        export=json.loads(self.one.read_text());export['message']+=' Correction: end date is 2026-11-09.'
        changed=self.root/'IT-001.json'; changed.write_text(json.dumps(export))
        latest=self.engine.intake([changed],self.provider('it-001-revised'))[0]
        self.assertNotEqual(first['source_sha256'],latest['source_sha256'])
        self.assertEqual(latest['extraction']['end_date'],'2026-11-09')
        self.assertEqual(self.store.attempts('IT-001.json')[0],first)
        self.assertEqual(self.store.current(),[latest])

class T19(DurableCase):
    def test_durable_failed_retry_replaces_success(self):
        first=self.engine.intake([self.one],self.provider('it-001'))[0]
        failed=self.engine.retry('IT-001.json',self.provider('unavailable'))
        self.assertEqual(failed['status'],'error')
        self.assertEqual(failed['source_sha256'],first['source_sha256'])
        self.assertNotEqual(failed['attempt_id'],first['attempt_id'])
        self.assertEqual(self.store.current(),[failed])
        self.assertEqual(self.store.attempts()[0],first)
        restored=self.engine.retry('IT-001.json',self.provider('it-001'))
        self.assertEqual(restored['owner'],'System Owner')

class T20(DurableCase):
    def test_omitted_document_remains(self):
        self.engine.intake([self.one,self.two],self.provider('it-001','it-002'))
        unused=self.provider()
        self.engine.intake([self.two],unused)
        self.assertEqual(unused.calls,0)
        self.assertEqual([r['document_id'] for r in self.store.current()],['IT-001.json','IT-002.json'])
