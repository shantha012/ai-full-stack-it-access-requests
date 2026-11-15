import copy
import json
from support import OfflineTest, ROOT, reply

class T03(OfflineTest):
    def test_gate_requires_completion_and_exact_schema(self):
        from access_requests.validation import validate_reply, InvalidResponse
        schema = json.loads((ROOT / 'snapshot.schema.json').read_text())
        valid = {k: None for k in schema['required']}
        valid.update(supporting_quotes=[], issues=[])
        envelope = {'status':'completed', 'output_text':json.dumps(valid)}
        self.assertEqual(validate_reply(envelope, ''), valid)
        for field in valid:
            for mode in ('missing', 'type'):
                changed = copy.deepcopy(valid)
                if mode == 'missing': del changed[field]
                else: changed[field] = 42
                with self.subTest(field=field, mode=mode), self.assertRaises(InvalidResponse):
                    validate_reply(dict(envelope, output_text=json.dumps(changed)), '')
        for field in ('kind','environment','permission'):
            with self.subTest(enum=field), self.assertRaises(InvalidResponse):
                validate_reply(dict(envelope, output_text=json.dumps(dict(valid, **{field:'invalid'}))), '')
        for changed in (dict(valid, extra=True), dict(valid, issues=[42]), dict(valid,supporting_quotes=[False])):
            with self.assertRaises(InvalidResponse): validate_reply(dict(envelope,output_text=json.dumps(changed)), '')
        for name in ('refusal','interrupted','complete'):
            with self.subTest(saved=name), self.assertRaises(InvalidResponse): validate_reply(reply(name), '')
        for text in ('{','[]','null'):
            with self.assertRaises(InvalidResponse): validate_reply(dict(envelope,output_text=text), '')
        for status in (None, 'incomplete','failed'):
            with self.assertRaises(InvalidResponse): validate_reply(dict(envelope,status=status), '')
