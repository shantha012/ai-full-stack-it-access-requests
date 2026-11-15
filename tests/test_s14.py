import copy
import json
from test_s09 import DurableCase
from support import ROOT, MOCKS, reply

class T27(DurableCase):
    def test_full_corpus_denominator_differences_and_unresolved(self):
        from access_requests.accuracy import compare, render_report
        from access_requests.provider import CorpusProvider
        expected=json.loads((ROOT/'tests/fixtures/expectations.json').read_text())
        records=self.engine.intake(sorted((ROOT/'materials/requests').glob('*.json')),CorpusProvider(MOCKS))
        self.assertEqual({r['document_id'] for r in records},{f'IT-{n:03}.json' for n in range(1,21)})
        paraphrase=self.engine.intake([ROOT/'tests/fixtures/IT-021.json'],self.provider('it-021'))
        records+=paraphrase
        result=compare(records,expected)
        self.assertEqual(result['denominator'],252)
        self.assertEqual(len(result['unresolved']),22)
        self.assertIsNone(result['final_score'])
        self.assertEqual(result['differences'],[])
        self.assertEqual(result['resolved_matches'],230)
        text=render_report(result,expected)
        self.assertIn('mock',text)
        self.assertIn('unresolved',text)
        self.assertIn('252',text)
        for n in range(1,22): self.assertIn(f'IT-{n:03}.json',text)
        broken=copy.deepcopy(records)
        for field,envelope in reply('accuracy-wrong-fields').items():
            broken[0]['extraction'][field]=json.loads(envelope['output_text'])[field]
        errors=compare(broken,expected)
        self.assertEqual({d['field'] for d in errors['differences']},{'manager','start_date','permission'})
        for d in errors['differences']:
            self.assertEqual(d['document_id'],'IT-001.json')
            self.assertIn('expected',d); self.assertIn('actual',d)
        for variant in (records[1:], [dict(r,extraction=None) if r['document_id']=='IT-001.json' else r for r in records]):
            missing=compare(variant,expected)
            self.assertEqual(missing['denominator'],252)
            self.assertEqual(missing['missing_or_failed_cells'],12)
