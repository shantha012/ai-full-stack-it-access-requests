import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from test_s09 import DurableCase
from support import ROOT, MOCKS

class T22(DurableCase):
    def test_completed_work_readable_while_another_waits(self):
        from access_requests.engine import Engine
        entered, release, ready = Event(), Event(), Event()
        one=self.provider('it-001');one.barrier=(entered,release)
        two=self.provider('it-002')
        class Select:
            def for_document(inner, document_id): return one if document_id=='IT-001.json' else two
        engine=Engine(self.store,workers=2)
        original=self.store.finish
        def finish(*args):
            record=original(*args)
            if record and record['document_id']=='IT-002.json': ready.set()
            return record
        self.store.finish=finish
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(engine.intake,[self.one,self.two],Select())
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(ready.wait(3))
                current=self.store.current()
                self.assertEqual([r['document_id'] for r in current],['IT-002.json'])
                self.assertEqual(current[0]['owner'],'Security Review')
                pending=self.store.pending()
                self.assertEqual(pending[0]['document_id'],'IT-001.json')
                self.assertEqual(pending[0]['state'],'running')
            finally: release.set()
            future.result(4)
        self.assertEqual(len(self.store.current()),2)
        self.assertEqual(self.store.pending(),[])

class T23(DurableCase):
    def test_killed_process_claim_reclaimed_and_completed_work_preserved(self):
        from access_requests.engine import Engine
        self.engine.intake([self.two],self.provider('it-002'))
        code='''
import sys
from access_requests.storage import Store
from access_requests.engine import Engine
from access_requests.provider import MockProvider
class Block(MockProvider):
    def extract(self, message):
        print('CLAIMED',flush=True)
        sys.stdin.readline()
        return super().extract(message)
Engine(Store(sys.argv[1]),lease_seconds=0).intake([sys.argv[2]],Block(sys.argv[3],['it-001']))
'''
        child=subprocess.Popen([sys.executable,'-c',code,str(self.store.path),str(self.one),str(MOCKS)],
                               cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        try:
            self.assertEqual(child.stdout.readline().strip(),'CLAIMED')
            self.assertEqual(self.store.pending()[0]['state'],'running')
            child.kill();child.wait(3)
        finally:
            child.stdin.close();child.stdout.close()
        result=Engine(self.store).resume(self.provider('it-001'))
        self.assertEqual(len(result),1)
        self.assertEqual(len(self.store.current()),2)
        self.assertEqual(len(self.store.attempts()),2)
        self.assertEqual(self.store.pending(),[])
        # A completed commit is never repeated by resume.
        unused=self.provider()
        self.assertEqual(Engine(self.store).resume(unused),[])
        self.assertEqual(unused.calls,0)

class T24(DurableCase):
    def test_older_completion_cannot_replace_last_registered_source(self):
        from access_requests.engine import Engine
        entered, release=Event(),Event()
        delayed=self.provider('it-001');delayed.barrier=(entered,release)
        changed=self.root/'IT-001.json'
        export=json.loads(self.one.read_text()); export['message']+=' Correction: end date is 2026-11-09.'
        changed.write_text(json.dumps(export))
        with ThreadPoolExecutor(1) as pool:
            old=pool.submit(self.engine.intake,[self.one],delayed)
            try:
                self.assertTrue(entered.wait(3))
                Engine(self.store).intake([changed],self.provider('it-001-revised'))
            finally: release.set()
            old.result(4)
        self.assertEqual(self.store.current()[0]['extraction']['end_date'],'2026-11-09')
        self.assertEqual(len(self.store.attempts()),2)
        self.store.export(self.root/'deliverables')
        rows=json.loads(((self.root/'deliverables').resolve()/'queue.json').read_text())
        self.assertEqual(rows[0]['attempt_id'],self.store.current()[0]['attempt_id'])
