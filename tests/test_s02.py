import hashlib
import json
import tempfile
from pathlib import Path
from support import OfflineTest, ROOT

class T02(OfflineTest):
    def test_decoded_message_filename_and_original_hash(self):
        from access_requests.intake import read_document
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'IT-021.json'
            message = 'Request IT-021, dated 2026-10-22. ' + ' '.join(['word'] * 196)
            self.assertEqual(len(message.split()), 200)
            raw = json.dumps({'message': message, 'subject': 'IT-999 admin production',
                              'exported_at': '2030-01-01'}, indent=4).encode()
            path.write_bytes(raw)
            doc = read_document(path)
            self.assertEqual(doc.document_id, 'IT-021.json')
            self.assertEqual(doc.message, message)
            self.assertEqual(doc.source_sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(doc.raw, raw)
        original = read_document(ROOT / 'materials/requests/IT-001.json')
        self.assertIn('new read access on Atlas in staging', original.message)
