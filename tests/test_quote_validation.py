import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

from access_requests.intake import read_document
from access_requests.pipeline import process
from access_requests.validation import InvalidResponse, validate_reply
from support import OfflineTest, reply


class QuoteValidation(OfflineTest):
    def envelope(self, quotes):
        envelope = reply('it-001')
        extraction = json.loads(envelope['output_text'])
        extraction['supporting_quotes'] = quotes
        envelope['output_text'] = json.dumps(extraction)
        return envelope

    def test_accepts_exact_substrings_without_requiring_unique_occurrences(self):
        message = 'Read access for Maya. Read access for Maya.'
        for quotes in ([], ['Read access'], ['Read access', 'Maya', 'Read access']):
            with self.subTest(quotes=quotes):
                self.assertEqual(validate_reply(self.envelope(quotes), message)['supporting_quotes'], quotes)

    def test_rejects_every_inexact_quote(self):
        message = 'Read access for Maya.\nTeam: Café'
        for quote in ('Admin access for Maya.', 'Maya needs read access.',
                      'read access', 'Maya. Team:', 'Cafe\u0301', r'Maya.\nTeam:'):
            with self.subTest(quote=quote), self.assertRaises(InvalidResponse):
                validate_reply(self.envelope(['Read access', quote]), message)

    def test_pipeline_checks_decoded_message_only(self):
        message = 'Read access for Maya.\nTeam: Café'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'IT-001.json'
            path.write_text(json.dumps({'message': message, 'subject': 'Invented quotation'}))
            document = read_document(path)
        for quotes, accepted in ((['Maya.\nTeam: Café'], True),
                                 (['Read access', 'Invented quotation'], False),
                                 (['Maya needs read access.'], False),
                                 ([r'Maya.\nTeam: Caf\u00e9'], False)):
            with self.subTest(quotes=quotes):
                provider = Mock(response_source='mock')
                provider.extract_source.return_value = self.envelope(quotes)
                result = process(document, provider)
                if accepted:
                    self.assertEqual(result['extraction']['supporting_quotes'], quotes)
                    self.assertIsNone(result['error'])
                else:
                    self.assertIsNone(result['extraction'])
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(result['error']['category'], 'invalid-response')
                    self.assertEqual(result['next_action'], 'retry-extraction')
