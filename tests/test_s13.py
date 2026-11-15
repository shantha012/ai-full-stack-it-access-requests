import hashlib
import json
from support import OfflineTest, ROOT, MOCKS

class T26(OfflineTest):
    def test_independently_authored_paraphrase(self):
        # Artifact failure must happen before generic pipeline invocation.
        source=ROOT/'tests/fixtures/IT-021.json'
        export=json.loads(source.read_text())
        self.assertIn('new access window',export['message'])
        from access_requests.intake import read_document
        from access_requests.pipeline import process
        from access_requests.provider import MockProvider
        record=process(read_document(source),MockProvider(MOCKS,['it-021']))
        expected=dict(request_id='IT-021',request_date='2026-10-22',kind='new',requester='Maya Chen',team='Analytics',
                      system='Atlas',environment='staging',permission='read',start_date='2026-10-23',end_date='2026-11-06',
                      manager='Priya Shah',business_purpose='checking the weekly conversion dashboard against the revised event definitions')
        self.assertEqual({k:record['extraction'][k] for k in expected},expected)
        self.assertEqual((record['status'],record['owner'],record['next_action']),('review','System Owner','review-request'))
        self.assertEqual(record['extraction']['issues'],[])
        for quote in record['extraction']['supporting_quotes']: self.assertIn(quote,export['message'])
