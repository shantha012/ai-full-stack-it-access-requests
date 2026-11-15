from support import OfflineTest, ROOT, MOCKS, run_case

class ErrorCase(OfflineTest):
    def check_error(self, saved, category):
        result=run_case(1,saved)
        self.assertEqual((result['status'],result['owner'],result['next_action']),('error','IT Service Desk','retry-extraction'))
        self.assertIsNone(result['extraction'])
        self.assertEqual(result['error']['category'],category)
        self.assertIn('retry',result['error']['retry_command'])
        self.assertIn('IT-001.json',result['error']['retry_command'])
        self.assertTrue(result['error']['message'])
        return result

class T12(ErrorCase):
    def test_failures_unaffected_and_targeted_retry(self):
        from access_requests.pipeline import Dispatcher
        from access_requests.intake import read_document
        from access_requests.provider import MockProvider
        for name in ('unavailable','timeout','rate-limit'):
            self.check_error(name,'provider')
        dispatcher=Dispatcher()
        one=read_document(ROOT/'materials/requests/IT-001.json')
        two=read_document(ROOT/'materials/requests/IT-002.json')
        dispatcher.run(one,MockProvider(MOCKS,['unavailable']))
        dispatcher.run(two,MockProvider(MOCKS,['it-002']))
        before=dispatcher.results[two.document_id]
        dispatcher.retry(one.document_id,MockProvider(MOCKS,['it-001']))
        self.assertEqual(dispatcher.results[one.document_id]['owner'],'System Owner')
        self.assertIs(dispatcher.results[two.document_id],before)

class T13(ErrorCase):
    def test_malformed_and_schema_failures(self):
        for name in ('malformed','schema-invalid'): self.check_error(name,'invalid-response')

class T14(ErrorCase):
    def test_refusal(self): self.check_error('refusal','refusal')

class T15(ErrorCase):
    def test_incomplete_json_and_parseable_reply(self):
        for name in ('interrupted','interrupted-parseable'): self.check_error(name,'incomplete')
