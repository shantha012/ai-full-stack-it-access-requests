from support import OfflineTest, run_case, MOCKS

class T07(OfflineTest):
    def test_withdrawal_precedes_completeness(self):
        from access_requests.pipeline import process
        from access_requests.intake import Document
        from access_requests.provider import MockProvider
        for result in (run_case(5), process(Document('IT-005.json','hash','Withdraw IT-005. Date: 2026-10-22.',b''),
                                           MockProvider(MOCKS,['minimal-withdrawal']))):
            self.assertEqual((result['status'],result['owner'],result['next_action']),('review','IT Service Desk','confirm-withdrawal'))
            self.assertEqual(result['extraction']['request_id'],'IT-005')
            self.assertTrue(result['extraction']['issues'])

class T08(OfflineTest):
    def test_change_new_permission_and_all_risk_triggers(self):
        for n, permission in ((2,'write'),(7,'write'),(12,'admin'),(19,'read')):
            with self.subTest(n=n):
                result=run_case(n)
                self.assertEqual(result['extraction']['permission'],permission)
                self.assertEqual((result['status'],result['owner'],result['next_action']),('review','Security Review','review-risk-then-owner'))
        result=run_case(8)
        self.assertEqual(result['extraction']['environment'],'staging')
        self.assertEqual(result['owner'],'System Owner')

class T09(OfflineTest):
    def test_corrections_and_reversed_dates(self):
        result=run_case(15)
        self.assertEqual((result['extraction']['start_date'],result['extraction']['end_date']),('2026-10-29','2026-10-31'))
        self.assertEqual(result['next_action'],'review-request')
        result=run_case(14)
        self.assertEqual((result['extraction']['start_date'],result['extraction']['end_date']),('2026-11-05','2026-11-02'))
        self.assertEqual(result['next_action'],'clarify')
        self.assertTrue(any('start_date' in i for i in result['extraction']['issues']))

class T10(OfflineTest):
    def test_mismatch_and_nonrequest(self):
        result=run_case(16)
        self.assertEqual(result['extraction']['request_id'],'IT-061')
        self.assertEqual(result['next_action'],'clarify')
        self.assertTrue(any('mismatch' in i for i in result['extraction']['issues']))
        for n,saved in ((17,None),(1,'kind-other'),(1,'kind-None')):
            self.assertEqual(run_case(n,saved)['next_action'],'clarify')
