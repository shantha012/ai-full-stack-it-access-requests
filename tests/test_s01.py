from support import OfflineTest, MOCKS, reply

class T01(OfflineTest):
    def test_saved_reply_script_counts_and_barrier(self):
        from access_requests.provider import MockProvider, ProviderError
        from threading import Event, Thread
        provider = MockProvider(MOCKS, ['complete', 'refusal', 'interrupted', 'unavailable'])
        entered, release = Event(), Event()
        provider.barrier = (entered, release)
        results = []
        worker = Thread(target=lambda: results.append(provider.extract('message')))
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(results, [])
        release.set(); worker.join(2)
        self.assertEqual(results, [reply('complete')])
        provider.barrier = None
        self.assertEqual(provider.extract('data')['status'], 'refused')
        self.assertEqual(provider.extract('data')['status'], 'incomplete')
        with self.assertRaises(ProviderError): provider.extract('data')
        self.assertEqual(provider.calls, 4)
