import json
import subprocess
import sys
import tempfile
from pathlib import Path
from support import OfflineTest, ROOT, MOCKS

class T16(OfflineTest):
    def test_independent_attempts_consistent_exports_and_cli(self):
        from access_requests.storage import Store
        from access_requests.engine import Engine
        from access_requests.provider import MockProvider
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            copy=root/'copy-001.json'
            copy.write_bytes((ROOT/'materials/requests/IT-001.json').read_bytes())
            store=Store(root/'state.sqlite')
            engine=Engine(store)
            engine.intake([ROOT/'materials/requests/IT-001.json',copy,ROOT/'materials/requests/IT-002.json'],
                          MockProvider(MOCKS,['it-001','it-001','unavailable']))
            records=store.current()
            self.assertEqual(len(records),3)
            by_id={r['document_id']:r for r in records}
            self.assertEqual(by_id['copy-001.json']['extraction']['request_id'],'IT-001')
            self.assertEqual(by_id['IT-002.json']['status'],'error')
            self.assertIsNone(by_id['IT-001.json']['error'])
            store.export(root/'deliverables')
            self.assertTrue((root/'deliverables').is_symlink())
            resolved=(root/'deliverables').resolve()
            exports=[json.loads(line) for line in (resolved/'extractions.jsonl').read_text().splitlines()]
            queue=json.loads((resolved/'queue.json').read_text())
            self.assertEqual(len(exports),3)
            for record, item in zip(exports,queue):
                for field in ('document_id','attempt_id','source_sha256','settings_fingerprint','policy_version',
                              'status','owner','next_action','snapshot_generation'):
                    self.assertEqual(record[field],item[field])
                for field in ('extraction','error','response_source'): self.assertIn(field,record)
            reopened=Store(root/'state.sqlite')
            self.assertEqual(reopened.current(),records)
            self.assertEqual(len(reopened.attempts()),3)
            output=subprocess.check_output([sys.executable,'-m','access_requests','--db',str(root/'state.sqlite'),'queue'],cwd=ROOT,text=True)
            self.assertEqual(len(json.loads(output)),3)
