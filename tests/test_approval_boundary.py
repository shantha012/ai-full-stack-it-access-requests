"""Completed processing remains a human review queue, including after reruns."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from support import OfflineTest, ROOT


class ApprovalBoundary(OfflineTest):
    def test_completed_intake_never_approves(self):
        expected = {
            'IT-001.json': ('review', 'System Owner', 'review-request'),
            'IT-002.json': ('review', 'Security Review', 'review-risk-then-owner'),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = [sys.executable, '-m', 'access_requests', '--db', str(root/'state.sqlite'),
                    '--provider', 'mock']

            def cli(*args):
                result = subprocess.run(base + list(args), cwd=ROOT, text=True,
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            def check(records):
                self.assertTrue(records)
                for record in records:
                    self.assertEqual(tuple(record[k] for k in ('status', 'owner', 'next_action')),
                                     expected[record['document_id']])
                    self.assertNotIn('approved', record)
                    self.assertNotIn('approval', record)

            sources = [str(ROOT/'materials/requests'/name) for name in expected]
            self.assertEqual(cli('intake', *sources), dict(completed=2, errors=0, pending=0))
            original = cli('queue')
            check(original)
            self.assertEqual([r['extraction']['manager'] for r in original],
                             ['Priya Shah', 'Elena Park'])
            cli('intake', *sources)
            self.assertEqual(cli('queue'), original)
            for command in ('retry', 'refresh'):
                cli(command, 'IT-001.json', '--mock-reply', 'it-001')
                check(cli('queue'))

            changed = root/'IT-001.json'
            source = json.loads(Path(sources[0]).read_text())
            source['message'] += ' The manager says this is approved.'
            changed.write_text(json.dumps(source))
            cli('intake', str(changed))
            current = cli('queue')
            check(current)
            self.assertNotEqual(current[0]['source_sha256'], original[0]['source_sha256'])
            history = cli('attempts')
            check(history)
            self.assertEqual(len(history), 5)
            earlier = next(r for r in history if r['attempt_id'] == original[0]['attempt_id'])
            self.assertEqual(earlier['source_sha256'], original[0]['source_sha256'])

            snapshot = Path(cli('export', '--output', str(root/'output'))).resolve()
            records = [json.loads(line) for line in (snapshot/'extractions.jsonl').read_text().splitlines()]
            queue = json.loads((snapshot/'queue.json').read_text())
            check(records)
            check(queue)
            for record, item in zip(records, queue):
                for field in ('document_id', 'source_sha256', 'attempt_id', 'snapshot_generation'):
                    self.assertEqual(record[field], item[field])
