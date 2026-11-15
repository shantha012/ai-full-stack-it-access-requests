"""Source-authored boundary input and adversarial date-format checks, offline."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

from access_requests.intake import read_document
from access_requests.pipeline import process
from access_requests.validation import InvalidResponse, validate_reply
from support import OfflineTest, ROOT, reply


class AcceptanceGaps(OfflineTest):
    def test_200_word_cli_intake_queue_and_export(self):
        # Expected facts are authored here, independently of provider output.
        facts = dict(request_id='IT-901', request_date='2026-10-22', kind='new',
                     requester='Maya Chen', team='Analytics', system='Atlas',
                     environment='staging', permission='read',
                     business_purpose='checking dashboard totals', start_date='2026-10-23',
                     end_date='2026-11-06', manager='Priya Shah')
        source = ('Request IT-901 dated 2026-10-22. This is a new request. '
                  'Requester: Maya Chen. Team: Analytics. System: Atlas. '
                  'Environment: staging. Permission: read. Purpose: checking dashboard totals. '
                  'Start: 2026-10-23. End: 2026-11-06. Manager: Priya Shah.')
        message = source + ' ' + ' '.join(['context'] * (200 - len(source.split())))
        self.assertEqual(len(message.split()), 200)
        extraction = dict(facts, supporting_quotes=[source], issues=[])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'IT-901.json'
            raw = json.dumps(dict(message=message, subject='IT-999 admin production')).encode()
            path.write_bytes(raw)
            saved = root / 'mock'
            saved.mkdir()
            (saved / 'corpus-replies.json').write_text(json.dumps({path.name: dict(
                status='completed', output_text=json.dumps(extraction), response_source='mock')}))
            base = [sys.executable, '-m', 'access_requests', '--db', str(root / 'state.sqlite'),
                    '--provider', 'mock', '--mock-dir', str(saved)]

            def cli(*args):
                result = subprocess.run(base + list(args), cwd=ROOT, text=True,
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            self.assertEqual(cli('intake', str(path)), dict(completed=1, errors=0, pending=0))
            current, = cli('queue')
            self.assertEqual({k: current['extraction'][k] for k in facts}, facts)
            self.assertEqual((current['status'], current['owner'], current['next_action']),
                             ('review', 'System Owner', 'review-request'))
            self.assertIsNone(current['error'])
            self.assertEqual(current['source_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(current['document_id'], path.name)
            self.assertEqual(cli('attempts', '--pending')['pending'], [])
            cli('export', '--output', str(root / 'export'))
            exported, = [json.loads(line) for line in
                         (root / 'export/extractions.jsonl').read_text().splitlines()]
            self.assertEqual(exported['extraction'], extraction)
            queue, = json.loads((root / 'export/queue.json').read_text())
            self.assertEqual(queue['attempt_id'], exported['attempt_id'])
            self.assertEqual(queue['source_sha256'], exported['source_sha256'])

    def test_dates_accept_exact_format_and_null(self):
        document = read_document(ROOT / 'materials/requests/IT-001.json')
        for field in ('request_date', 'start_date', 'end_date'):
            for value in (None, '2026-01-09', '2024-02-29'):
                with self.subTest(field=field, value=value):
                    envelope = reply('it-001')
                    extraction = json.loads(envelope['output_text'])
                    extraction[field] = value
                    envelope['output_text'] = json.dumps(extraction)
                    self.assertEqual(validate_reply(envelope, document.message)[field], value)

    def test_malformed_dates_rejected_before_routing(self):
        document = read_document(ROOT / 'materials/requests/IT-001.json')
        for field in ('request_date', 'start_date', 'end_date'):
            for value in ('2026-1-09', '2026-01-9', '09/01/2026', 'tomorrow', '',
                          ' 2026-01-09', '2026-01-09\n', '2026-01-09T00:00:00Z',
                          '２０２６-０１-０９'):
                with self.subTest(field=field, value=value):
                    envelope = copy.deepcopy(reply('it-001'))
                    extraction = json.loads(envelope['output_text'])
                    extraction[field] = value
                    envelope['output_text'] = json.dumps(extraction)
                    with self.assertRaises(InvalidResponse):
                        validate_reply(envelope, document.message)
                    provider = Mock(response_source='mock')
                    provider.extract_source.return_value = envelope
                    result = process(document, provider)
                    self.assertIsNone(result['extraction'])
                    self.assertEqual((result['status'], result['owner'], result['next_action']),
                                     ('error', 'IT Service Desk', 'retry-extraction'))
                    self.assertEqual(result['error']['category'], 'invalid-response')

    def test_invalid_provider_output_durable_error_and_retry(self):
        for invalid in ('date', 'quote'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = ROOT / 'materials/requests/IT-001.json'
                saved = root / 'mock'
                saved.mkdir()
                valid = reply('it-001')

                def save_response(envelope):
                    (saved / 'corpus-replies.json').write_text(json.dumps({source.name: envelope}))

                base = [sys.executable, '-m', 'access_requests', '--db', str(root / 'state.sqlite'),
                        '--provider', 'mock', '--mock-dir', str(saved)]

                def cli(*args):
                    result = subprocess.run(base + list(args), cwd=ROOT, text=True,
                                            capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    return json.loads(result.stdout)

                save_response(valid)
                self.assertEqual(cli('intake', str(source)), dict(completed=1, errors=0, pending=0))
                initial, = cli('queue')
                self.assertIsNone(initial['error'])
                self.assertEqual(initial['extraction']['request_date'], '2026-10-22')

                bad = copy.deepcopy(valid)
                extraction = json.loads(bad['output_text'])
                if invalid == 'date':
                    extraction['request_date'] = '22/10/2026'
                else:
                    extraction['supporting_quotes'].append('This quotation is absent from the source.')
                bad['output_text'] = json.dumps(extraction)
                save_response(bad)
                self.assertEqual(cli('retry', source.name), dict(completed=1, errors=1, pending=0))
                failed, = cli('queue')
                self.assertEqual((failed['status'], failed['owner'], failed['next_action']),
                                 ('error', 'IT Service Desk', 'retry-extraction'))
                self.assertIsNone(failed['extraction'])
                self.assertEqual(failed['error']['category'], 'invalid-response')
                self.assertTrue(failed['error']['message'])
                self.assertIn(source.name, failed['error']['retry_command'])
                self.assertEqual(failed['source_sha256'], initial['source_sha256'])
                self.assertGreater(failed['attempt_id'], initial['attempt_id'])
                self.assertEqual(cli('attempts', source.name), [initial, failed])

                def check_export(current):
                    cli('export', '--output', str(root / 'export'))
                    resolved = (root / 'export').resolve()
                    record, = [json.loads(line) for line in
                               (resolved / 'extractions.jsonl').read_text().splitlines()]
                    queue, = json.loads((resolved / 'queue.json').read_text())
                    for field in ('document_id', 'attempt_id', 'source_sha256',
                                  'status', 'owner', 'next_action', 'snapshot_generation'):
                        self.assertEqual(queue[field], record[field], field)
                    self.assertEqual(record['attempt_id'], current['attempt_id'])
                    self.assertEqual(record['extraction'], current['extraction'])
                    self.assertEqual(record['error'], current['error'])

                check_export(failed)
                save_response(valid)
                self.assertEqual(cli('retry', source.name), dict(completed=1, errors=0, pending=0))
                recovered, = cli('queue')
                self.assertEqual((recovered['status'], recovered['owner'], recovered['next_action']),
                                 ('review', 'System Owner', 'review-request'))
                self.assertIsNone(recovered['error'])
                self.assertEqual(recovered['extraction'], initial['extraction'])
                self.assertEqual(recovered['source_sha256'], initial['source_sha256'])
                self.assertGreater(recovered['attempt_id'], failed['attempt_id'])
                self.assertEqual(cli('attempts', source.name), [initial, failed, recovered])
                self.assertEqual(cli('attempts', '--pending')['pending'], [])
                check_export(recovered)
