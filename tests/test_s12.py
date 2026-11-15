import dataclasses
import json
from urllib.error import HTTPError
from support import OfflineTest, ROOT, reply

class T25(OfflineTest):
    def test_fake_transport_wire_contract_and_redaction(self):
        from access_requests.http_provider import ResponsesProvider
        from access_requests.config import Settings
        from access_requests.intake import read_document
        from access_requests.pipeline import process
        settings=Settings(provider='openai',endpoint='https://example.invalid/v1/responses',timeout=9,max_output_tokens=777)
        sentinel='dummy-credential-ONLY-IN-TEST'
        calls=[]
        responses=iter(['http-complete','http-refusal','http-incomplete'])
        def transport(url,headers,payload,timeout):
            calls.append((url,headers,payload,timeout))
            return reply(next(responses))
        provider=ResponsesProvider(settings,transport=transport,environment={'API_KEY':sentinel})
        doc=read_document(ROOT/'materials/requests/IT-001.json')
        complete=process(doc,provider,settings)
        self.assertEqual(complete['owner'],'System Owner')
        self.assertEqual(complete['response_source'],'openai/'+settings.model)
        url,headers,payload,timeout=calls[0]
        self.assertEqual(url,settings.endpoint)
        self.assertEqual(timeout,9)
        self.assertEqual(headers['Authorization'],'Bearer '+sentinel)
        self.assertEqual(payload['model'],settings.model)
        self.assertEqual(payload['max_output_tokens'],777)
        self.assertEqual(payload['text']['format']['schema'],settings.schema)
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(payload['input'][0]['role'],'user')
        self.assertEqual(payload['input'][0]['content'],doc.message)
        self.assertIn('untrusted',payload['instructions'])
        for expected in ('refusal','incomplete'):
            result=process(doc,provider,settings)
            self.assertEqual(result['error']['category'],expected)
            self.assertIsNone(result['extraction'])
        evidence=provider.evidence(doc.message)
        self.assertNotIn(sentinel,json.dumps(evidence))
        self.assertEqual(evidence['request']['model'],settings.model)
        self.assertIn('refusal',evidence['handlers'])
        for injected in (TimeoutError(sentinel),HTTPError(settings.endpoint,429,sentinel,{},None),
                         HTTPError(settings.endpoint,503,sentinel,{},None),ValueError(sentinel)):
            def broken(*args): raise injected
            failed=ResponsesProvider(settings,transport=broken,environment={'API_KEY':sentinel})
            result=process(doc,failed,settings)
            self.assertEqual(result['status'],'error')
            self.assertNotIn(sentinel,json.dumps(result))
