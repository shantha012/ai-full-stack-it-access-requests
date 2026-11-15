import json
import re
from support import OfflineTest, ROOT, MOCKS, reply, run_case

# Frozen from L01 before any measured extraction exists.
L01 = dict(request_id='IT-001',request_date='2026-10-22',kind='new',requester='Maya Chen',
           team='Analytics',system='Atlas',environment='staging',permission='read',
           business_purpose='checking the weekly conversion dashboard with the new event definition changes',
           start_date='2026-10-23',end_date='2026-11-06',manager='Priya Shah')
REQUIRED = list(L01)
REQUIRED.remove('kind')

class T04(OfflineTest):
    def test_complete_source_to_policy(self):
        record = run_case(1)
        self.assertEqual({k:record['extraction'][k] for k in L01}, L01)
        self.assertEqual((record['status'],record['owner'],record['next_action']),
                         ('review','System Owner','review-request'))
        self.assertIsNone(record['error'])
        self.assertEqual(record['response_source'],'mock')
        message = json.loads((ROOT/'materials/requests/IT-001.json').read_text())['message']
        for quote in record['extraction']['supporting_quotes']: self.assertIn(quote,message)
        for field in ('request_date','start_date','end_date'):
            self.assertRegex(record['extraction'][field],r'^\d{4}-\d{2}-\d{2}$')

class T05(OfflineTest):
    def test_missing_and_relative_dates(self):
        for number, fields in ((10,['end_date']),(11,['start_date','end_date'])):
            result = run_case(number)
            self.assertEqual(result['next_action'],'clarify')
            for field in fields:
                self.assertIsNone(result['extraction'][field])
                self.assertTrue(any(field in issue for issue in result['extraction']['issues']))

    def test_each_required_fact_new_and_change(self):
        from access_requests.pipeline import process
        from access_requests.intake import Document
        from access_requests.provider import MockProvider
        for kind in ('new','change'):
            for field in REQUIRED:
                with self.subTest(kind=kind,missing=field):
                    name = f'missing-{kind}-{field}'
                    message = (ROOT / f'tests/fixtures/{name}.txt').read_text()
                    result = process(Document('IT-021.json','hash',message,b''),MockProvider(MOCKS,[name]))
                    self.assertIsNone(result['extraction'][field])
                    self.assertEqual(result['next_action'],'clarify')

class T06(OfflineTest):
    def test_conflicting_alternatives_retained(self):
        for number, field, quotes in ((4,'environment',['read access in staging','This request is for the production environment.']),
                                      (20,'manager',['My manager is Priya Shah.','The manager for this request is Elena Park.'])):
            result=run_case(number)
            extraction=result['extraction']
            self.assertIsNone(extraction[field])
            self.assertEqual(result['next_action'],'clarify')
            self.assertTrue(any('conflict' in i for i in extraction['issues']))
            joined=' '.join(extraction['supporting_quotes'])
            for quote in quotes: self.assertIn(quote,joined)
